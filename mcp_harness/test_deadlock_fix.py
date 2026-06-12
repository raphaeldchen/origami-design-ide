"""
Deterministic, key-free proof that the fork->spawn isolation fix is live.

Drives `server.py` over the SAME stdio MCP transport the agent uses (this is the
exact path that used to deadlock 60s on every call), times each tool, and
asserts crash-isolation holds. No ANTHROPIC_API_KEY required: this exercises the
transport + worker isolation, i.e. everything the LLM does minus the LLM.

The bug's signature was: every TreeMaker tool returns "ERROR: compilation timed
out after 60s" because the forked child inherited the stdin lock and deadlocked
before running. So the headline assertion is simply: nothing takes ~60s, and no
result contains the timeout string.

Run:  cd mcp_harness && ./.venv/bin/python test_deadlock_fix.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_HERE = os.path.dirname(os.path.abspath(__file__))
_PYTHON = sys.executable

# Generous ceiling that is still WAY under the 60s deadlock signature. A spawned
# child boots a fresh interpreter + re-imports the .so, so allow a few seconds.
_FAST_CEILING = 25.0

# A path with no built crease pattern: convert must return a CLEAN error FAST
# (proving the child ran), not hang.
_TMD = os.path.join(_HERE, "..", "treemaker", "build", "bin", "pre_build_creases.tmd5")

# A simple 4-leaf star for the compile paths. Whether it yields a .fold or a
# crash-isolation error, it must come back fast — both outcomes prove the fix.
_STAR = [
    {"id": 0, "parent_id": None, "length": 0},
    {"id": 1, "parent_id": 0, "length": 1.0},
    {"id": 2, "parent_id": 0, "length": 1.0},
    {"id": 3, "parent_id": 0, "length": 1.0},
    {"id": 4, "parent_id": 0, "length": 1.0},
]


def _flatten(result) -> str:
    texts = [b.text for b in result.content if getattr(b, "type", None) == "text"]
    return "\n".join(texts).strip()


async def _timed_call(session, name, args) -> tuple[float, str]:
    t0 = time.time()
    result = await session.call_tool(name, args)
    dt = time.time() - t0
    return dt, _flatten(result)


async def main() -> int:
    params = StdioServerParameters(
        command=_PYTHON, args=[os.path.join(_HERE, "server.py")], cwd=_HERE
    )

    failures: list[str] = []

    async with AsyncExitStack() as stack:
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        tools = {t.name for t in (await session.list_tools()).tools}
        print(f"connected; {len(tools)} tools: {', '.join(sorted(tools))}\n")

        # Each entry: (label, tool, args). We assert FAST + no-timeout for all,
        # plus a per-case content expectation.
        cases = [
            ("convert_tmd_to_fold (no-CP base)", "convert_tmd_to_fold",
             {"filepath": _TMD}),
            ("draft_and_compile_full_base (one-shot, spawn worker)",
             "draft_and_compile_full_base", {"tree_nodes": _STAR}),
        ]

        for label, tool, args in cases:
            dt, out = await _timed_call(session, tool, args)
            preview = " ".join(out.split())[:90]
            fast = dt < _FAST_CEILING
            no_timeout = "timed out after" not in out
            ok = fast and no_timeout
            print(f"[{'PASS' if ok else 'FAIL'}] {label}")
            print(f"        {dt*1000:7.1f} ms | {preview!r}")
            if not fast:
                failures.append(f"{label}: took {dt:.1f}s (deadlock signature)")
            if not no_timeout:
                failures.append(f"{label}: returned the 60s timeout string")

        # Incremental recipe path: new_base -> apply_symmetry -> compile_base.
        # This is the one that USED to fork a live engine; now the worker must
        # rebuild from the serialized recipe. Each step must return fast.
        print("\n  incremental recipe path (new_base -> symmetry -> compile_base):")
        for label, tool, args in [
            ("new_base", "new_base", {"tree_nodes": _STAR}),
            ("apply_symmetry(1,2)", "apply_symmetry", {"node_a": 1, "node_b": 2}),
            ("compile_base (rebuild-from-recipe in spawned child)",
             "compile_base", {}),
        ]:
            dt, out = await _timed_call(session, tool, args)
            preview = " ".join(out.split())[:90]
            fast = dt < _FAST_CEILING
            no_timeout = "timed out after" not in out
            ok = fast and no_timeout
            print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
            print(f"          {dt*1000:7.1f} ms | {preview!r}")
            if not fast:
                failures.append(f"{label}: took {dt:.1f}s (deadlock signature)")
            if not no_timeout:
                failures.append(f"{label}: returned the 60s timeout string")

    print()
    if failures:
        print("RESULT: FAIL — deadlock/timeout signature still present:")
        for f in failures:
            print("  -", f)
        return 1
    print("RESULT: PASS — every tool returned fast through stdio MCP; the "
          "fork deadlock is gone and crash-isolation holds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
