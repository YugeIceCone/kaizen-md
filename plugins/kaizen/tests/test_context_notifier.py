"""Tests for context.py from-jsonl source + context_notifier.py.

CC's authoritative context-window source is the latest assistant
turn's `message.usage` in the session JSONL — env vars are
inconsistent across CC versions.

The notifier checks zone, dedupes via dxm event history (only emits
on zone transitions), surfaces dxm events for handoff+intent to
consume.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
_CONTEXT_PY = _SCRIPTS / "context.py"
_NOTIFIER_PY = _SCRIPTS / "context_notifier.py"


class CtxBase(unittest.TestCase):
    def setUp(self):
        self._cwd0 = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.fake_home = self.tmp / "home"
        self.fake_home.mkdir()
        self.dxm_dir = self.tmp / "dxm"
        self.dxm_dir.mkdir()

        self._orig: dict[str, str | None] = {}
        for k, v in (("HOME", str(self.fake_home)),
                      ("KAIZEN_DXM_DIR", str(self.dxm_dir))):
            self._orig[k] = os.environ.get(k)
            os.environ[k] = v

    def tearDown(self):
        try:
            os.chdir(self._cwd0)
        except OSError:
            pass
        self._tmp.cleanup()
        for k, v in self._orig.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    def _seed_jsonl(self, cwd: Path, sid: str, *,
                     input_t=0, cache_read=0, cache_create=0, output_t=0):
        """Seed a fake CC JSONL with one assistant turn carrying the
        supplied usage tokens."""
        slug = str(cwd.resolve()).replace("/", "-")
        proj = self.fake_home / ".claude" / "projects" / slug
        proj.mkdir(parents=True, exist_ok=True)
        jsonl = proj / f"{sid}.jsonl"
        records = [
            {"type": "assistant",
              "timestamp": "2026-05-17T07:00:00.000Z",
              "message": {
                  "model": "claude-opus-4-7",
                  "content": [{"type": "text", "text": "ok"}],
                  "usage": {
                      "input_tokens": input_t,
                      "cache_creation_input_tokens": cache_create,
                      "cache_read_input_tokens": cache_read,
                      "output_tokens": output_t,
                  },
              }},
        ]
        with jsonl.open("w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return jsonl


# ─── context.py from-jsonl ───────────────────────────────────────────


class TestContextFromJsonl(CtxBase):
    def _run_ctx(self, *args: str, cwd=None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_CONTEXT_PY), *args],
            capture_output=True, text=True, timeout=10,
            cwd=str(cwd) if cwd else None,
            env=os.environ.copy(),
        )

    def test_from_jsonl_sums_all_usage_fields(self):
        cwd = self.tmp / "p"
        cwd.mkdir()
        self._seed_jsonl(cwd, "sess-ctx",
                           input_t=1000, cache_read=50000,
                           cache_create=10000, output_t=500)
        os.environ["KAIZEN_CONTEXT_LIMIT"] = "200000"
        r = self._run_ctx("from-jsonl", cwd=cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        # 1000 + 50000 + 10000 + 500 = 61500
        self.assertEqual(out["tokens"], 61500)
        self.assertEqual(out["limit"], 200000)
        self.assertEqual(out["pct"], 30)  # 61500 / 200000
        self.assertEqual(out["zone"], "green")

    def test_yellow_zone_at_60_pct(self):
        cwd = self.tmp / "p2"
        cwd.mkdir()
        os.environ["KAIZEN_CONTEXT_LIMIT"] = "100000"
        self._seed_jsonl(cwd, "sess-y",
                           cache_read=65000)  # 65% of 100k
        r = self._run_ctx("from-jsonl", cwd=cwd)
        out = json.loads(r.stdout)
        self.assertEqual(out["zone"], "yellow")

    def test_red_zone_at_85_pct(self):
        cwd = self.tmp / "p3"
        cwd.mkdir()
        os.environ["KAIZEN_CONTEXT_LIMIT"] = "100000"
        self._seed_jsonl(cwd, "sess-r", cache_read=85000)
        r = self._run_ctx("from-jsonl", cwd=cwd)
        out = json.loads(r.stdout)
        self.assertEqual(out["zone"], "red")

    def test_no_jsonl_returns_unknown(self):
        cwd = self.tmp / "no-jsonl"
        cwd.mkdir()
        r = self._run_ctx("from-jsonl", cwd=cwd)
        out = json.loads(r.stdout)
        self.assertEqual(out["zone"], "unknown")
        self.assertIsNone(out["tokens"])


# ─── context_notifier.py — emit dxm events on zone transitions ───────


class TestNotifier(CtxBase):
    def _run_notifier(self, *args: str, cwd=None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_NOTIFIER_PY), *args],
            capture_output=True, text=True, timeout=10,
            cwd=str(cwd) if cwd else None,
            env=os.environ.copy(),
        )

    def _events(self, sid: str) -> list[dict]:
        p = self.dxm_dir / f"events-{sid}.jsonl"
        if not p.is_file(): return []
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

    def test_emits_warn_yellow_on_first_yellow(self):
        cwd = self.tmp / "p"
        cwd.mkdir()
        os.environ["KAIZEN_CONTEXT_LIMIT"] = "100000"
        self._seed_jsonl(cwd, "sess-warn", cache_read=70000)
        r = self._run_notifier("check", cwd=cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._events("sess-warn")
        warn = [e for e in events if e["evt_type"].startswith("context.warn")]
        self.assertEqual(len(warn), 1)
        self.assertEqual(warn[0]["evt_type"], "context.warn.yellow")
        self.assertEqual(warn[0]["payload"]["zone"], "yellow")

    def test_emits_warn_red_on_red(self):
        cwd = self.tmp / "p2"
        cwd.mkdir()
        os.environ["KAIZEN_CONTEXT_LIMIT"] = "100000"
        self._seed_jsonl(cwd, "sess-red", cache_read=90000)
        self._run_notifier("check", cwd=cwd)
        events = self._events("sess-red")
        warn = [e for e in events if e["evt_type"].startswith("context.warn")]
        self.assertEqual(warn[0]["evt_type"], "context.warn.red")

    def test_no_emit_when_green(self):
        cwd = self.tmp / "p3"
        cwd.mkdir()
        os.environ["KAIZEN_CONTEXT_LIMIT"] = "100000"
        self._seed_jsonl(cwd, "sess-green", cache_read=10000)
        self._run_notifier("check", cwd=cwd)
        events = self._events("sess-green")
        warn = [e for e in events if e["evt_type"].startswith("context.warn")]
        self.assertEqual(warn, [])

    def test_dedupe_no_re_emit_same_zone(self):
        """Two consecutive checks in yellow → only one warn event."""
        cwd = self.tmp / "p4"
        cwd.mkdir()
        os.environ["KAIZEN_CONTEXT_LIMIT"] = "100000"
        self._seed_jsonl(cwd, "sess-dedupe", cache_read=70000)
        self._run_notifier("check", cwd=cwd)
        self._run_notifier("check", cwd=cwd)
        events = self._events("sess-dedupe")
        warn = [e for e in events if e["evt_type"].startswith("context.warn")]
        self.assertEqual(len(warn), 1,
                          f"deduped emit failed; got {len(warn)} warn events")

    def test_emit_on_zone_transition_yellow_to_red(self):
        cwd = self.tmp / "p5"
        cwd.mkdir()
        os.environ["KAIZEN_CONTEXT_LIMIT"] = "100000"
        self._seed_jsonl(cwd, "sess-trans", cache_read=70000)
        self._run_notifier("check", cwd=cwd)
        # Bump usage to red
        self._seed_jsonl(cwd, "sess-trans", cache_read=90000)
        self._run_notifier("check", cwd=cwd)
        events = self._events("sess-trans")
        warn = [e for e in events if e["evt_type"].startswith("context.warn")]
        zones = [e["payload"]["zone"] for e in warn]
        self.assertEqual(zones, ["yellow", "red"])

    def test_check_envelope_shape(self):
        cwd = self.tmp / "p6"
        cwd.mkdir()
        os.environ["KAIZEN_CONTEXT_LIMIT"] = "100000"
        self._seed_jsonl(cwd, "sess-env", cache_read=85000)
        r = self._run_notifier("check", "--json", cwd=cwd)
        env = json.loads(r.stdout)
        self.assertIn("data", env)
        d = env["data"]
        self.assertEqual(d["zone"], "red")
        self.assertEqual(d["pct"], 85)
        self.assertTrue(d["emitted"])

    def test_no_session_skips_silently(self):
        cwd = self.tmp / "no-proj"
        cwd.mkdir()
        r = self._run_notifier("check", "--json", cwd=cwd)
        # Exit 0, just skip
        self.assertEqual(r.returncode, 0)
        env = json.loads(r.stdout)
        self.assertFalse(env["data"]["emitted"])


# ─── Peak-aware enrichment (BK-015 wire-up) ──────────────────────────


def _make_turn(total: int, ts: str = "2026-05-17T07:00:00Z") -> dict:
    return {
        "type": "assistant", "timestamp": ts,
        "message": {"usage": {
            "input_tokens": total // 4,
            "cache_creation_input_tokens": total // 4,
            "cache_read_input_tokens": total // 4,
            "output_tokens": total - 3 * (total // 4),
        }},
    }


def _compact_marker() -> dict:
    return {"type": "user", "timestamp": "2026-05-17T07:01:00Z",
            "isCompactSummary": True, "isVisibleInTranscriptOnly": True,
            "message": {"role": "user", "content": "summary"}}


class TestNotifierPeakEnrichment(CtxBase):
    def _run_notifier(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, str(_NOTIFIER_PY), *args],
            capture_output=True, text=True, timeout=10,
            cwd=str(cwd) if cwd else None, env=os.environ.copy(),
        )

    def _seed_multi(self, cwd: Path, sid: str, records: list[dict]):
        slug = str(cwd.resolve()).replace("/", "-")
        proj = self.fake_home / ".claude" / "projects" / slug
        proj.mkdir(parents=True, exist_ok=True)
        jsonl = proj / f"{sid}.jsonl"
        with jsonl.open("w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def _events(self, sid):
        p = self.dxm_dir / f"events-{sid}.jsonl"
        if not p.is_file(): return []
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

    def test_payload_includes_peak_tokens(self):
        cwd = self.tmp / "p1"
        cwd.mkdir()
        os.environ["KAIZEN_CONTEXT_LIMIT"] = "100000"
        # Rising usage, current = peak = 90k (single-rise, red zone)
        self._seed_multi(cwd, "sess-peak", [
            _make_turn(20_000),
            _make_turn(60_000),
            _make_turn(90_000),
        ])
        self._run_notifier("check", cwd=cwd)
        events = self._events("sess-peak")
        warn = [e for e in events if e["evt_type"].startswith("context.warn")]
        self.assertEqual(len(warn), 1, "expected one red warn event")
        payload = warn[0]["payload"]
        self.assertEqual(payload["peak_tokens"], 90_000)
        self.assertFalse(payload["peak_pre_compact"])
        self.assertEqual(payload["compact_count"], 0)

    def test_post_compact_payload_exposes_peak(self):
        """After compact: current dropped to green, but peak was red.
        Notifier zone follows current — green = no warn emit — but if
        any warn DID emit (e.g. yellow), the payload must surface the
        true peak so consumers can react."""
        cwd = self.tmp / "p2"
        cwd.mkdir()
        os.environ["KAIZEN_CONTEXT_LIMIT"] = "100000"
        # 95k pre-compact (red), then compact, then 70k post (yellow)
        self._seed_multi(cwd, "sess-postcompact", [
            _make_turn(95_000),
            _compact_marker(),
            _make_turn(70_000),
        ])
        self._run_notifier("check", cwd=cwd)
        events = self._events("sess-postcompact")
        warn = [e for e in events if e["evt_type"].startswith("context.warn")]
        # Current zone = yellow (70k) → one warn fires
        self.assertEqual(len(warn), 1)
        self.assertEqual(warn[0]["payload"]["zone"], "yellow")
        self.assertEqual(warn[0]["payload"]["peak_tokens"], 95_000)
        self.assertTrue(warn[0]["payload"]["peak_pre_compact"])
        self.assertEqual(warn[0]["payload"]["compact_count"], 1)

    def test_envelope_data_includes_peak_fields(self):
        cwd = self.tmp / "p3"
        cwd.mkdir()
        os.environ["KAIZEN_CONTEXT_LIMIT"] = "100000"
        self._seed_multi(cwd, "sess-env", [
            _make_turn(40_000),
            _make_turn(85_000),
        ])
        r = self._run_notifier("check", "--json", cwd=cwd)
        env = json.loads(r.stdout)
        d = env["data"]
        # Backward-compat fields
        self.assertEqual(d["tokens"], 85_000)
        self.assertEqual(d["zone"], "red")
        # New peak-aware fields
        self.assertEqual(d["peak_tokens"], 85_000)
        self.assertEqual(d["compact_count"], 0)
        self.assertFalse(d["peak_pre_compact"])


if __name__ == "__main__":
    unittest.main()
