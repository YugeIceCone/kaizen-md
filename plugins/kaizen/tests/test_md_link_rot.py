"""md-link-rot (idea #5+#6): markdown links that don't resolve."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ / "scripts/quality"))

import md_link_rot  # noqa: E402

class TestMdLinkRot(unittest.TestCase):
    def test_relative_link_rot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.md").write_text("See [there](./b.md) and [oops](./missing.md).\n")
            (root / "b.md").write_text("ok\n")
            rep = md_link_rot.scan(root=root)
            broken = {(g["from"], g["target"]) for g in rep["broken"]}
            self.assertIn(("a.md", "./missing.md"), broken)
            self.assertNotIn(("a.md", "./b.md"), broken)

    def test_absolute_url_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.md").write_text("[ext](https://example.com)\n")
            rep = md_link_rot.scan(root=root)
            self.assertEqual(rep["broken"], [])

if __name__ == "__main__":
    unittest.main()
