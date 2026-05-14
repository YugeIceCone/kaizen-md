"""Smoke tests for brain_mcp.py — verify tool wrappers are async,
importable, and call through to the underlying CLI helpers.

The mcp package may not be installed in every CI env; those tests
skip when the import fails. The wrapper-shape tests run regardless.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))


def _mcp_available():
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_mcp_available(), "mcp package not installed")
class TestMcpToolsRegistered(unittest.TestCase):
    """Verify the @mcp.tool() decorators registered every brain
    operation. The FastMCP server exposes tool names; check the names
    cover the full surface."""

    def test_imports_cleanly(self):
        # Just importing brain_mcp must not crash
        import brain_mcp  # noqa: F401

    def test_tool_handlers_are_async(self):
        import brain_mcp
        # Every tool function in the module should be a coroutine.
        for name in (
            "brain_capture", "brain_detect", "brain_status", "brain_path",
            "brain_search", "brain_index_build", "brain_index_stats",
            "brain_get", "brain_promote_preview", "brain_promote_apply",
            "brain_audit", "brain_evolve",
        ):
            fn = getattr(brain_mcp, name, None)
            self.assertIsNotNone(fn, f"missing tool: {name}")
            self.assertTrue(asyncio.iscoroutinefunction(fn),
                            f"{name} must be async")


@unittest.skipUnless(_mcp_available(), "mcp package not installed")
class TestMcpToolBehaviour(unittest.TestCase):
    """Sandbox each tool against a tmp brain root + db; verify the
    happy-path return shape."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name) / "brain"
        self.brain.mkdir()
        self._orig = {}
        for k, v in (
            ("KAIZEN_BRAIN_PATH", str(self.brain)),
            ("KAIZEN_BRAIN_DB", str(Path(self._tmp.name) / "brain.db")),
            ("KAIZEN_BRAIN_INDEX_SKIP_EMBED", "1"),
        ):
            self._orig[k] = os.environ.get(k)
            os.environ[k] = v

    def tearDown(self):
        self._tmp.cleanup()
        for k, v in self._orig.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_brain_detect(self):
        import brain_mcp
        out = asyncio.run(brain_mcp.brain_detect("we decided to ship"))
        self.assertEqual(out["type"], "world-fact")

    def test_brain_status(self):
        import brain_mcp
        out = asyncio.run(brain_mcp.brain_status())
        self.assertIn("brain_root", out)

    def test_brain_path(self):
        import brain_mcp
        out = asyncio.run(brain_mcp.brain_path())
        self.assertIn("brain_root", out)
        self.assertIn("project_memory_root", out)
        self.assertIn("index_db", out)

    def test_brain_capture(self):
        import brain_mcp
        out = asyncio.run(brain_mcp.brain_capture(
            "we decided to use sqlite", tier_hint="brain",
        ))
        self.assertEqual(out["type"], "world-fact")
        self.assertEqual(out["tier"], "brain")

    def test_brain_index_build_then_stats(self):
        import brain_mcp
        # Capture something first so the index has content
        asyncio.run(brain_mcp.brain_capture(
            "we decided to use sqlite", tier_hint="brain",
        ))
        rep = asyncio.run(brain_mcp.brain_index_build())
        self.assertIn("discovered", rep)
        stats = asyncio.run(brain_mcp.brain_index_stats())
        self.assertIn("total", stats)


# Even when mcp isn't installed, we want at least to verify the
# script file itself parses (no syntax errors).
class TestModuleParses(unittest.TestCase):
    def test_brain_mcp_script_parses(self):
        path = _KZ_DIR / "skills/workflow/scripts/brain_mcp.py"
        # Compile via stdlib so we don't depend on the mcp package
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        compile(src, str(path), "exec")  # raises SyntaxError on failure


if __name__ == "__main__":
    unittest.main()
