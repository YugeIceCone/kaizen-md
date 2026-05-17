"""Tests for the 2026-05-18 CLI-rename pass that aligned CLI verb names
with their slash-command counterparts:

  kaizen self-audit-agent  →  kaizen agent-self-audit   (slash: /kaizen:agent-self-audit)
  kaizen karpathy          →  kaizen karpathy-check     (slash: /kaizen:karpathy-check)

The old verbs stay as deprecation aliases (per no-deletions discipline)
that forward to the canonical bin and emit a one-line warning to stderr.
The iron-law `bin-wrapper-per-cli` requires kaizen-self-audit-agent to
exist (mapped from self_audit_agent.py); keeping it as an alias
satisfies the rule.
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


class TestDeprecationAliases(unittest.TestCase):
    """Old verbs still work but emit a deprecation note to stderr."""

    def test_self_audit_agent_alias_still_works(self):
        r = _run("kaizen-self-audit-agent", "--help")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("dispatch-plan", r.stdout + r.stderr,
                      "deprecation alias must still pass-through to the canonical bin")

    def test_self_audit_agent_emits_deprecation(self):
        r = _run("kaizen-self-audit-agent", "--help")
        self.assertIn("deprecated", r.stderr.lower(),
                      "alias must emit a deprecation note on stderr")
        self.assertIn("kaizen-agent-self-audit", r.stderr,
                      "deprecation note should name the canonical bin")

    def test_karpathy_alias_still_works(self):
        r = _run("kaizen-karpathy", "help")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("complexity", r.stdout,
                      "deprecation alias must still pass-through")

    def test_karpathy_emits_deprecation(self):
        r = _run("kaizen-karpathy", "help")
        self.assertIn("deprecated", r.stderr.lower(),
                      "alias must emit a deprecation note on stderr")
        self.assertIn("kaizen-karpathy-check", r.stderr,
                      "deprecation note should name the canonical bin")


if __name__ == "__main__":
    unittest.main()
