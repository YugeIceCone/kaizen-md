"""Tests for the 2026-05-18 CLI-rename pass that aligned CLI verb names
with their slash-command counterparts:

  kaizen self-audit-agent  →  kaizen agent-self-audit   (slash: /kaizen:agent-self-audit)
  kaizen karpathy          →  kaizen karpathy-check     (slash: /kaizen:karpathy-check)

Initial pass kept the old verbs as deprecation aliases; user retired
them later that day to keep the CLI surface tight. self_audit_agent.py
now carries a `# consolidated-cli-parent: agent-self-audit` header so
the iron-law `bin-wrapper-per-cli` is satisfied without the alias.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = PLUGIN_ROOT / "bin"


def _run(bin_name: str, *args: str) -> subprocess.CompletedProcess:
    real = BIN_DIR / bin_name
    with tempfile.TemporaryDirectory() as td:
        link = Path(td) / bin_name
        link.symlink_to(real)
        env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)}
        return subprocess.run(
            [str(link), *args],
            capture_output=True, text=True,
            env=env, timeout=10,
        )


class TestCanonicalBinsExist(unittest.TestCase):
    """New canonical bins match the slash-command names."""

    def test_kaizen_agent_self_audit_exists(self):
        path = BIN_DIR / "kaizen-agent-self-audit"
        self.assertTrue(path.is_file(), "missing canonical bin/kaizen-agent-self-audit")
        self.assertTrue(os.access(path, os.X_OK), "not executable")

    def test_kaizen_karpathy_check_exists(self):
        path = BIN_DIR / "kaizen-karpathy-check"
        self.assertTrue(path.is_file(), "missing canonical bin/kaizen-karpathy-check")
        self.assertTrue(os.access(path, os.X_OK), "not executable")


class TestCanonicalBinsWork(unittest.TestCase):
    """Both canonical bins must invoke their backing logic end-to-end."""

    def test_agent_self_audit_help_works(self):
        r = _run("kaizen-agent-self-audit", "--help")
        self.assertEqual(0, r.returncode, r.stderr)
        # The underlying self_audit_agent.py argparse should mention 'dispatch-plan'.
        self.assertIn("dispatch-plan", r.stdout + r.stderr)

    def test_karpathy_check_help_works(self):
        r = _run("kaizen-karpathy-check", "help")
        self.assertEqual(0, r.returncode, r.stderr)
        # The wrapper's help text should list the 4 sub-scanners.
        for kw in ("complexity", "surgeon", "assumption", "goal"):
            self.assertIn(kw, r.stdout, f"karpathy-check help missing '{kw}' subcmd")


class TestRetiredAliasesAreGone(unittest.TestCase):
    """Old verbs were retired in the follow-up commit; assert they're
    really gone so future drift doesn't silently re-introduce them."""

    def test_kaizen_self_audit_agent_bin_does_not_exist(self):
        self.assertFalse(
            (BIN_DIR / "kaizen-self-audit-agent").exists(),
            "kaizen-self-audit-agent was retired — use kaizen-agent-self-audit",
        )

    def test_kaizen_karpathy_bin_does_not_exist(self):
        self.assertFalse(
            (BIN_DIR / "kaizen-karpathy").exists(),
            "kaizen-karpathy was retired — use kaizen-karpathy-check",
        )

    def test_self_audit_agent_script_carries_consolidated_parent_header(self):
        """Without this header, `bin-wrapper-per-cli` fails — the script
        no longer maps 1:1 to a bin of the same name (only the parent bin
        kaizen-agent-self-audit exists)."""
        script = (
            PLUGIN_ROOT / "scripts" / "iron-laws" / "self_audit_agent.py"
        )
        content = script.read_text(encoding="utf-8")
        self.assertIn(
            "# consolidated-cli-parent: agent-self-audit",
            content,
            "self_audit_agent.py must declare its parent bin to satisfy iron-law",
        )


if __name__ == "__main__":
    unittest.main()
