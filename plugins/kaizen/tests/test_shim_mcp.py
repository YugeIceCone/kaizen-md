"""Tests for shim_mcp.py — MCP server wrapping the kaizen-shim CLI.

Verifies the module imports, exposes the expected tools, the wrappers
delegate to shim.py correctly, and the user-gating (Iron Law 4) is
preserved when going through the MCP surface.

Run:
    python3 -m unittest tests.test_shim_mcp -v
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "workflow" / "scripts"))
sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "mcp"))


def _init_git_repo(path: Path) -> None:
    """Initialize a minimal git repo so shim's git operations don't error."""
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=path, check=True
    )


class _CwdMixin:
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpcm = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpcm.name)
        _init_git_repo(self.tmp)
        os.chdir(self.tmp)
        # Clear cached modules so cwd-relative imports resolve fresh
        for mod in ("shim", "shim_mcp"):
            if mod in sys.modules:
                del sys.modules[mod]

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpcm.cleanup()


class TestShimMcpModule(unittest.TestCase):
    """The module imports cleanly and exposes the expected tools."""

    def test_module_loads(self):
        if "shim_mcp" in sys.modules:
            del sys.modules["shim_mcp"]
        import shim_mcp  # noqa: E402
        for tool in ("shim_init", "shim_carve", "shim_list", "shim_sweep"):
            self.assertTrue(
                hasattr(shim_mcp, tool),
                f"shim_mcp missing tool: {tool}",
            )

    def test_mcp_json_registers_shim(self):
        mcp_path = PLUGIN_ROOT / ".mcp.json"
        data = json.loads(mcp_path.read_text())
        # All domain servers are composed through the kaizen gateway
        self.assertIn("kaizen", data["mcpServers"])
        cmd = data["mcpServers"]["kaizen"]
        self.assertEqual(cmd["command"], "uv")
        joined = " ".join(cmd["args"])
        self.assertIn("gateway.py", joined)
        import gateway
        module_names = [m for _, m in gateway.SUBSERVERS]
        self.assertIn("shim_mcp", module_names)


class TestShimMcpDelegates(_CwdMixin, unittest.TestCase):
    """The wrappers call shim.py with the right arguments."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_shim_init_creates_manifest(self):
        import shim_mcp
        result = self._run(shim_mcp.shim_init("test-refactor"))
        self.assertNotIn("error", result)
        self.assertTrue(result["ok"])
        manifest = Path(result["manifest_path"])
        self.assertTrue(manifest.is_file())
        self.assertIn("test-refactor", manifest.read_text())

    def test_shim_init_is_idempotent(self):
        import shim_mcp
        r1 = self._run(shim_mcp.shim_init("twice"))
        r2 = self._run(shim_mcp.shim_init("twice"))
        self.assertEqual(r1["manifest_path"], r2["manifest_path"])

    def test_shim_carve_with_python_file(self):
        import shim_mcp
        # Set up a python file at the old path
        old = self.tmp / "src" / "old.py"
        old.parent.mkdir()
        old.write_text("# original content\ndef hello(): return 'hi'\n")
        new = self.tmp / "src" / "renamed.py"
        # Init + carve
        self._run(shim_mcp.shim_init("py-rename"))
        result = self._run(shim_mcp.shim_carve(
            "src/old.py",
            "src/renamed.py",
            "py-rename",
            reexport="src.renamed",
        ))
        self.assertNotIn("error", result, f"carve failed: {result}")
        # New file has original content
        self.assertTrue(new.is_file())
        self.assertIn("def hello", new.read_text())
        # Old file is a shim
        self.assertTrue(old.is_file())
        self.assertIn("from src.renamed import *", old.read_text())
        self.assertIn("kaizen-shim", old.read_text())

    def test_shim_carve_rejects_python_without_reexport(self):
        import shim_mcp
        old = self.tmp / "x.py"
        old.write_text("# x\n")
        self._run(shim_mcp.shim_init("bad"))
        result = self._run(shim_mcp.shim_carve("x.py", "y.py", "bad"))
        self.assertIn("error", result)
        self.assertIn("reexport", result["error"].lower())

    def test_shim_list_returns_manifest_entries(self):
        import shim_mcp
        old = self.tmp / "old.ts"
        old.write_text("export const x = 1;\n")
        self._run(shim_mcp.shim_init("ts-rename"))
        self._run(shim_mcp.shim_carve("old.ts", "new.ts", "ts-rename"))
        entries = self._run(shim_mcp.shim_list("ts-rename"))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["path"], "old.ts")
        self.assertIn("date", entries[0])

    def test_shim_list_empty_for_unknown_slug(self):
        import shim_mcp
        entries = self._run(shim_mcp.shim_list("never-existed"))
        self.assertEqual(entries, [])


class TestShimSweepGate(_CwdMixin, unittest.TestCase):
    """Iron Law 4: sweep refuses without explicit user authorization."""

    def _run(self, coro):
        return asyncio.run(coro)

    def _prepare_manifest_with_entries(self) -> "object":
        """Set up a slug with one carved entry. Returns the shim_mcp module."""
        import shim_mcp
        # Stash KAIZEN_ALLOW_DELETE if set globally
        self._orig_env = os.environ.get("KAIZEN_ALLOW_DELETE")
        if "KAIZEN_ALLOW_DELETE" in os.environ:
            del os.environ["KAIZEN_ALLOW_DELETE"]
        # Initial file
        old = self.tmp / "alpha.ts"
        old.write_text("export const a = 1;\n")
        subprocess.run(
            ["git", "add", "."], cwd=self.tmp, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial", "-q"], cwd=self.tmp, check=True
        )
        self._run(shim_mcp.shim_init("sweep-test"))
        self._run(shim_mcp.shim_carve("alpha.ts", "beta.ts", "sweep-test"))
        return shim_mcp

    def tearDown(self):
        # Restore env
        orig = getattr(self, "_orig_env", None)
        if orig is None:
            os.environ.pop("KAIZEN_ALLOW_DELETE", None)
        else:
            os.environ["KAIZEN_ALLOW_DELETE"] = orig
        super().tearDown()

    def test_sweep_refuses_without_allow_delete(self):
        shim_mcp = self._prepare_manifest_with_entries()
        result = self._run(shim_mcp.shim_sweep("sweep-test"))
        self.assertIn("error", result)
        self.assertTrue(result.get("permission_denied"))

    def test_sweep_dry_run_lists_targets_without_deleting(self):
        shim_mcp = self._prepare_manifest_with_entries()
        result = self._run(shim_mcp.shim_sweep(
            "sweep-test", allow_delete=True, dry_run=True
        ))
        self.assertNotIn("error", result)
        self.assertTrue(result["dry_run"])
        # The shim file at alpha.ts is still on disk
        self.assertTrue((self.tmp / "alpha.ts").is_file())
        self.assertIn("alpha.ts", result["deleted"])


if __name__ == "__main__":
    unittest.main()
