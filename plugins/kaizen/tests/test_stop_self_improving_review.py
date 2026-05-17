"""Tests for stop_self_improving_review.py — periodic curation nudge."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "skills/workflow/scripts/stop_self_improving_review.py"


class _Sandbox(unittest.TestCase):
    def setUp(self):
        self._cwd0 = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.dxm_dir = self.tmp / "dxm"
        self.dxm_dir.mkdir()
        self._orig = os.environ.get("KAIZEN_DXM_DIR")
        os.environ["KAIZEN_DXM_DIR"] = str(self.dxm_dir)
        # Default cadence 5 unless overridden by test
        self._orig_every = os.environ.pop(
            "KAIZEN_SELF_IMPROVING_EVERY_N", None)
        self._orig_disable = os.environ.pop(
            "KAIZEN_SELF_IMPROVING_REVIEW_DISABLE", None)

    def tearDown(self):
        try: os.chdir(self._cwd0)
        except OSError: pass
        self._tmp.cleanup()
        if self._orig is None: os.environ.pop("KAIZEN_DXM_DIR", None)
        else: os.environ["KAIZEN_DXM_DIR"] = self._orig
        if self._orig_every is not None:
            os.environ["KAIZEN_SELF_IMPROVING_EVERY_N"] = self._orig_every
        if self._orig_disable is not None:
            os.environ["KAIZEN_SELF_IMPROVING_REVIEW_DISABLE"] = self._orig_disable

    def _seed_stops(self, sid: str, n: int):
        """Plant N Stop events in the per-session dxm log."""
        f = self.dxm_dir / f"events-{sid}.jsonl"
        with f.open("w") as fh:
            for i in range(n):
                rec = {"ts_unix": 1000 + i, "session_id": sid,
                       "evt_type": "Stop"}
                fh.write(json.dumps(rec, separators=(",", ":")) + "\n")

    def _run(self, sid: str, env_extra: dict | None = None):
        env = os.environ.copy()
        if env_extra: env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(_SCRIPT), "check", "--session", sid],
            capture_output=True, text=True, timeout=5, env=env,
        )


class TestNoStopsNoOp(_Sandbox):
    def test_zero_events_returns_empty(self):
        r = self._run("sid-zero")
        self.assertEqual(r.stdout.strip(), "{}")


class TestBelowCadenceNoOp(_Sandbox):
    def test_under_default_5_no_emit(self):
        self._seed_stops("sid-low", 3)  # below 5
        r = self._run("sid-low")
        self.assertEqual(r.stdout.strip(), "{}")


class TestCadenceMultiples(_Sandbox):
    def test_5th_stop_fires(self):
        self._seed_stops("sid-5", 5)
        r = self._run("sid-5")
        out = json.loads(r.stdout)
        self.assertIn("systemMessage", out)
        self.assertIn("5 Stop events", out["systemMessage"])
        self.assertIn("/kaizen:self-improving", out["systemMessage"])

    def test_10th_stop_fires(self):
        self._seed_stops("sid-10", 10)
        r = self._run("sid-10")
        out = json.loads(r.stdout)
        self.assertIn("systemMessage", out)

    def test_6th_stop_no_fire(self):
        # Not a multiple of 5 → no fire
        self._seed_stops("sid-6", 6)
        r = self._run("sid-6")
        self.assertEqual(r.stdout.strip(), "{}")


class TestConfigurableCadence(_Sandbox):
    def test_every_2_fires_on_2nd(self):
        self._seed_stops("sid-2", 2)
        r = self._run("sid-2",
                       env_extra={"KAIZEN_SELF_IMPROVING_EVERY_N": "2"})
        self.assertIn("systemMessage", json.loads(r.stdout))

    def test_every_100_silent_at_50(self):
        self._seed_stops("sid-100", 50)
        r = self._run("sid-100",
                       env_extra={"KAIZEN_SELF_IMPROVING_EVERY_N": "100"})
        self.assertEqual(r.stdout.strip(), "{}")


class TestBypassEnv(_Sandbox):
    def test_disable_no_op(self):
        self._seed_stops("sid-byp", 5)
        r = self._run("sid-byp",
                       env_extra={"KAIZEN_SELF_IMPROVING_REVIEW_DISABLE": "1"})
        self.assertEqual(r.stdout.strip(), "{}")


class TestInvalidCadenceDefaults(_Sandbox):
    def test_garbage_env_falls_back_to_5(self):
        self._seed_stops("sid-garb", 5)
        r = self._run("sid-garb",
                       env_extra={"KAIZEN_SELF_IMPROVING_EVERY_N": "garbage"})
        self.assertIn("systemMessage", json.loads(r.stdout))


if __name__ == "__main__":
    unittest.main()
