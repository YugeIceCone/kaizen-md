"""Tests for kaizen-help-gen — auto-regenerate commands/help.md."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/util/help_gen.py"


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=10,
        env=os.environ.copy(),
    )


class TestScriptHealth(unittest.TestCase):
    def test_script_parses(self):
        with open(_SCRIPT) as f:
            compile(f.read(), str(_SCRIPT), "exec")


class TestRender(unittest.TestCase):
    def test_print_emits_body_with_clusters(self):
        r = _run("print")
        self.assertEqual(r.returncode, 0, r.stderr)
        for cluster in ("audit/quality", "observability", "brain/memory",
                         "workflow", "plugin-meta", "discovery/search",
                         "dev-aids"):
            self.assertIn(cluster, r.stdout)

    def test_print_includes_known_commands(self):
        r = _run("print")
        for cmd in ("audit", "audit:axis", "brain", "backlog", "help"):
            self.assertIn(f"`{cmd}`", r.stdout)

    def test_render_then_check_passes(self):
        """Render writes a stable output; check confirms freshness."""
        r1 = _run("render")
        self.assertEqual(r1.returncode, 0, r1.stderr)
        r2 = _run("check")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("fresh", r2.stdout)


class TestShortDesc(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        if "help_gen" in sys.modules:
            del sys.modules["help_gen"]
        import help_gen
        self.hg = help_gen

    def test_strips_triggers_clause(self):
        s = self.hg._short_desc(
            'Do X. Triggers on "phrase one", "phrase two".'
        )
        self.assertNotIn("Triggers", s)
        self.assertIn("Do X", s)

    def test_truncates_long(self):
        s = self.hg._short_desc("x" * 200)
        self.assertLessEqual(len(s), 85)

    def test_compresses_whitespace(self):
        s = self.hg._short_desc("multiple   spaces\n\nand newlines")
        self.assertNotIn("  ", s)
        self.assertNotIn("\n", s)


class TestClusterAssignment(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        if "help_gen" in sys.modules:
            del sys.modules["help_gen"]
        import help_gen
        self.hg = help_gen

    def test_known_command_lands_in_cluster(self):
        cmds = [{"name": "audit", "stem": "audit", "desc": "x"}]
        buckets = self.hg.cluster_assignments(cmds)
        self.assertEqual(len(buckets["audit/quality"]), 1)
        self.assertEqual(buckets["uncategorized"], [])

    def test_unknown_command_lands_in_uncategorized(self):
        cmds = [{"name": "totally-novel", "stem": "totally-novel", "desc": "x"}]
        buckets = self.hg.cluster_assignments(cmds)
        self.assertEqual(buckets["uncategorized"][0]["stem"], "totally-novel")


class TestClusterSubcommand(unittest.TestCase):
    """Backing for /kaizen:help cluster-picker QA — emit one cluster only."""

    def test_cluster_emits_only_that_cluster(self):
        r = _run("cluster", "audit/quality")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("audit/quality", r.stdout)
        # Some other clusters should NOT appear as headings in the output
        self.assertNotIn("## observability", r.stdout)
        self.assertNotIn("## brain/memory", r.stdout)
        self.assertNotIn("## workflow", r.stdout)

    def test_cluster_includes_member_commands(self):
        r = _run("cluster", "audit/quality")
        self.assertEqual(r.returncode, 0, r.stderr)
        # audit/quality cluster includes audit + audit:axis (the only
        # surviving roots post-consolidate-2 D3 fold of karpathy /
        # review / vibe-check / precommit / ci-gate / gatekeeper).
        self.assertIn("`audit`", r.stdout)
        self.assertIn("`audit:axis`", r.stdout)

    def test_cluster_unknown_exits_nonzero(self):
        r = _run("cluster", "nonexistent-cluster")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("nonexistent-cluster", r.stderr + r.stdout)

    def test_cluster_help_lists_known_clusters(self):
        """Calling cluster without arg or with --list shows the catalog."""
        r = _run("cluster", "--list")
        self.assertEqual(r.returncode, 0, r.stderr)
        for cluster in ("audit/quality", "observability", "brain/memory",
                         "workflow", "plugin-meta", "discovery/search",
                         "dev-aids"):
            self.assertIn(cluster, r.stdout)


if __name__ == "__main__":
    unittest.main()
