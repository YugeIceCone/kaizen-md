"""RED first — per-repo lint_fix prefs.

Persists the chosen dispatch strategy (subagent | local_llm) + the
chosen local-LLM model + base_url at `.kaizen/lint_dispatch_prefs.json`
under the repo root. Means: pick once, the rest of the session
(everything happening in this repo) honors the choice.

Run:
    python3 -m unittest tests.test_lint_fix_prefs -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "workflow" / "scripts"))

import lint_fix_prefs as prefs  # noqa: E402


class PrefsRoundtrip(unittest.TestCase):

    def test_load_prefs_empty_when_file_missing(self):
        with tempfile.TemporaryDirectory() as td:
            out = prefs.load_prefs(td)
            self.assertEqual(out, {})

    def test_save_then_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            prefs.save_prefs(td, {"strategy": "local_llm", "model": "qwen-coder"})
            out = prefs.load_prefs(td)
            self.assertEqual(out["strategy"], "local_llm")
            self.assertEqual(out["model"], "qwen-coder")

    def test_save_creates_kaizen_dir(self):
        with tempfile.TemporaryDirectory() as td:
            prefs.save_prefs(td, {"strategy": "subagent"})
            self.assertTrue((Path(td) / ".kaizen").is_dir())
            self.assertTrue((Path(td) / ".kaizen" / "lint_dispatch_prefs.json").is_file())

    def test_save_is_atomic_no_partial_files_on_crash(self):
        """Atomic write = no .tmp leftover after successful save."""
        with tempfile.TemporaryDirectory() as td:
            prefs.save_prefs(td, {"strategy": "subagent"})
            leftovers = list((Path(td) / ".kaizen").glob("*.tmp"))
            self.assertEqual(leftovers, [])


class StrategyHelpers(unittest.TestCase):

    def test_get_strategy_returns_default_when_no_prefs(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(prefs.get_strategy(td), "subagent")

    def test_get_strategy_honors_custom_default(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(prefs.get_strategy(td, default="local_llm"), "local_llm")

    def test_set_strategy_persists_across_calls(self):
        with tempfile.TemporaryDirectory() as td:
            prefs.set_strategy(td, "local_llm")
            self.assertEqual(prefs.get_strategy(td), "local_llm")

    def test_set_strategy_rejects_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                prefs.set_strategy(td, "bogus")

    def test_set_strategy_preserves_other_keys(self):
        with tempfile.TemporaryDirectory() as td:
            prefs.save_prefs(td, {"strategy": "subagent", "model": "alpha", "extra": "keep"})
            prefs.set_strategy(td, "local_llm")
            out = prefs.load_prefs(td)
            self.assertEqual(out["strategy"], "local_llm")
            self.assertEqual(out["model"], "alpha")
            self.assertEqual(out["extra"], "keep")


class SchemaVersion(unittest.TestCase):

    def test_save_writes_schema_version_field(self):
        with tempfile.TemporaryDirectory() as td:
            prefs.save_prefs(td, {"strategy": "subagent"})
            out = prefs.load_prefs(td)
            self.assertIn("schema_version", out)


if __name__ == "__main__":
    unittest.main()
