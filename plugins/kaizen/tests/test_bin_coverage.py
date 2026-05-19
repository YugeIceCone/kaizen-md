"""bin-coverage (idea #36): every argparse-main script has a bin/ symlink."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/quality"))

import bin_coverage  # noqa: E402


class TestBinCoverage(unittest.TestCase):
    def test_synthetic_orphan_script(self):
        with tempfile.TemporaryDirectory() as td:
            scripts = Path(td) / "scripts"
            scripts.mkdir()
            (scripts / "wired.py").write_text(
                "import argparse\nargparse.ArgumentParser()\nif __name__=='__main__': pass\n")
            (scripts / "orphan.py").write_text(
                "import argparse\nargparse.ArgumentParser()\nif __name__=='__main__': pass\n")
            bin_d = Path(td) / "bin"
            bin_d.mkdir()
            (bin_d / "kaizen-wired").symlink_to(scripts / "wired.py")
            rep = bin_coverage.scan(scripts_dir=scripts, bin_dir=bin_d)
            names = {g["script"] for g in rep["gaps"]}
            self.assertIn("orphan.py", names)
            self.assertNotIn("wired.py", names)

    def test_known_scripts_have_bin(self):
        rep = bin_coverage.scan(
            scripts_dir=_KZ / "skills/workflow/scripts",
            bin_dir=_KZ / "bin",
        )
        names = {g["script"] for g in rep["gaps"]}
        # brainstorm shipped with its bin in P4
        self.assertNotIn("brainstorm.py", names)


if __name__ == "__main__":
    unittest.main()
