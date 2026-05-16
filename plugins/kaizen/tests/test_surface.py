"""Tests for skills/workflow/scripts/surface.py — unified MCP+hooks registry."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SURFACE = _REPO_ROOT / "plugins/kaizen/skills/workflow/scripts/surface.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestSurfaceInventory(unittest.TestCase):
    def setUp(self):
        self.s = _load("surface_test", _SURFACE)

    def test_list_hook_entries_returns_list(self):
        hooks = self.s.list_hook_entries()
        self.assertIsInstance(hooks, list)
        # Should have at least the canonical kaizen events
        events = {h.event for h in hooks}
        self.assertIn("SessionStart", events)
        self.assertIn("PreToolUse", events)
        self.assertIn("PostToolUse", events)

    def test_list_mcp_servers_includes_gatekeeper(self):
        servers = self.s.list_mcp_servers()
        names = {s.name for s in servers}
        # gatekeeper was wired in this session
        self.assertIn("gatekeeper", names)
        # And at least the canonical hot-path servers
        for must in ("iron_laws", "brain", "state", "workflow"):
            self.assertIn(must, names, f"missing canonical server: {must}")

    def test_total_tool_count_positive(self):
        servers = self.s.list_mcp_servers()
        total = sum(s.tool_count for s in servers)
        # Sanity — should be well over 100 (current is ~146)
        self.assertGreater(total, 100, f"tool count too low: {total}")

    def test_curated_core_non_empty(self):
        core = self.s._curated_core()
        self.assertGreater(len(core), 5)
        # Recent additions from C1 commit
        self.assertIn("gatekeeper_check", core)


class TestSurfaceValidator(unittest.TestCase):
    def setUp(self):
        self.s = _load("surface_val_test", _SURFACE)

    def test_validate_returns_list(self):
        findings = self.s.validate()
        self.assertIsInstance(findings, list)

    def test_orphan_hook_detected(self):
        """karpathy-gate.sh is the known orphan from F-002."""
        findings = self.s.validate()
        orphans = [f for f in findings if f.rule_id == "orphan-hook-script"]
        self.assertTrue(
            any("karpathy-gate.sh" in f.message for f in orphans),
            f"expected karpathy-gate.sh orphan; got: {[f.message for f in orphans]}",
        )

    def test_wildcard_permission_recognized(self):
        """All MCP modules should NOT be flagged as missing permission —
        the wildcard `uv run --script .../skills/workflow/scripts/*.py:*`
        covers them all."""
        findings = self.s.validate()
        missing = [f for f in findings if f.rule_id == "missing-permission"]
        self.assertEqual(
            missing, [],
            f"wildcard recognition broke; spurious missing-permission: {[f.message for f in missing]}",
        )


class TestRenderers(unittest.TestCase):
    def setUp(self):
        self.s = _load("surface_render_test", _SURFACE)

    def test_render_list_text_includes_totals(self):
        servers = self.s.list_mcp_servers()
        hooks = self.s.list_hook_entries()
        out = self.s.render_list_text(servers, hooks)
        self.assertIn("TOTAL", out)
        self.assertIn("MCP sub-servers", out)
        self.assertIn("Hooks", out)

    def test_render_validate_text_clean(self):
        out = self.s.render_validate_text([])
        self.assertIn("clean", out)


if __name__ == "__main__":
    unittest.main()
