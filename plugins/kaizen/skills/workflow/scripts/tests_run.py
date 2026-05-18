#!/usr/bin/env python3
# consolidated-cli-parent: tests
"""kaizen-tests — unified test harness for the kaizen plugin.

Per user 2026-05-18 sid 32bad1f7 — collapses the 5 historical test
entry points (unittest discover / pytest / run_tests_parallel /
legacy _tests.py / bash test_plugin_root.sh) into one CLI.

## Subcommands

    kaizen-test                     # full suite (parallel, auto-style)
    kaizen-test --affected          # only tests for staged files
    kaizen-test --pattern test_X*   # glob filter
    kaizen-test --concurrency N     # override (default: cpu_count)
    kaizen-test --json              # structured envelope
    kaizen-test bench [--top-n N]   # per-file timing report (find slow ones)

## Style auto-detection

Each file is classified via `_tests_run.classify_style`:
  - .sh → bash
  - unittest.TestCase subclass present → unittest
  - bare `class TestX:` / module-level `def test_x` → pytest
  - else → unittest (with rc=5 graceful handling)

The correct dispatcher is invoked per file — no manual style flags
needed, no mixed-suite gymnastics.

## Design contract

  PROGRAMMABLE  — pure helpers in _tests_run; CLI is thin shell
  REPRODUCIBLE  — same suite + concurrency → same pass/fail breakdown
  CONSISTENT    — --json everywhere; exit 0 on pass; 1 on any failure
  DETERMINISTIC — no randomness; ordering is asyncio.gather (input order)
  REUSABLE      — add a new style by extending the 3 pure functions
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import _tests_run as _tr  # noqa: E402


def _discover(tests_dir: Path, pattern: str = "test_*") -> list[Path]:
    """Find test files matching pattern. Includes .py + .sh."""
    if not tests_dir.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(tests_dir.iterdir()):
        if not p.is_file() or p.name == "__init__.py":
            continue
        # Honor pattern for .py; always pick up matching .sh
        if p.suffix in (".py", ".sh"):
            # Substring-or-glob: bare "test_*" → starts with "test_"
            import fnmatch
            stem_match = fnmatch.fnmatch(p.stem, pattern.replace(".py", "")
                                            .replace(".sh", ""))
            if stem_match:
                out.append(p)
    return out


def _resolve_concurrency(arg: int | None) -> int:
    """CLI > env > nproc, floor=1."""
    if arg and arg > 0:
        return arg
    env = os.environ.get("KAIZEN_TEST_CONCURRENCY")
    if env:
        try:
            v = int(env)
            if v > 0:
                return v
        except ValueError:
            pass
    return max(1, os.cpu_count() or 1)


async def _run_one(path: Path, sem: asyncio.Semaphore, cwd: Path
                     ) -> tuple[str, float, int, str]:
    """Spawn the right subprocess for `path` based on its style.

    Returns (display_name, elapsed_s, returncode, combined-output).
    Display name is `tests.<stem>` for .py and basename for .sh.
    """
    style = _tr.classify_style(path)
    # dispatch_cmd needs a path relative to cwd (so module form
    # `tests.<stem>` resolves correctly); absolute paths produce
    # `.tmp.xxx.tests.<stem>` which unittest can't import.
    try:
        rel = path.relative_to(cwd)
    except ValueError:
        rel = path
    cmd = _tr.dispatch_cmd(rel, style=style, python_exe=sys.executable)
    display = (f"tests.{path.stem}" if path.suffix == ".py" else path.name)
    async with sem:
        t0 = time.time()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
        )
        out, err = await proc.communicate()
        elapsed = time.time() - t0
    combined = (err or b"").decode() + (out or b"").decode()
    rc = proc.returncode
    # pytest rc=5 (no tests) is OK — same convention as unittest
    if style == "pytest" and rc == 5:
        rc = 0
    return display, elapsed, rc, combined


async def _run_all(paths: list[Path], cwd: Path, concurrency: int
                     ) -> list[tuple[str, float, int, str]]:
    sem = asyncio.Semaphore(concurrency)
    return await asyncio.gather(*(_run_one(p, sem, cwd) for p in paths))


def cmd_run(args) -> int:
    root = Path(args.root).resolve()
    tests_dir = root / args.tests_dir
    paths = _discover(tests_dir, args.pattern)
    if args.affected:
        # Subset to affected tests via the existing helper
        try:
            sys.path.insert(0, str(SCRIPT_DIR))
            import _affected_tests as _at
            staged = _at.read_staged_files()  # type: ignore
            affected_mods = _at.affected_modules(staged)  # type: ignore
            if affected_mods != "FULL":
                wanted = {m.split(".", 1)[1] for m in affected_mods
                           if m.startswith("tests.")}
                paths = [p for p in paths if p.stem in wanted]
        except (ImportError, AttributeError):
            pass  # fall through to full run when affected helper unavailable
    concurrency = _resolve_concurrency(args.concurrency)
    if not paths:
        if args.json:
            print(json.dumps({"passed": 0, "failed": 0, "results": [],
                                "concurrency": concurrency}))
        else:
            print(f"no test files matched (pattern={args.pattern!r})")
        return 0
    t0 = time.time()
    results = asyncio.run(_run_all(paths, root, concurrency))
    elapsed = time.time() - t0
    failed = sum(1 for _, _, rc, _ in results if rc not in (0, 5))
    passed = len(results) - failed
    if args.json:
        print(json.dumps({
            "passed": passed, "failed": failed,
            "concurrency": concurrency,
            "wall_seconds": round(elapsed, 2),
            "results": [{"name": n, "elapsed_s": round(t, 3), "rc": rc}
                         for n, t, rc, _ in results],
        }, indent=2))
    else:
        print(f"kaizen-test: {len(paths)} files, concurrency={concurrency}, "
              f"cwd={root}")
        print(f"{passed} passed, {failed} failed in {elapsed:.1f}s")
        if failed:
            print("\n--- failures ---", file=sys.stderr)
            for n, t, rc, output in results:
                if rc not in (0, 5):
                    print(f"FAIL: {n} (rc={rc}, {t:.2f}s)", file=sys.stderr)
                    tail = "\n".join(output.splitlines()[-20:])
                    print(tail + "\n---", file=sys.stderr)
    return 1 if failed else 0


def cmd_bench(args) -> int:
    root = Path(args.root).resolve()
    tests_dir = root / args.tests_dir
    paths = _discover(tests_dir, args.pattern)
    concurrency = _resolve_concurrency(args.concurrency)
    if not paths:
        print("no test files matched")
        return 0
    results = asyncio.run(_run_all(paths, root, concurrency))
    triples = [(n, t, rc) for n, t, rc, _ in results]
    if args.json:
        print(json.dumps({
            "files": len(triples),
            "sequential_ceiling_s": round(sum(t for _, t, _ in triples), 2),
            "ranked": [{"name": n, "elapsed_s": round(t, 3), "rc": rc}
                        for n, t, rc in sorted(triples, key=lambda r: -r[1])],
        }, indent=2))
    else:
        print(_tr.bench_report(triples, top_n=args.top_n))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-test", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=".",
                    help="repo root (cwd for subprocess; default '.')")
    p.add_argument("--tests-dir", default="tests",
                    help="tests directory under root (default 'tests')")
    p.add_argument("--pattern", default="test_*",
                    help="glob pattern for test stems (default 'test_*')")
    p.add_argument("--concurrency", type=int, default=None,
                    help="max concurrent test-file processes "
                         "(default: KAIZEN_TEST_CONCURRENCY or nproc)")
    p.add_argument("--affected", action="store_true",
                    help="restrict to tests affected by staged files")
    p.add_argument("--json", action="store_true",
                    help="emit JSON envelope")

    sub = p.add_subparsers(dest="cmd")
    pb = sub.add_parser("bench",
                          help="per-file timing report (find slow tests)")
    pb.add_argument("--top-n", type=int, default=25,
                     help="show top N slowest (default 25)")
    pb.set_defaults(fn=cmd_bench)

    args = p.parse_args(argv)
    fn = getattr(args, "fn", cmd_run)
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
