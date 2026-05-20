"""Phase 5.B: pre-flight audit for parallel-branches plan.yaml.

Structural validation only. Runtime concerns (worktree orchestration,
merge handlers) live in clever-lama-mcp per the kit scope split.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
class TestAudit(unittest.TestCase):

    def _skip_if_no_yaml(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")

    def test_missing_plan_emits_error(self):
        import parallel_dispatch_audit as pda
        findings = pda.audit(Path("/does/not/exist/plan.yaml"))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["rule_id"], "plan-missing")
        self.assertEqual(findings[0]["severity"], "error")

    def test_valid_plan_returns_no_findings(self):
        self._skip_if_no_yaml()
        import parallel_dispatch_audit as pda
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan.yaml"
            plan.write_text(
                "chunks:\n"
                "  - id: chunk-1\n"
                "    perms: []\n"
                "  - id: chunk-2\n"
                "    perms: []\n"
            )
            findings = pda.audit(plan)
        self.assertEqual(findings, [])

    def test_duplicate_chunk_id_emits_error(self):
        self._skip_if_no_yaml()
        import parallel_dispatch_audit as pda
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan.yaml"
            plan.write_text(
                "chunks:\n"
                "  - id: same-id\n"
                "  - id: same-id\n"
            )
            findings = pda.audit(plan)
        kinds = [f["rule_id"] for f in findings]
        self.assertIn("chunk-id-duplicate", kinds)

    def test_perm_collision_emits_error(self):
        self._skip_if_no_yaml()
        import parallel_dispatch_audit as pda
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan.yaml"
            plan.write_text(
                "chunks:\n"
                "  - id: chunk-a\n"
                "    perms:\n"
                "      - {mode: exclusive, path: src/foo.py}\n"
                "  - id: chunk-b\n"
                "    perms:\n"
                "      - {mode: exclusive, path: src/foo.py}\n"
            )
            findings = pda.audit(plan)
        kinds = [f["rule_id"] for f in findings]
        self.assertIn("perm-collision", kinds)
        msgs = " ".join(f["message"] for f in findings)
        self.assertIn("src/foo.py", msgs)

    def test_missing_chunks_key_emits_error(self):
        self._skip_if_no_yaml()
        import parallel_dispatch_audit as pda
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan.yaml"
            plan.write_text("description: only metadata\n")
            findings = pda.audit(plan)
        kinds = [f["rule_id"] for f in findings]
        self.assertIn("missing-required-key", kinds)

    def test_chunks_glob_resolves(self):
        """plan.chunks as `./chunks/*.yaml` glob loads each file."""
        self._skip_if_no_yaml()
        import parallel_dispatch_audit as pda
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "chunks").mkdir()
            (Path(td) / "chunks" / "a.yaml").write_text("id: chunk-a\nperms: []\n")
            (Path(td) / "chunks" / "b.yaml").write_text("id: chunk-b\nperms: []\n")
            plan = Path(td) / "plan.yaml"
            plan.write_text("chunks: ./chunks/*.yaml\n")
            findings = pda.audit(plan)
        # No errors for a clean glob with unique ids
        errs = [f for f in findings if f["severity"] == "error"]
        self.assertEqual(errs, [])

class TestMainCLI(unittest.TestCase):

    def _skip_if_no_yaml(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")

    def test_clean_plan_returns_rc0(self):
        self._skip_if_no_yaml()
        import parallel_dispatch_audit as pda
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan.yaml"
            plan.write_text("chunks:\n  - id: only\n    perms: []\n")
            self.assertEqual(pda.main([str(plan)]), 0)

    def test_error_plan_returns_rc1(self):
        self._skip_if_no_yaml()
        import parallel_dispatch_audit as pda
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "plan.yaml"
            plan.write_text("chunks:\n  - id: dup\n  - id: dup\n")
            self.assertEqual(pda.main([str(plan)]), 1)

if __name__ == "__main__":
    unittest.main()
