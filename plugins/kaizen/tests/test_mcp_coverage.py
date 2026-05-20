"""mcp-coverage (idea #38): every *_mcp.py is mounted into the FastMCP
gateway via SUBSERVERS."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ / "scripts/quality"))

import mcp_coverage  # noqa: E402

class TestMcpCoverage(unittest.TestCase):
    def test_real_gateway_picks_up_subservers(self):
        rep = mcp_coverage.scan(
            scripts_dir=_KZ / "scripts/mcp",
            gateway_py=_KZ / "scripts/mcp/gateway.py",
        )
        for k in ("mcp_modules_on_disk", "mounted_subservers",
                   "orphans", "gaps_total"):
            self.assertIn(k, rep)
        self.assertGreater(rep["mounted_subservers"], 0)

    def test_synthetic_orphan(self):
        with tempfile.TemporaryDirectory() as td:
            sd = Path(td) / "scripts"
            sd.mkdir()
            (sd / "foo_mcp.py").write_text("# mounted\n")
            (sd / "bar_mcp.py").write_text("# orphan\n")
            gw = Path(td) / "gateway.py"
            gw.write_text('SUBSERVERS = [("foo", "foo_mcp")]\n')
            rep = mcp_coverage.scan(scripts_dir=sd, gateway_py=gw)
            names = {o["module"] for o in rep["orphans"]}
            self.assertIn("bar_mcp", names)
            self.assertNotIn("foo_mcp", names)

if __name__ == "__main__":
    unittest.main()
