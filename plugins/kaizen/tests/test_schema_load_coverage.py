"""schema-load-coverage (idea #16): every domain/schemas/*.json is loaded by code."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ / "scripts/quality"))

import schema_load_coverage  # noqa: E402

class TestSchemaLoadCoverage(unittest.TestCase):
    def test_synthetic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "skills/x/domain/schemas").mkdir(parents=True)
            (root / "skills/x/domain/schemas/used.schema.json").write_text("{}")
            (root / "skills/x/domain/schemas/orphan.schema.json").write_text("{}")
            (root / "scripts/util").mkdir(parents=True)
            (root / "scripts/util/loader.py").write_text(
                'open("used.schema.json")\n')
            rep = schema_load_coverage.scan(plugin_root=root)
            names = {g["schema"] for g in rep["gaps"]}
            self.assertIn("orphan.schema.json", names)
            self.assertNotIn("used.schema.json", names)

    def test_real_repo(self):
        rep = schema_load_coverage.scan(
            plugin_root=_KZ
        )
        self.assertIn("schemas_total", rep)

if __name__ == "__main__":
    unittest.main()
