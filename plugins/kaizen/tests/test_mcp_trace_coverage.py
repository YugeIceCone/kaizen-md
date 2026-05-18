"""mcp-trace-coverage (idea #31): every *_mcp.py should emit kaizen-trace events."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))

import mcp_trace_coverage  # noqa: E402


class TestMcpTraceCoverage(unittest.TestCase):
    def test_synthetic(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "scripts"
            d.mkdir()
            (d / "good_mcp.py").write_text(
                "from _trace import emit\nemit('foo')\n")
            (d / "bad_mcp.py").write_text("# no tracing\n")
            rep = mcp_trace_coverage.scan(scripts_dir=d)
            names = {g["module"] for g in rep["gaps"]}
            self.assertIn("bad_mcp.py", names)
            self.assertNotIn("good_mcp.py", names)

    def test_real_dir(self):
        rep = mcp_trace_coverage.scan(scripts_dir=_KZ / "skills/workflow/scripts")
        self.assertIn("mcp_total", rep)


if __name__ == "__main__":
    unittest.main()
