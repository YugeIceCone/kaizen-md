"""perm-coverage axis (idea #34): every argparse-main script under
skills/workflow/scripts/ has a matching plugin.json permission entry.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/quality"))

import perm_coverage  # noqa: E402


class TestPermCoverage(unittest.TestCase):
    def test_argparse_main_finder_picks_up_known_scripts(self):
        scripts = perm_coverage._argparse_main_scripts(
            _KZ / "skills/workflow/scripts")
        names = {s.name for s in scripts}
        # Known argparse-main scripts that must be picked up
        for known in ("brainstorm.py", "coverage.py", "frontmatter.py"):
            self.assertIn(known, names,
                f"argparse-main detector missed known script {known}")

    def test_perm_index_keys_each_entry_once(self):
        idx = perm_coverage._perm_index(
            _KZ / ".claude-plugin/plugin.json")
        # frontmatter is a known existing entry
        self.assertTrue(
            any("frontmatter.py" in p for p in idx),
            "frontmatter.py expected in plugin.json perm index")

    def test_brainstorm_has_perm(self):
        """Just-shipped brainstorm.py landed with its plugin.json perm."""
        report = perm_coverage.scan(
            scripts_dir=_KZ / "skills/workflow/scripts",
            plugin_json=_KZ / ".claude-plugin/plugin.json",
        )
        names = {g["script"] for g in report["gaps"]}
        self.assertNotIn("brainstorm.py", names,
            "brainstorm.py landed with its perm in BK-012 P3 — gap is a bug")


if __name__ == "__main__":
    unittest.main()
