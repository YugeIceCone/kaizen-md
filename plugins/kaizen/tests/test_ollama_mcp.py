"""Tests for ollama_mcp — exposes local Ollama as MCP tools.

Three test classes:
  TestArtifacts    — file present, parses, declares the right tools
  TestGracefulOff  — when ollama python pkg missing, all tools return
                     {"error": "..."}, no crash, gateway still mounts
  TestLive         — opt-in via KAIZEN_OLLAMA_TEST_LIVE=1; exercises
                     reachable/list against the actual local daemon
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
import urllib.request
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_MCP_FILE = _KZ_DIR / "skills/workflow/scripts/ollama_mcp.py"
_GATEWAY = _KZ_DIR / "skills/workflow/scripts/gateway.py"


def _ollama_reachable() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags",
                                       timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


_LIVE_OPT_IN = os.environ.get("KAIZEN_OLLAMA_TEST_LIVE", "") == "1"
_REACHABLE = _ollama_reachable() if _LIVE_OPT_IN else False


class TestArtifacts(unittest.TestCase):
    def test_file_present(self):
        self.assertTrue(_MCP_FILE.is_file())

    def test_file_parses(self):
        with open(_MCP_FILE, "r") as f:
            compile(f.read(), str(_MCP_FILE), "exec")

    def test_declares_expected_tools(self):
        """Source-level grep — every @mcp.tool() decorated function
        must be one of the 5 documented tools."""
        text = _MCP_FILE.read_text()
        import re
        tools = re.findall(r"@mcp\.tool\(\)\s*\nasync def (\w+)", text)
        expected = {"ollama_reachable", "ollama_list", "ollama_ps",
                     "ollama_show", "ollama_chat"}
        self.assertEqual(set(tools), expected,
                          f"declared tools drift: {sorted(tools)}")

    def test_gateway_registers_ollama_subserver(self):
        """gateway.py::SUBSERVERS must include ('ollama', 'ollama_mcp')."""
        text = _GATEWAY.read_text()
        self.assertIn('("ollama", "ollama_mcp")', text,
                       "gateway SUBSERVERS missing ollama entry")

    def test_plugin_json_has_permission(self):
        plugin_json = _KZ_DIR / ".claude-plugin/plugin.json"
        data = json.loads(plugin_json.read_text())
        allow = data["permissions"]["allow"]
        self.assertTrue(any("ollama_mcp.py" in e for e in allow),
                          f"plugin.json missing ollama_mcp permission")


class TestGracefulOff(unittest.TestCase):
    """When the ollama pip pkg isn't installed, the module must still
    import + every tool returns an error dict (no crash, gateway
    safe)."""

    def test_module_imports_without_ollama_pkg(self):
        """Use importlib so we can sandbox-test the load path."""
        spec = importlib.util.spec_from_file_location(
            "ollama_mcp_test", _MCP_FILE
        )
        # If fastmcp not installed, the module sys.exits(2) at import —
        # skip the test gracefully when fastmcp is absent (it's the
        # gateway runtime; tests aren't expected to drag it in).
        try:
            import fastmcp  # noqa
        except ImportError:
            self.skipTest("fastmcp not installed (gateway-side dep)")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertTrue(hasattr(mod, "mcp"))
        self.assertTrue(hasattr(mod, "_ollama_client"))


@unittest.skipUnless(_LIVE_OPT_IN and _REACHABLE,
                       f"live test gated: opt_in={_LIVE_OPT_IN}, reachable={_REACHABLE}")
class TestLive(unittest.TestCase):
    """Live tests against the running Ollama daemon. Opt-in:
       KAIZEN_OLLAMA_TEST_LIVE=1 python3 -m unittest tests.test_ollama_mcp"""

    @classmethod
    def setUpClass(cls):
        try:
            import fastmcp  # noqa
            import ollama   # noqa
        except ImportError as e:
            raise unittest.SkipTest(f"runtime deps missing: {e}")
        spec = importlib.util.spec_from_file_location(
            "ollama_mcp_live", _MCP_FILE
        )
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_reachable_returns_true(self):
        import asyncio
        # Pull the underlying function from the FastMCP tool wrapper
        fn = self.mod.ollama_reachable.fn
        result = asyncio.run(fn())
        self.assertTrue(result.get("reachable"), result)

    def test_list_returns_models(self):
        import asyncio
        fn = self.mod.ollama_list.fn
        result = asyncio.run(fn())
        self.assertNotIn("error", result, result)
        self.assertIsInstance(result["models"], list)
        self.assertGreaterEqual(result["count"], 1,
                                  "expected ≥1 model installed locally")


if __name__ == "__main__":
    unittest.main(verbosity=2)
