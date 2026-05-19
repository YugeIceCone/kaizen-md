"""heavy-imports (idea #27): AST scan for eager imports of heavy deps."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/quality"))

import heavy_imports  # noqa: E402


class TestHeavyImports(unittest.TestCase):
    def test_eager_heavy_import_flagged(self):
        src = "import torch\nfrom transformers import AutoModel\n"
        findings = heavy_imports.scan_text(src, path="bad.py")
        modules = {f["module"] for f in findings}
        self.assertIn("torch", modules)
        self.assertIn("transformers", modules)

    def test_lazy_import_inside_function_not_flagged(self):
        src = '''
def heavy():
    import torch
    return torch.zeros(1)
'''
        findings = heavy_imports.scan_text(src, path="ok.py")
        self.assertEqual(findings, [])

    def test_real_dir_scan_shape(self):
        rep = heavy_imports.scan(scripts_dir=_KZ / "skills/workflow/scripts")
        for k in ("scripts_total", "findings"):
            self.assertIn(k, rep)


if __name__ == "__main__":
    unittest.main()
