"""kaizen-test pure-function core — classify / dispatch / report.

Layered per onion-DDD: this module holds the DOMAIN — pure functions
that decide what runner to use for a test file and how to format
results. The CLI adapter (test_runner.py) imports + composes.

Design contract (per pref-prcdr-contract-declared):
  PROGRAMMABLE  — every public callable is pure
  REPRODUCIBLE  — same inputs → same outputs
  CONSISTENT    — single return shape per function
  DETERMINISTIC — no wall-clock, no env reads, no I/O
  REUSABLE      — new runner styles plug in via the dispatch table
"""
from __future__ import annotations

import re
from pathlib import Path

# ─── classify_style ────────────────────────────────────────────────────

_UNITTEST_PARENT_RE = re.compile(r"\bclass\s+\w+\s*\(\s*unittest\.TestCase\s*\)")
_BARE_TEST_CLASS_RE = re.compile(r"^class\s+Test\w*\s*:", re.MULTILINE)
_MODULE_TEST_FN_RE  = re.compile(r"^def\s+test_\w+\s*\(", re.MULTILINE)


def classify_style(path: Path) -> str:
    """Return "unittest" | "pytest" | "bash" based on filename + content.

    Priority:
      1. .sh suffix → "bash"
      2. File body contains `class X(unittest.TestCase)` → "unittest"
         (preferred even when bare classes also present — unittest
         discovery picks up the TestCase subclasses cleanly)
      3. Bare `class TestX:` OR module-level `def test_x(...)` → "pytest"
      4. Anything else (empty/placeholder) → "unittest" (default;
         unittest's "0 tests found" rc=5 is then handled by the dispatch
         fallback in the CLI layer)
    """
    if path.suffix == ".sh":
        return "bash"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "unittest"
    if _UNITTEST_PARENT_RE.search(text):
        return "unittest"
    if _BARE_TEST_CLASS_RE.search(text) or _MODULE_TEST_FN_RE.search(text):
        return "pytest"
    return "unittest"


# ─── dispatch_cmd ──────────────────────────────────────────────────────

def dispatch_cmd(path: Path, *, style: str,
                  python_exe: str = "python3") -> list[str]:
    """Build the subprocess argv for running `path` under `style`.

    Returns a plain list — no subprocess.run call, no env. Caller composes.

    Shapes:
      unittest → [python, -m, unittest, tests.<stem>]   (module form)
      pytest   → [python, -m, pytest, -q, tests/path.py] (file form)
      bash     → [bash, tests/path.sh]
    """
    p = str(path)
    if style == "unittest":
        # tests/test_foo.py → tests.test_foo
        mod = p.replace("/", ".")
        if mod.endswith(".py"):
            mod = mod[:-3]
        return [python_exe, "-m", "unittest", mod]
    if style == "pytest":
        return [python_exe, "-m", "pytest", "-q", p]
    if style == "bash":
        return ["bash", p]
    raise ValueError(f"unknown style {style!r}")


# ─── bench_report ──────────────────────────────────────────────────────

def bench_report(results: list[tuple[str, float, int]], *,
                  top_n: int = 25) -> str:
    """Format per-file timings as a human-readable report.

    `results` is [(mod_name, elapsed_seconds, returncode), ...].
    Returns multi-line string sorted by elapsed (slowest first).
    """
    sorted_r = sorted(results, key=lambda r: -r[1])[:top_n]
    lines = [f"top {len(sorted_r)} slowest of {len(results)} files:"]
    for mod, t, rc in sorted_r:
        marker = "fail" if rc not in (0, 5) else "    "
        lines.append(f"  {marker} {t:6.2f}s  {mod}")
    total = sum(t for _, t, _ in results)
    failed = sum(1 for _, _, rc in results if rc not in (0, 5))
    passed = len(results) - failed
    lines.append("")
    lines.append(f"  {len(results)} files, {passed} passed, {failed} failed, "
                  f"total {total:.1f}s sequential ceiling")
    return "\n".join(lines)


__all__ = ["classify_style", "dispatch_cmd", "bench_report"]
