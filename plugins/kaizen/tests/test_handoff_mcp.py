"""TDD — handoff_mcp.py exposes handoff subcommands as MCP tools."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/mcp/handoff_mcp.py"


def _load():
    spec = importlib.util.spec_from_file_location("handoff_mcp_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["handoff_mcp_test"] = mod
    scripts_dir = str(_SCRIPT.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    legacy = str(_KZ_DIR / "skills/workflow/scripts")
    if legacy not in sys.path: sys.path.insert(0, legacy)
    spec.loader.exec_module(mod)
    return mod


class TestHandoffMcp(unittest.TestCase):
    def setUp(self):
        self.mod = _load()

    def test_module_exports_mcp_instance(self):
        self.assertTrue(hasattr(self.mod, "mcp"))
        self.assertEqual(self.mod.mcp.name, "handoff")

    def test_read_tools_registered(self):
        """Read-mostly tools: latest, list, path."""
        tools = asyncio.run(self.mod.mcp._list_tools())
        names = {t.name for t in tools}
        for expected in ("handoff_latest", "handoff_list", "handoff_path"):
            self.assertIn(expected, names,
                           f"missing {expected}; got {sorted(names)}")


class TestHandoffMcpReturns(unittest.TestCase):
    """Each tool returns a dict (parseable by the MCP client)."""

    def setUp(self):
        self.mod = _load()
        self.tmp = tempfile.TemporaryDirectory()
        self._orig_env = dict(os.environ)
        os.environ["KAIZEN_HANDOFF_DIR"] = str(Path(self.tmp.name) / "ho")
        os.environ["KAIZEN_HANDOFF_DB"] = str(
            Path(self.tmp.name) / "ho" / "handoff.db"
        )

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
        self.tmp.cleanup()

    def test_latest_returns_dict_with_handoff_key(self):
        """latest returns {handoff: <dict>|null}. Empty store → null."""
        r = self.mod.handoff_latest()
        self.assertIsInstance(r, dict)
        self.assertIn("handoff", r)

    def test_list_returns_dict_with_handoffs_list(self):
        r = self.mod.handoff_list()
        self.assertIsInstance(r, dict)
        self.assertIn("handoffs", r)
        self.assertIsInstance(r["handoffs"], list)

    def test_path_returns_dict(self):
        r = self.mod.handoff_path()
        self.assertIsInstance(r, dict)


if __name__ == "__main__":
    unittest.main()
