"""Tests for gateway.py — the single-entry MCP gateway."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(SCRIPTS))

try:
    import fastmcp  # noqa: F401
except ImportError:
    raise unittest.SkipTest("fastmcp not installed in the test env")


class TestGatewayComposition(unittest.TestCase):
    def test_gateway_imports_and_mounts_pilots(self):
        import gateway
        names = {name for name, _ in gateway.MOUNTED}
        for pilot in ("iron_laws", "manifests", "drift"):
            self.assertIn(pilot, names, f"{pilot} should be mounted")

    def test_gateway_object_is_fastmcp(self):
        import gateway
        from fastmcp import FastMCP
        self.assertIsInstance(gateway.gw, FastMCP)

    def test_gateway_has_no_mount_errors(self):
        import gateway
        self.assertEqual(gateway.MOUNT_ERRORS, [],
                         f"no sub-server should fail to mount: {gateway.MOUNT_ERRORS}")

    def test_gateway_mounts_all_phase2_servers(self):
        import gateway
        names = {name for name, _ in gateway.MOUNTED}
        phase2 = (
            "backlog", "browser", "trace", "knowledge", "onboard",
            "claude_docs", "scrape", "state", "lint", "workflow",
            "loc", "loop", "shim", "rerank", "audit", "roadmap",
        )
        for srv in phase2:
            self.assertIn(srv, names, f"{srv} should be mounted in phase 2")


if __name__ == "__main__":
    unittest.main()
