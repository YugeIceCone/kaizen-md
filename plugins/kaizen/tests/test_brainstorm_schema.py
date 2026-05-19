"""T5: every emitted row validates against idea.schema.json."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ / "scripts/util/brainstorm.py"
_RUBRIC = _KZ / "skills/brainstorming/domain/brainstorm-rubric.yaml"
_SCHEMA = _KZ / "skills/brainstorming/domain/schemas/idea.schema.json"

try:
    from jsonschema import validate as _validate
    from jsonschema import ValidationError as _ValidationError
    _HAS = True
except ImportError:
    _HAS = False


_GOOD_ROWS = [
    {"id": 1, "theme": "x", "idea": "When user hits enter, then submit the prompt now",
     "confidence": 0.9, "effort_estimate": "S"},
]


@unittest.skipUnless(_HAS, "jsonschema not installed")
class TestBrainstormSchema(unittest.TestCase):
    def test_schema_file_exists(self):
        self.assertTrue(_SCHEMA.is_file(), f"missing schema: {_SCHEMA}")

    def test_emitted_rows_validate(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text("\n".join(json.dumps(r) for r in _GOOD_ROWS) + "\n")
            r = subprocess.run(
                [sys.executable, str(_SCRIPT), "score",
                 "--input", str(inp), "--rubric", str(_RUBRIC), "--json"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            with _SCHEMA.open("r", encoding="utf-8") as f:
                schema = json.load(f)
            for row in json.loads(r.stdout)["data"]["rows"]:
                _validate(row, schema)  # raises on failure

    def test_required_field_missing_rejected(self):
        with _SCHEMA.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        # missing `confidence` (required)
        bad = {"id": 1, "theme": "x", "idea": "no confidence",
               "auto_bucket": "KEEP", "classification_confidence": 1.0,
               "rationale": "x", "rubric_version": "1"}
        with self.assertRaises(_ValidationError):
            _validate(bad, schema)

    def test_invalid_bucket_rejected(self):
        with _SCHEMA.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        bad = {"id": 1, "theme": "x", "idea": "bad bucket",
               "confidence": 0.5, "auto_bucket": "INVALID",
               "classification_confidence": 1.0, "rationale": "x",
               "rubric_version": "1"}
        with self.assertRaises(_ValidationError):
            _validate(bad, schema)


if __name__ == "__main__":
    unittest.main()
