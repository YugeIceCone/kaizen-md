"""hook-trace-coverage (idea #30): every hook script must source/fire _trace.sh."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/quality"))

import hook_trace_coverage  # noqa: E402


class TestHookTraceCoverage(unittest.TestCase):
    def test_synthetic(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "hooks"
            d.mkdir()
            (d / "ok.sh").write_text("#!/bin/bash\nsource _trace.sh\n")
            (d / "bad.sh").write_text("#!/bin/bash\necho hello\n")
            rep = hook_trace_coverage.scan(hooks_dir=d)
            names = {g["script"] for g in rep["gaps"]}
            self.assertIn("bad.sh", names)
            self.assertNotIn("ok.sh", names)

    def test_real_dir(self):
        rep = hook_trace_coverage.scan(hooks_dir=_KZ / "hooks/claude")
        self.assertIn("hooks_total", rep)


if __name__ == "__main__":
    unittest.main()
