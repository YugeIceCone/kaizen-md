#!/usr/bin/env python3
"""kaizen run_tests_parallel — async-bounded-batch unittest runner.

Speeds ci-gate --full from ~70s (sequential `unittest discover`) to
~8s on 32 threads. Pattern lifted from clever-lama-mcp's
ParallelBashRunnerNode (BoundedAsyncParallelBatchNode + Semaphore);
we don't drag in the whole Node+Flow framework for a one-shot runner
— just the async-Semaphore bounded fan-out.

Why parallel beats sequential here:
  - 193 test files × ~30ms python cold-start = ~6s of pure import
    overhead even with no test logic
  - `unittest discover` runs everything in ONE process — fast import
    BUT all tests serial = ~70s wallclock dominated by the slow files
  - Per-file parallel = per-file cold-start, but ~32 files at a time
    in parallel = wallclock floor of (slowest single file) + a few
    seconds

CLI:
    run_tests_parallel.py [--root REPO] [--tests-dir tests] [--pattern test_*.py]
                          [--concurrency N]

Env (in precedence order):
    --concurrency CLI flag  >  KAIZEN_TEST_CONCURRENCY  >  os.cpu_count()
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path


def discover_test_modules(tests_dir: Path,
                            pattern: str = "test_*.py") -> list[str]:
    """Return module names (``tests.<stem>``) for every matching file.
    Empty list when dir is missing or empty."""
    if not tests_dir.is_dir():
        return []
    return [
        f"tests.{p.stem}"
        for p in sorted(tests_dir.glob(pattern))
        if p.is_file() and p.name != "__init__.py"
    ]


def _resolve_concurrency(arg_value: int | None) -> int:
    """CLI > env > nproc, floor=1."""
    if arg_value and arg_value > 0:
        return arg_value
    env = os.environ.get("KAIZEN_TEST_CONCURRENCY")
    if env:
        try:
            v = int(env)
            if v > 0:
                return v
        except ValueError:
            pass
    return max(1, os.cpu_count() or 1)


async def _run_one(mod: str, sem: asyncio.Semaphore, cwd: Path
                     ) -> tuple[str, int, str]:
    """Spawn `python3 -m unittest <mod>` under the semaphore.
    Returns (mod, returncode, combined-stderr-stdout)."""
    async with sem:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "unittest", mod,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
        )
        out, err = await proc.communicate()
        # unittest writes its summary to stderr; keep both
        return mod, proc.returncode, (err or b"").decode() + (out or b"").decode()


async def run_parallel(test_modules: list[str], cwd: Path,
                         concurrency: int) -> tuple[int, list[tuple[str, int, str]]]:
    """Run every module in bounded-parallel async batch.
    Returns (failed_count, results)."""
    sem = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(*(_run_one(m, sem, cwd) for m in test_modules))
    failed = sum(1 for _, rc, _ in results if rc != 0)
    return failed, results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="run_tests_parallel",
        description="Async-bounded-batch parallel unittest runner.",
    )
    p.add_argument("--root", default=".",
                    help="Repo root to run from (cwd for the subprocesses).")
    p.add_argument("--tests-dir", default="tests",
                    help="Tests directory under root (default: tests).")
    p.add_argument("--pattern", default="test_*.py",
                    help="Glob pattern for test files (default: test_*.py).")
    p.add_argument("--concurrency", type=int, default=None,
                    help="Max concurrent test-file processes. Default: nproc, "
                         "overridable via KAIZEN_TEST_CONCURRENCY env.")
    args = p.parse_args(argv)

    root = Path(args.root).resolve()
    tests_dir = root / args.tests_dir
    modules = discover_test_modules(tests_dir, args.pattern)
    concurrency = _resolve_concurrency(args.concurrency)

    print(f"run_tests_parallel: {len(modules)} test files, "
          f"concurrency={concurrency}, cwd={root}")

    if not modules:
        print("0 passed, 0 failed (no test files)")
        return 0

    t0 = time.time()
    failed_count, results = asyncio.run(run_parallel(modules, root, concurrency))
    elapsed = time.time() - t0

    passed = len(results) - failed_count
    print(f"{passed} passed, {failed_count} failed in {elapsed:.1f}s")

    if failed_count:
        print("--- failures ---", file=sys.stderr)
        for mod, rc, output in results:
            if rc != 0:
                print(f"FAIL: {mod} (rc={rc})", file=sys.stderr)
                # Last 30 lines is usually the failure detail
                tail = "\n".join(output.splitlines()[-30:])
                print(tail, file=sys.stderr)
                print("---", file=sys.stderr)
    return 1 if failed_count else 0


if __name__ == "__main__":
    sys.exit(main())
