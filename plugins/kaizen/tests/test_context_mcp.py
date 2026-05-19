"""TDD — context_mcp.py exposes /kaizen:context as an MCP tool.

Agents query context-window state every few turns to decide compaction
+ auto-handoff timing. Subprocess-via-Bash adds overhead; MCP gives
direct structured access.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/mcp/context_mcp.py"


def _load():
    spec = importlib.util.spec_from_file_location("context_mcp_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["context_mcp_test"] = mod
    # Add scripts dir to path so context.py sibling import works
    scripts_dir = str(_SCRIPT.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    legacy = str(_KZ_DIR / "skills/workflow/scripts")
    if legacy not in sys.path: sys.path.insert(0, legacy)
    spec.loader.exec_module(mod)
    return mod


class TestContextMcp(unittest.TestCase):
    def setUp(self):
        self.mod = _load()

    def test_module_exports_mcp_instance(self):
        self.assertTrue(hasattr(self.mod, "mcp"),
                          "module must export `mcp` for gateway mount")
        # Should be a FastMCP instance with name 'context'
        self.assertEqual(self.mod.mcp.name, "context")

    def test_status_tool_registered(self):
        """The headline tool — context_status() returns {tokens, pct, zone}."""
        tools = asyncio.run(self.mod.mcp._list_tools())
        names = {t.name for t in tools}
        self.assertIn("context_status", names,
                       f"missing context_status; got {names}")

    def test_status_returns_dict_shape(self):
        """Calling context_status() returns a parseable dict (or JSON)."""
        result = self.mod.context_status()
        # Tool can return dict or JSON-str; both fine for MCP
        if isinstance(result, str):
            import json
            result = json.loads(result)
        self.assertIsInstance(result, dict)
        # Must carry at least these keys (per /kaizen:context contract)
        for key in ("zone", "recommendation"):
            self.assertIn(key, result,
                           f"context_status missing key {key!r}; got {result}")


if __name__ == "__main__":
    unittest.main()
