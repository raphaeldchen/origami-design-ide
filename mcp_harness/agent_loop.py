"""
Tier 2: The AI Orchestrator for the AI-Driven Origami IDE.

A conversational agent that instantiates a Claude model, equips it with the MCP
tools exposed by our two headless backend servers, and runs a tool-calling chat
loop on the command line.

Architecture (one async process, two child MCP servers over stdio):

    agent_loop.py
     |- anthropic.AsyncAnthropic                 -> the LLM (tool-use loop)
     '- MCP stdio clients (the `mcp` SDK)
         |- spawn: python server.py              -> convert_tmd_to_fold, new_base, ...
         '- spawn: python linter_server.py       -> validate_flat_foldability

The agent does NOT compute folding math. It plans, calls the backend tools, reads
their text output (including any "ERROR: ..." strings, which are recoverable
signals, not crashes), and reports to the user.

Tools are discovered DYNAMICALLY from the servers at startup, so the agent
automatically gets every tool a server exposes and stays correct if a server
gains or renames tools.

Run (key required):
    export ANTHROPIC_API_KEY=sk-ant-...
    cd mcp_harness && ./.venv/bin/python agent_loop.py
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass

from anthropic import AsyncAnthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #
_HERE = os.path.dirname(os.path.abspath(__file__))

# Use THIS venv's interpreter for the child servers so the compiled
# `headless_treemaker.so` and the `mcp` package resolve exactly as they do here.
_PYTHON = sys.executable

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096

# Upper bound on consecutive model<->tool round-trips inside a single user turn.
# The agent needs several turns with no human input to draft a tree, fail a
# compile, adjust the constraints, recompile, and finally lint -- so this must be
# well above 1. It is a safety stop against an infinite tool loop, not a budget
# the agent should try to exhaust.
MAX_AGENT_STEPS = 12

# Each entry spawns one MCP server as a subprocess. cwd is pinned to this
# directory so server-relative assets (the .so, the Oriedita jar) are found.
_SERVERS = {
    "treemaker": StdioServerParameters(
        command=_PYTHON, args=[os.path.join(_HERE, "server.py")], cwd=_HERE
    ),
    "linter": StdioServerParameters(
        command=_PYTHON, args=[os.path.join(_HERE, "linter_server.py")], cwd=_HERE
    ),
}

SYSTEM_PROMPT = """\
You are an expert computational origami AI. Your core objective is to \
autonomously design foldable origami crease patterns from natural-language \
requests using the tree method (Robert J. Lang's circle/river packing). You do \
not compute the folding math yourself -- you plan, call the backend tools, read \
their output, and recover from errors on your own.

THE TREE MODEL
A subject is described as a metric tree: leaf nodes are flap tips (legs, head, \
tail), interior nodes form the body, and each edge's `length` is the \
proportional flap length. A typical four-legged animal needs about five leaf \
nodes (4 legs + 1 head/tail) hanging off one or two central body nodes. If you \
are unsure of the exact node JSON schema, call describe_tree_format first.

TWO WAYS TO COMPILE -- PICK ONE, NEVER MIX THEM
The backend exposes two distinct workflows. Symmetry enters each differently, \
and mixing them silently discards your symmetry constraints:
  (A) One-shot: draft_and_compile_full_base(tree_nodes, symmetric_pairs, ...). \
Pass the left/right leaf pairs directly as `symmetric_pairs`. This one call \
builds the tree, applies symmetry, runs scale optimization, builds the Universal \
Molecule (GUI-style, scale-only), and returns FOLD JSON. Do NOT call new_base / \
apply_symmetry on this path -- they are not read by it.
  (B) Incremental: new_base(tree_nodes) -> apply_symmetry(a, b) for each \
left/right pair -> optionally set_edge_strain_fixed(edge) -> compile_base(). \
Here apply_symmetry mutates the live session and compile_base reads it. The \
compile step on this path is compile_base, NOT draft_and_compile_full_base.
Both paths drive the SAME ALM optimizer, so switching from one to the other \
does NOT improve convergence: a tree that fails to pack fails on both. Pick one \
path for the whole design and treat the choice as ergonomics, never as a remedy \
for a packing failure.

SYMMETRY IS CRITICAL. Every bilateral feature (legs, ears, wings) must have its \
left/right leaf nodes paired -- via `symmetric_pairs` on path (A) or \
apply_symmetry on path (B). Without it the ALM optimizer rarely packs the \
circles cleanly and the compile will fail.

ERROR HANDLING -- RECOVER, DO NOT BAIL
A tool result beginning with "ERROR:" is a recoverable signal, not a crash. \
"ERROR: polygon network is not valid" or a convergence timeout means the \
required circles could not pack into the square paper. Do NOT immediately give \
up or ask the user for help. Autonomously retry by:
  1. Confirming symmetry was applied (right path, right leaf pairs).
  2. Changing the tree TOPOLOGY -- the active-path network, not the numbers, \
usually decides whether a base packs. If the optimizer scale reported in the \
error barely moves between attempts, the binding constraint is topological: \
restructure (fewer junctions, regroup which flaps share a hub) rather than only \
nudging lengths.
  3. As a secondary lever, shrinking the offending edge lengths so the flaps \
fit the paper.
  4. Recompiling.
Do NOT switch between the one-shot and incremental paths hoping for a different \
result -- they share one optimizer (see above), so it cannot help. HARD LIMIT: \
after 3 failed compile attempts (counting draft_and_compile_full_base and \
compile_base calls together), STOP. Do not generate further variations. Report \
the failure to the user and explain the distinct variations you tried and why \
you believe the tree will not pack.

ALWAYS LINT THE RESULT
Once you have valid FOLD JSON, ALWAYS pass that exact JSON string into \
validate_flat_foldability. It returns "Pass" when every interior vertex is \
flat-foldable; otherwise it splits violations into "M/V-fixable" problems \
(Maekawa parity -- repairable by flipping mountain/valley assignments) versus \
"geometry" problems (Kawasaki angle sum, number-of-folds, big-little-big -- \
which require moving creases, not relabeling them). Always surface this \
distinction, citing the vertex locations and rule names the linter reports.

(For an already-solved "Golden Base" file the user supplies, use \
convert_tmd_to_fold(filepath) instead of drafting, then lint its FOLD. An \
"ERROR: ... no crease pattern (vertices=0, creases=0)" there is NOT retryable: \
the file was saved before its crease pattern was built; tell the user to open \
it in the TreeMaker GUI, run Action -> Build Crease Pattern, and re-save as \
native v5 .tmd5.)

Be concise and concrete. Report the final FOLD and lint verdict to the user \
only after the design has compiled and been validated."""


# --------------------------------------------------------------------------- #
# Server connection + dynamic tool discovery                                  #
# --------------------------------------------------------------------------- #
@dataclass
class Backend:
    """The connected MCP backends and everything the LLM loop needs to use them."""

    sessions: dict[str, ClientSession]      # server label -> live session
    anthropic_tools: list[dict]             # tool schemas in Anthropic's format
    route: dict[str, ClientSession]         # tool name -> owning session


async def connect_servers(stack: AsyncExitStack) -> Backend:
    """Spawn every MCP server, initialize a session, and discover its tools.

    All subprocesses + sessions are entered on the shared AsyncExitStack, so a
    single `await stack.aclose()` (or leaving the `async with`) tears them all
    down cleanly, even on error.
    """
    sessions: dict[str, ClientSession] = {}
    anthropic_tools: list[dict] = []
    route: dict[str, ClientSession] = {}

    for label, params in _SERVERS.items():
        # stdio_client yields (read, write) streams over the subprocess's pipes.
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        sessions[label] = session

        listed = await session.list_tools()
        for tool in listed.tools:
            if tool.name in route:
                # Two servers exposing the same tool name would make routing
                # ambiguous; fail loud rather than silently shadowing one.
                raise RuntimeError(
                    f"Duplicate tool name {tool.name!r} from server {label!r}; "
                    "tool names must be unique across servers."
                )
            route[tool.name] = session
            anthropic_tools.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    # MCP's inputSchema is already JSON-Schema, which is exactly
                    # what Anthropic's tool `input_schema` expects.
                    "input_schema": tool.inputSchema,
                }
            )

    return Backend(sessions=sessions, anthropic_tools=anthropic_tools, route=route)


async def run_tool(backend: Backend, name: str, args: dict) -> str:
    """Route one tool call to its owning server and return the result as text.

    Backend tools are designed to return strings (including "ERROR: ..."), so we
    flatten the MCP content blocks to text and hand that straight back to the
    model. A transport/exception is also returned as text so the loop survives.
    """
    session = backend.route.get(name)
    if session is None:
        return f"ERROR: no server exposes a tool named {name!r}."
    try:
        result = await session.call_tool(name, args)
    except Exception as exc:  # transport-level failure -> let the model react
        return f"ERROR: tool {name!r} failed to execute: {exc}"

    texts = [
        block.text
        for block in result.content
        if getattr(block, "type", None) == "text"
    ]
    text = "\n".join(texts).strip()
    if result.isError:
        return f"ERROR: {text}" if not text.startswith("ERROR:") else text
    return text or "(tool returned no text output)"


# --------------------------------------------------------------------------- #
# The agentic tool-use loop                                                   #
# --------------------------------------------------------------------------- #
async def agent_turn(
    client: AsyncAnthropic, backend: Backend, messages: list[dict]
) -> None:
    """Run one user turn to completion, streaming assistant text as it arrives.

    Loops while the model keeps requesting tools: stream the assistant message,
    execute every tool_use block, append the tool_result blocks, and re-call the
    model. `messages` is mutated in place so the caller keeps the full history.

    The loop runs up to MAX_AGENT_STEPS model<->tool round-trips without human
    input, so the agent can draft -> fail -> adjust -> recompile -> lint on its
    own. The cap is a safety stop against a runaway tool loop; when it trips we
    still execute and record the pending tool batch first, leaving `messages` in
    a valid state (every tool_use answered by a tool_result) for the next turn.
    """
    for step in range(1, MAX_AGENT_STEPS + 1):
        async with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=backend.anthropic_tools,
            messages=messages,
        ) as stream:
            async for event in stream:
                if (
                    event.type == "content_block_delta"
                    and event.delta.type == "text_delta"
                ):
                    print(event.delta.text, end="", flush=True)
            final = await stream.get_final_message()

        # Record exactly what the model produced (text + any tool_use blocks).
        messages.append({"role": "assistant", "content": final.content})

        if final.stop_reason != "tool_use":
            print()  # newline after the final streamed answer
            return

        # Execute each requested tool and gather the results for the next turn.
        tool_results = []
        for block in final.content:
            if block.type != "tool_use":
                continue
            print(f"\n  [tool] {block.name}({_preview(block.input)})", flush=True)
            output = await run_tool(backend, block.name, block.input)
            print(f"  [<-]  {_preview(output, 160)}", flush=True)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                }
            )

        messages.append({"role": "user", "content": tool_results})

        # Safety stop: the pending tool batch is now recorded, so history is
        # valid. Bail before re-calling the model if we have hit the cap.
        if step == MAX_AGENT_STEPS:
            print(
                f"\n[stopped after {MAX_AGENT_STEPS} tool steps without "
                "finishing; ask me to continue if it needs more]",
                flush=True,
            )
            return
        # Otherwise loop: hand the tool results back so the model can continue.


def _preview(value: object, limit: int = 100) -> str:
    """A compact one-line preview of tool args/results for the transcript."""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --------------------------------------------------------------------------- #
# REPL                                                                        #
# --------------------------------------------------------------------------- #
def _force_utf8_console() -> None:
    """Make stdout/stderr tolerate non-ASCII so print() never crashes.

    Model text and tool output routinely contain non-ASCII (em dashes, ellipses,
    the degree symbol in vertex errors). Under a bare C/ASCII locale (common when
    launched from a minimal shell), every such print() raises UnicodeEncodeError.

    `errors="replace"` is the key guarantee: even if UTF-8 can't be set, the
    worst case is a '?' rather than a crashed turn. For the most robust override,
    launch with `PYTHONUTF8=1`, which flips UTF-8 mode before any code runs.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
            continue
        except (AttributeError, ValueError):
            pass  # not a reconfigurable TextIOWrapper; try a re-wrap below
        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            try:
                setattr(sys, name, io.TextIOWrapper(
                    buffer, encoding="utf-8", errors="replace",
                    line_buffering=True))
            except Exception:
                pass


async def main() -> None:
    _force_utf8_console()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit(
            "ERROR: ANTHROPIC_API_KEY is not set.\n"
            "    export ANTHROPIC_API_KEY=sk-ant-...   then rerun."
        )

    client = AsyncAnthropic()

    async with AsyncExitStack() as stack:
        print("Connecting to MCP backends (spawning server subprocesses)...")
        backend = await connect_servers(stack)

        tool_names = ", ".join(sorted(backend.route))
        print(
            f"Connected. {len(backend.sessions)} server(s), "
            f"{len(backend.route)} tool(s) discovered:\n  {tool_names}\n"
        )
        print(
            "Origami assistant ready. Type a request, or 'exit' to quit.\n"
            "Try: load the golden base at <path/to/base.tmd5> and tell me if it "
            "passes mathematical validation.\n"
        )

        messages: list[dict] = []
        loop = asyncio.get_event_loop()
        while True:
            try:
                # readline in a thread so the event loop (and its subprocess
                # pipes) keep breathing while we wait on the human.
                user = (await loop.run_in_executor(None, input, "you> ")).strip()
            except (EOFError, KeyboardInterrupt):
                print("\nbye.")
                break
            if not user:
                continue
            if user.lower() in {"exit", "quit", ":q"}:
                print("bye.")
                break

            messages.append({"role": "user", "content": user})
            print("\nclaude> ", end="", flush=True)
            try:
                await agent_turn(client, backend, messages)
            except Exception as exc:
                # Keep the REPL alive on any model/transport hiccup.
                print(f"\n[loop error] {exc}")


if __name__ == "__main__":
    asyncio.run(main())
