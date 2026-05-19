"""TDD — config_mcp.py exposes config lookup as MCP tools."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/mcp/config_mcp.py"


def _load():
    spec = importlib.util.spec_from_file_location("config_mcp_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["config_mcp_test"] = mod
    scripts_dir = str(_SCRIPT.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    legacy = str(_KZ_DIR / "skills/workflow/scripts")
    if legacy not in sys.path: sys.path.insert(0, legacy)
    spec.loader.exec_module(mod)
    return mod


class TestConfigMcp(unittest.TestCase):
    def setUp(self):
        self.mod = _load()

    def test_module_exports_mcp_instance(self):
        self.assertTrue(hasattr(self.mod, "mcp"))
        self.assertEqual(self.mod.mcp.name, "config")

    def test_tools_registered(self):
        tools = asyncio.run(self.mod.mcp._list_tools())
        names = {t.name for t in tools}
        for expected in ("config_get", "config_defaults", "config_validate"):
            self.assertIn(expected, names,
                           f"missing {expected}; got {sorted(names)}")

    def test_defaults_returns_dict(self):
        r = self.mod.config_defaults()
        self.assertIsInstance(r, dict)
        # config.py PLUGIN_DEFAULTS exposes at least these stable keys
        for k in ("EMBED_MODEL", "EMBED_DIM", "USER_DIR_NAME"):
            self.assertIn(k, r, f"defaults missing key {k!r}; got {sorted(r)}")

    def test_get_returns_dict_with_key_value(self):
        r = self.mod.config_get("compile_check_cmd", default="")
        self.assertIsInstance(r, dict)
        self.assertIn("key", r)
        self.assertIn("value", r)
        self.assertEqual(r["key"], "compile_check_cmd")

    def test_get_missing_key_returns_default(self):
        r = self.mod.config_get("nonexistent_key_xyz", default="fallback-x")
        self.assertEqual(r["value"], "fallback-x")

    def test_validate_returns_dict(self):
        r = self.mod.config_validate()
        self.assertIsInstance(r, dict)


if __name__ == "__main__":
    unittest.main()
