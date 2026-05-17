"""TDD — detect_stack_mcp.py exposes stack-detection as MCP tools."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "skills/workflow/scripts/detect_stack_mcp.py"


def _load():
    spec = importlib.util.spec_from_file_location("ds_mcp_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ds_mcp_test"] = mod
    scripts_dir = str(_SCRIPT.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec.loader.exec_module(mod)
    return mod


class TestDetectStackMcp(unittest.TestCase):
    def setUp(self):
        self.mod = _load()

    def test_module_exports_mcp_instance(self):
        self.assertTrue(hasattr(self.mod, "mcp"))
        self.assertEqual(self.mod.mcp.name, "detect_stack")

    def test_tools_registered(self):
        tools = asyncio.run(self.mod.mcp._list_tools())
        names = {t.name for t in tools}
        for expected in ("detect_stack_show", "detect_stack_path"):
            self.assertIn(expected, names,
                           f"missing {expected}; got {sorted(names)}")

    def test_path_returns_resolved_artifact_path(self):
        result = self.mod.detect_stack_path()
        self.assertIsInstance(result, dict)
        self.assertIn("json_path", result)
        self.assertIn("md_path", result)

    def test_show_returns_dict_or_none(self):
        """show reads existing artifact if present; returns None if absent.
        Either way must not crash."""
        result = self.mod.detect_stack_show()
        self.assertTrue(result is None or isinstance(result, dict))


if __name__ == "__main__":
    unittest.main()
