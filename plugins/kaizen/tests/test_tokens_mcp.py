"""Phase 5 — FastMCP server surface for kaizen-tokens.

The MCP server runs under `uv run --script` (PEP-723) because fastmcp
and tree-sitter are not in the system Python. Tests invoke the script
in a `--self-test` mode that emits JSON describing the registered
tool surface, so we avoid importing fastmcp into the test process.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "skills/workflow/scripts/tokens_mcp.py"


def _self_test() -> dict:
    """Run the MCP script with --self-test and parse the JSON line."""
    proc = subprocess.run(
        ["uv", "run", "--script", str(SCRIPT), "--self-test"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"--self-test exited {proc.returncode}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    # The script may print uv-install chatter to stderr; stdout is the JSON.
    last_line = proc.stdout.strip().splitlines()[-1]
    return json.loads(last_line)


class TestMcpServerSurface(unittest.TestCase):
    """Smoke tests on the FastMCP instance via --self-test."""

    @classmethod
    def setUpClass(cls):
        cls.report = _self_test()

    def test_mcp_instance_exists(self):
        self.assertTrue(self.report.get("ok"),
                         f"self-test reported not-ok: {self.report}")
        self.assertEqual(self.report.get("server_name"), "kaizen-tokens")

    def test_read_token_tool_registered(self):
        tools = set(self.report.get("tools", []))
        for name in ("read_token", "read_token_by_name",
                     "batch_read", "list_files"):
            self.assertIn(name, tools,
                          f"tool {name!r} missing from registry: {tools}")


if __name__ == "__main__":
    unittest.main()
