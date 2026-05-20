"""Tests for `kaizen handoff cost` — token-budget estimator.

Per Task #40 brainstorm — top item (impact 5 × effort 1 = score 25).
First-class visibility into "is this handoff approaching the budget
where reading the whole thing wastes tokens?" — pairs with the just-
shipped `parent_handoff` (the recommended remediation is "scaffold
fresh + link via parent_handoff" rather than letting the yaml bloat).

Pure read; no mutation. Uses chars/4 token approximation (kaizen
convention for fast estimates).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_HANDOFF = _KZ / "scripts/handoff/handoff.py"

sys.path.insert(0, str(_KZ / "scripts/handoff"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ / "scripts/rules"))
import handoff as _h  # noqa: E402

_SMALL_YAML = """---
session: test
date: 2026-05-18
status: complete
outcome: SUCCEEDED
---

session_meta:
  cc_session_uuid: 'abc-123'

goal: 'small goal'
now: 'do x'
test: pytest

done_this_session:
  - task: 'wired feature A'
    files: ['a.py']

blockers: []
next:
  - 'next step one'
"""

def _make_big_yaml(n_entries: int) -> str:
    """A yaml with N done_this_session entries — for threshold testing."""
    base = """---
session: test
date: 2026-05-18
status: complete
outcome: SUCCEEDED
---

session_meta:
  cc_session_uuid: 'abc-123'

goal: 'big goal'
now: 'do many things'
test: pytest

done_this_session:
"""
    entries = []
    for i in range(n_entries):
        entries.append(f"  - task: 'task number {i} — lorem ipsum dolor sit amet, "
                        f"consectetur adipiscing elit, sed do eiusmod tempor "
                        f"incididunt ut labore et dolore magna aliqua'\n"
                        f"    files: ['src/file_{i}.py', 'tests/test_{i}.py']\n")
    return base + "".join(entries) + "\nblockers: []\nnext: []\n"

# ─── _approx_tokens ─────────────────────────────────────────────────────

class TestApproxTokens(unittest.TestCase):
    def test_empty_string_is_zero(self):
        self.assertEqual(_h._approx_tokens(""), 0)

    def test_chars_div_4_ceiling(self):
        # 7 chars → ceil(7/4) = 2 (matches a typical tokenizer better than floor)
        self.assertEqual(_h._approx_tokens("abcdefg"), 2)

    def test_long_string(self):
        self.assertEqual(_h._approx_tokens("x" * 400), 100)

# ─── _compute_costs ─────────────────────────────────────────────────────

class TestComputeCosts(unittest.TestCase):
    def test_returns_total_matching_text_length(self):
        result = _h._compute_costs(_SMALL_YAML)
        self.assertEqual(result["size_bytes"], len(_SMALL_YAML.encode("utf-8")))
        self.assertGreater(result["approx_tokens"], 0)

    def test_per_section_breakdown(self):
        result = _h._compute_costs(_SMALL_YAML)
        sections = result["per_section"]
        # Every known body section should appear (even if empty)
        for k in ("done_this_session", "session_meta", "goal", "now",
                   "blockers", "next"):
            self.assertIn(k, sections)
        # done_this_session has the most content here
        self.assertGreater(sections["done_this_session"]["chars"],
                            sections["goal"]["chars"])

    def test_percentages_sum_approximately_to_total(self):
        result = _h._compute_costs(_SMALL_YAML)
        total_pct = sum(s["pct"] for s in result["per_section"].values())
        # Allow some slack — frontmatter + formatting chars not in any section
        # but all section pcts must be ≤ 100
        for s in result["per_section"].values():
            self.assertLessEqual(s["pct"], 100.0)
        self.assertLessEqual(total_pct, 105.0)

# ─── Threshold logic ────────────────────────────────────────────────────

class TestThreshold(unittest.TestCase):
    def test_threshold_default(self):
        result = _h._compute_costs(_SMALL_YAML)
        self.assertEqual(result["threshold_tokens"], 2000)

    def test_threshold_env_overridable(self):
        _orig = os.environ.get("KAIZEN_HANDOFF_COST_TOKEN_BUDGET")
        try:
            os.environ["KAIZEN_HANDOFF_COST_TOKEN_BUDGET"] = "500"
            result = _h._compute_costs(_SMALL_YAML)
            self.assertEqual(result["threshold_tokens"], 500)
        finally:
            if _orig is None:
                os.environ.pop("KAIZEN_HANDOFF_COST_TOKEN_BUDGET", None)
            else:
                os.environ["KAIZEN_HANDOFF_COST_TOKEN_BUDGET"] = _orig

    def test_under_threshold_returns_ok(self):
        result = _h._compute_costs(_SMALL_YAML)
        self.assertFalse(result["over_threshold"])
        self.assertIn("ok", result["recommendation"].lower())

    def test_over_threshold_returns_scaffold_hint(self):
        big = _make_big_yaml(200)
        result = _h._compute_costs(big)
        self.assertTrue(result["over_threshold"])
        self.assertIn("scaffold", result["recommendation"].lower())

# ─── CLI integration ────────────────────────────────────────────────────

class TestCostCLI(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.yaml = self.tmp / "h.yaml"
        self.yaml.write_text(_SMALL_YAML, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_HANDOFF), *args],
            capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )

    def test_cli_json_output_matches_compute_costs(self):
        r = self._run("cost", "--file", str(self.yaml), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertIn("size_bytes", data)
        self.assertIn("approx_tokens", data)
        self.assertIn("per_section", data)

    def test_cli_human_output_lists_top_sections(self):
        r = self._run("cost", "--file", str(self.yaml))
        self.assertEqual(r.returncode, 0)
        # Human format names the biggest section
        self.assertIn("done_this_session", r.stdout)
        self.assertIn("total", r.stdout.lower())

    def test_cli_missing_file_fails(self):
        r = self._run("cost", "--file", str(self.tmp / "nope.yaml"))
        self.assertNotEqual(r.returncode, 0)

if __name__ == "__main__":
    unittest.main()
