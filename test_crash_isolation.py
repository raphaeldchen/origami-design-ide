"""
Prove `_run_isolated` contains a hard child SIGSEGV (not just a Python error).

The crash worker is a real top-level function so the spawned child can import it
by reference (the same requirement the real workers satisfy). It null-derefs to
raise SIGSEGV; the parent must translate the child's exit code -11 into a clean
error string and KEEP RUNNING.

Run:  cd mcp_harness && ./.venv/bin/python test_crash_isolation.py
"""

import time

import server


def _seg(queue):
    """Hard-crash the child with SIGSEGV; never reaches queue.put."""
    import ctypes

    ctypes.string_at(0)  # null deref -> SIGSEGV (exit code -11)


if __name__ == "__main__":
    t = time.time()
    out = server._run_isolated(_seg)
    dt = time.time() - t

    print(f"child crashed, parent still alive after {dt * 1000:.0f} ms")
    print("returned:", out[:130])

    assert out.startswith("ERROR: the geometry engine crashed"), out
    assert "exit code -11" in out, f"expected SIGSEGV (-11), got: {out}"
    print("PASS: SIGSEGV in spawned child contained as a clean error; "
          "the server process survived.")
