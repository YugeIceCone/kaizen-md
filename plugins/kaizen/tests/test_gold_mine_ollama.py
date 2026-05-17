"""Phase 3 — tests for the minimal Ollama caller (`_ollama.py`).

Mocks urllib.request.urlopen — never makes a real network call. Tests:
  - KAIZEN_GOLD_MINE_ENABLE knob (off → no call)
  - graceful failure (URLError → None + stderr)
  - schema-shape validation (response missing fields → None)
  - happy path returns the parsed dict
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills" / "workflow" / "scripts"))

import _ollama  # noqa: E402


_SCHEMA = {
    "type": "object",
    "properties": {
        "gold_worthy": {"type": "boolean"},
        "confidence":  {"type": "number", "minimum": 0, "maximum": 1},
        "pattern":     {"type": "string"},
        "tag":         {"type": "string"},
        "reason":      {"type": "string"},
    },
    "required": ["gold_worthy", "confidence", "pattern", "tag", "reason"],
}


def _ollama_response(body: dict) -> MagicMock:
    """Build a fake urlopen response whose .read() returns Ollama's
    chat-API shape: {message: {content: "<json-string>"}}."""
    wire = {"message": {"content": json.dumps(body)}}
    resp = MagicMock()
    resp.read.return_value = json.dumps(wire).encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = lambda *a: None
    return resp


class OllamaBase(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.get("KAIZEN_GOLD_MINE_ENABLE")
        os.environ["KAIZEN_GOLD_MINE_ENABLE"] = "1"

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("KAIZEN_GOLD_MINE_ENABLE", None)
        else:
            os.environ["KAIZEN_GOLD_MINE_ENABLE"] = self._orig


class TestEnableKnob(OllamaBase):
    def test_disabled_returns_none(self):
        os.environ.pop("KAIZEN_GOLD_MINE_ENABLE", None)
        with patch("urllib.request.urlopen") as mock:
            out = _ollama.score_hint("hint", schema=_SCHEMA)
            self.assertIsNone(out)
            mock.assert_not_called()

    def test_enable_unset_returns_none(self):
        os.environ["KAIZEN_GOLD_MINE_ENABLE"] = "0"
        with patch("urllib.request.urlopen") as mock:
            out = _ollama.score_hint("hint", schema=_SCHEMA)
            self.assertIsNone(out)
            mock.assert_not_called()


class TestGracefulFailure(OllamaBase):
    def test_connection_refused_returns_none(self):
        from urllib.error import URLError
        with patch("urllib.request.urlopen",
                    side_effect=URLError("connection refused")), \
              patch("sys.stderr", new=io.StringIO()) as err:
            out = _ollama.score_hint("hint", schema=_SCHEMA)
            self.assertIsNone(out)
            self.assertIn("gold-mine", err.getvalue().lower())

    def test_malformed_json_returns_none(self):
        resp = MagicMock()
        resp.read.return_value = b"not-json"
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda *a: None
        with patch("urllib.request.urlopen", return_value=resp):
            self.assertIsNone(_ollama.score_hint("h", schema=_SCHEMA))

    def test_missing_required_fields_returns_none(self):
        # Ollama returned valid JSON but missing the required keys.
        bad = {"gold_worthy": True, "confidence": 0.9}  # missing pattern/tag/reason
        with patch("urllib.request.urlopen",
                    return_value=_ollama_response(bad)):
            self.assertIsNone(_ollama.score_hint("h", schema=_SCHEMA))


class TestHappyPath(OllamaBase):
    def test_returns_parsed_dict(self):
        good = {
            "gold_worthy": True,
            "confidence":  0.87,
            "pattern":     "Long context warnings predict crash",
            "tag":         "context-mgmt",
            "reason":      "recurrent + actionable",
        }
        with patch("urllib.request.urlopen",
                    return_value=_ollama_response(good)):
            out = _ollama.score_hint("hint", schema=_SCHEMA)
            self.assertIsNotNone(out)
            self.assertEqual(out["confidence"], 0.87)
            self.assertEqual(out["tag"], "context-mgmt")

    def test_passes_schema_as_format(self):
        good = {
            "gold_worthy": False, "confidence": 0.2,
            "pattern": "x", "tag": "y", "reason": "z",
        }
        with patch("urllib.request.urlopen",
                    return_value=_ollama_response(good)) as mock:
            _ollama.score_hint("hint", schema=_SCHEMA)
            # Inspect the Request that was passed.
            call = mock.call_args
            req = call.args[0]
            body = json.loads(req.data.decode())
            self.assertEqual(body["format"], _SCHEMA)
            self.assertEqual(body["options"]["temperature"], 0)
            self.assertFalse(body["stream"])

    def test_default_model_is_granite(self):
        good = {
            "gold_worthy": False, "confidence": 0.1,
            "pattern": "x", "tag": "y", "reason": "z",
        }
        with patch("urllib.request.urlopen",
                    return_value=_ollama_response(good)) as mock:
            _ollama.score_hint("hint", schema=_SCHEMA)
            body = json.loads(mock.call_args.args[0].data.decode())
            self.assertEqual(body["model"], "granite4.1:8b")


if __name__ == "__main__":
    unittest.main()
