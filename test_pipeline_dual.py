"""
Key-free proof that the agent's ENTIRE tool substrate works through MCP.

Connects to BOTH backend servers exactly as agent_loop.connect_servers does
(treemaker + linter over stdio), runs dynamic tool discovery with unique routing,
then drives the real Tier-3 chain: a TreeMaker tool, then the Oriedita linter.
This is everything the AI Orchestrator does minus the LLM's natural-language
planning — so a PASS here means the only thing left to exercise is the model glue.

Run:  cd mcp_harness && ./.venv/bin/python test_pipeline_dual.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_HERE = os.path.dirname(os.path.abspath(__file__))
_PYTHON = sys.executable

_SERVERS = {
    "treemaker": StdioServerParameters(
        command=_PYTHON, args=[os.path.join(_HERE, "server.py")], cwd=_HERE
    ),
    "linter": StdioServerParameters(
        command=_PYTHON, args=[os.path.join(_HERE, "linter_server.py")], cwd=_HERE
    ),
}

# A square creased on both diagonals: a single degree-4 interior vertex at the
# center, all angles 90 deg (Kawasaki: 90+90 == 90+90), assigned 3 mountains +
# 1 valley (Maekawa: |M - V| == 2). This is the foundational flat fold (collapse
# the square to a quarter triangle), so the linter should return "Pass".
_GOOD_FOLD = json.dumps({
    "file_spec": 1.1,
    "frame_attributes": ["2D"],
    "vertices_coords": [[0, 0], [1, 0], [1, 1], [0, 1], [0.5, 0.5]],
    "edges_vertices": [[0, 1], [1, 2], [2, 3], [3, 0], [0, 4], [1, 4], [2, 4], [3, 4]],
    "edges_assignment": ["B", "B", "B", "B", "M", "M", "M", "V"],
    "faces_vertices": [[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]],
})


def _flatten(result) -> str:
    return "\n".join(
        b.text for b in result.content if getattr(b, "type", None) == "text"
    ).strip()


async def _timed(session, name, args):
    t0 = time.time()
    res = await session.call_tool(name, args)
    return time.time() - t0, _flatten(res)


async def main() -> int:
    route: dict[str, ClientSession] = {}
    failures: list[str] = []

    async with AsyncExitStack() as stack:
        # --- dynamic discovery across both servers, unique-name routing -------
        for label, params in _SERVERS.items():
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            for tool in (await session.list_tools()).tools:
                if tool.name in route:
                    raise RuntimeError(f"duplicate tool {tool.name!r}")
                route[tool.name] = session
        print(f"connected 2 servers; {len(route)} tools discovered: "
              f"{', '.join(sorted(route))}\n")

        # --- step 1: a TreeMaker tool (spawn worker, fast clean error) --------
        dt, out = await _timed(
            route["convert_tmd_to_fold"], "convert_tmd_to_fold",
            {"filepath": os.path.join(_HERE, "..", "treemaker", "build", "bin",
                                      "pre_build_creases.tmd5")})
        print(f"[treemaker] convert_tmd_to_fold  {dt*1000:6.0f} ms")
        print(f"            -> {' '.join(out.split())[:88]!r}")
        if dt >= 25 or "timed out after" in out:
            failures.append("convert_tmd_to_fold hit the deadlock signature")

        # --- step 2: the Oriedita linter on a known flat-foldable FOLD --------
        dt, out = await _timed(
            route["validate_flat_foldability"], "validate_flat_foldability",
            {"fold_json_string": _GOOD_FOLD})
        print(f"[linter]    validate_flat_foldability  {dt*1000:6.0f} ms")
        print(f"            -> {' '.join(out.split())[:88]!r}")
        if out != "Pass":
            failures.append(f"linter did not Pass the known-good FOLD: {out!r}")

    print()
    if failures:
        print("RESULT: FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("RESULT: PASS — both MCP servers reachable; TreeMaker tool returns "
          "fast (no deadlock); Oriedita linter validates a known-good FOLD as "
          "'Pass'. The full tool substrate the agent drives is healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
