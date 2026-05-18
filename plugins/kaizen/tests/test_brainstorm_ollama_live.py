"""T8: Live smoke against local Ollama (granite4.1:8b).

Skipped when:
  - KAIZEN_BRAINSTORM_TEST_LIVE != "1" (opt-in)
  - Ollama not reachable at :11434
  - granite4.1:8b not present

Mirror of test_gold_mine_ollama_live.py — same opt-in shape, same
graceful-skip pattern. The "live" label means the Ollama stack is
available; the asserted contract is that the deterministic rubric
correctly classifies pre-flagged synthetic ideas when run end-to-end
through the score CLI.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ / "skills/workflow/scripts/brainstorm.py"
_RUBRIC = _KZ / "skills/brainstorming/domain/brainstorm-rubric.yaml"


def _ollama_reachable() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags",
                                      timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _granite_present() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags",
                                      timeout=2) as r:
            data = json.loads(r.read().decode("utf-8"))
            names = [m.get("name", "") for m in data.get("models", [])]
            return any(n.startswith("granite4.1:8b") for n in names)
    except Exception:
        return False


_LIVE = os.environ.get("KAIZEN_BRAINSTORM_TEST_LIVE", "") == "1"
_REACHABLE = _ollama_reachable() if _LIVE else False
_GRANITE = _granite_present() if _LIVE else False

_SKIP_MSG = (
    f"live test gated: opt_in={_LIVE}, "
    f"ollama_reachable={_REACHABLE}, granite_present={_GRANITE}"
)


@unittest.skipUnless(_LIVE and _REACHABLE and _GRANITE, _SKIP_MSG)
class TestBrainstormOllamaLive(unittest.TestCase):
    def test_yagni_flag_routes_to_yagni_bucket(self):
        rows = [
            {"id": 1, "theme": "live",
             "idea": "delete logs nightly via cron job some extra words",
             "confidence": 0.9, "yagni": True},
        ]
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "live.jsonl"
            inp.write_text(json.dumps(rows[0]) + "\n")
            r = subprocess.run(
                [sys.executable, str(_SCRIPT), "score",
                 "--input", str(inp), "--rubric", str(_RUBRIC), "--json"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            row = json.loads(r.stdout)["data"]["rows"][0]
            self.assertEqual(row["auto_bucket"], "YAGNI")

    def test_radical_flag_routes_to_radical_bucket(self):
        rows = [
            {"id": 2, "theme": "live",
             "idea": "rewrite the planet using neuromorphic chips and quantum dust",
             "confidence": 0.7, "radical": True},
        ]
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "live.jsonl"
            inp.write_text(json.dumps(rows[0]) + "\n")
            r = subprocess.run(
                [sys.executable, str(_SCRIPT), "score",
                 "--input", str(inp), "--rubric", str(_RUBRIC), "--json"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            row = json.loads(r.stdout)["data"]["rows"][0]
            self.assertEqual(row["auto_bucket"], "RADICAL")


if __name__ == "__main__":
    unittest.main()
