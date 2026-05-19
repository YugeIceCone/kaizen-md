"""T4: kaizen-brainstorm score — CLI subprocess contract.

Hits the script directly (not the bin/ symlink, to keep test paths
absolute). Subprocess boundary so we exercise argparse + envelope
emission + atomic write end-to-end.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ / "scripts/util/brainstorm.py"
_RUBRIC = _KZ / "skills/brainstorming/domain/brainstorm-rubric.yaml"


def _run(*args, env_extra=None):
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=30, env=env,
    )


def _jsonl(rows: list[dict]) -> str:
    return "\n".join(json.dumps(r) for r in rows) + "\n"


_FIVE_DRAFTS = [
    {"id": 1, "theme": "core",  "idea": "When the user hits enter, then submit the prompt",
     "confidence": 0.9, "effort_estimate": "S"},
    {"id": 2, "theme": "edge",  "idea": "Idle TTL knob to auto-close stale sessions",
     "confidence": 0.6, "effort_estimate": "M"},
    {"id": 3, "theme": "moon",  "idea": "Reactive UI that rewrites itself based on user mood",
     "confidence": 0.4, "radical": True},
    {"id": 4, "theme": "trim",  "idea": "Delete cache nightly via cron",
     "confidence": 0.2, "yagni": True},
    {"id": 5, "theme": "huge",  "idea": "When traffic spikes, then shard the queue across regions",
     "confidence": 0.7, "effort_estimate": "XL"},
]


class TestBrainstormScoreCLI(unittest.TestCase):
    def test_score_enriches_every_row(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text(_jsonl(_FIVE_DRAFTS))
            r = _run("score", "--input", str(inp), "--rubric", str(_RUBRIC), "--json")
            self.assertEqual(r.returncode, 0,
                f"stdout: {r.stdout}\nstderr: {r.stderr}")
            payload = json.loads(r.stdout)
            rows = payload["data"]["rows"]
            self.assertEqual(len(rows), 5)
            for row in rows:
                for field in ("auto_bucket", "classification_confidence",
                              "rationale", "rubric_version"):
                    self.assertIn(field, row, f"row {row.get('id')} missing {field}")

    def test_rewrite_atomic_in_place(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text(_jsonl(_FIVE_DRAFTS))
            r = _run("score", "--input", str(inp), "--rubric", str(_RUBRIC), "--rewrite")
            self.assertEqual(r.returncode, 0, r.stderr)
            new_rows = [json.loads(ln) for ln in inp.read_text().splitlines() if ln.strip()]
            self.assertEqual(len(new_rows), 5)
            for row in new_rows:
                self.assertIn("auto_bucket", row)

    def test_max_ideas_exit_1(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text(_jsonl(_FIVE_DRAFTS))
            r = _run("score", "--input", str(inp), "--rubric", str(_RUBRIC),
                     "--max-ideas", "3", "--json")
            self.assertEqual(r.returncode, 1)

    def test_max_ideas_env_override(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text(_jsonl(_FIVE_DRAFTS))
            r = _run("score", "--input", str(inp), "--rubric", str(_RUBRIC),
                     "--json", env_extra={"KAIZEN_BRAINSTORM_MAX_IDEAS": "3"})
            self.assertEqual(r.returncode, 1, r.stderr)

    def test_rubric_version_drift_blocks_rewrite(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            pre = [{**_FIVE_DRAFTS[0], "auto_bucket": "KEEP",
                    "classification_confidence": 1.0,
                    "rationale": "old",  "rubric_version": "999"}]
            inp.write_text(_jsonl(pre))
            r = _run("score", "--input", str(inp), "--rubric", str(_RUBRIC),
                     "--rewrite")
            self.assertNotEqual(r.returncode, 0,
                "drift without --force should fail")
            self.assertIn("rubric_version", r.stderr + r.stdout)

    def test_rubric_version_drift_with_force_proceeds(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            pre = [{**_FIVE_DRAFTS[0], "auto_bucket": "KEEP",
                    "classification_confidence": 1.0,
                    "rationale": "old",  "rubric_version": "999"}]
            inp.write_text(_jsonl(pre))
            r = _run("score", "--input", str(inp), "--rubric", str(_RUBRIC),
                     "--rewrite", "--force")
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
