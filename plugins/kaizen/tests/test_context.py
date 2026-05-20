#!/usr/bin/env python3
"""Unit tests for context.py — pure-Python, no subprocess.

Run:
    python3 -m unittest tests.test_context -v
    OR
    python3 tests/test_context.py

Covers:
    - get_tokens: env-var priority, alternate env names, stdin JSON fallback
    - get_limit: default + KAIZEN_CONTEXT_LIMIT override
    - zone_of: green/yellow/red/unknown thresholds
    - missing inputs return None / unknown (no crash)
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

def _fresh():
    """Reimport context module (no env mutation — caller controls env)."""
    if "context" in sys.modules:
        del sys.modules["context"]
    import context  # noqa: E402
    return context

def _clear_env():
    for k in (
        "CLAUDE_CONTEXT_TOKENS", "CLAUDE_USAGE_TOTAL_TOKENS",
        "KAIZEN_CONTEXT_LIMIT", "KAIZEN_MODEL_ID", "CLAUDE_MODEL_ID",
    ):
        os.environ.pop(k, None)

class TestGetTokens(unittest.TestCase):
    def setUp(self):
        _clear_env()
    def test_env_primary(self):
        os.environ["CLAUDE_CONTEXT_TOKENS"] = "55000"
        c = _fresh()
        self.assertEqual(c.get_tokens(), 55000)

    def test_env_alternate(self):
        os.environ["CLAUDE_USAGE_TOTAL_TOKENS"] = "33000"
        c = _fresh()
        self.assertEqual(c.get_tokens(), 33000)

    def test_env_invalid_falls_through(self):
        os.environ["CLAUDE_CONTEXT_TOKENS"] = "not-a-number"
        c = _fresh()
        # falls through to stdin (empty) → None
        self.assertIsNone(c.get_tokens())

    def test_stdin_total_tokens(self):
        c = _fresh()
        self.assertEqual(c.get_tokens('{"total_tokens": 12345}'), 12345)

    def test_stdin_nested_usage(self):
        c = _fresh()
        self.assertEqual(c.get_tokens('{"usage": {"total_tokens": 9999}}'), 9999)

    def test_stdin_invalid_json(self):
        c = _fresh()
        self.assertIsNone(c.get_tokens("not json"))

    def test_stdin_missing_field(self):
        c = _fresh()
        self.assertIsNone(c.get_tokens('{"other_field": 1}'))

    def test_env_beats_stdin(self):
        os.environ["CLAUDE_CONTEXT_TOKENS"] = "100"
        c = _fresh()
        # env=100 wins over stdin=999
        self.assertEqual(c.get_tokens('{"total_tokens": 999}'), 100)

class TestGetLimit(unittest.TestCase):
    def setUp(self):
        _clear_env()

    def test_default(self):
        c = _fresh()
        self.assertEqual(c.get_limit(), 200_000)

    def test_override(self):
        os.environ["KAIZEN_CONTEXT_LIMIT"] = "500000"
        c = _fresh()
        self.assertEqual(c.get_limit(), 500_000)

    def test_invalid_falls_back(self):
        os.environ["KAIZEN_CONTEXT_LIMIT"] = "garbage"
        c = _fresh()
        self.assertEqual(c.get_limit(), 200_000)

class TestModelAwareLimit(unittest.TestCase):
    """Limit must reflect the *active model's* context window.

    Opus 4.7 [1m] = 1,000,000 tokens. Default Sonnet/Opus/Haiku = 200k.
    KAIZEN_CONTEXT_LIMIT still wins (explicit > derived).
    """

    def setUp(self):
        _clear_env()

    def test_explicit_env_beats_model(self):
        os.environ["KAIZEN_CONTEXT_LIMIT"] = "300000"
        os.environ["KAIZEN_MODEL_ID"] = "claude-opus-4-7[1m]"
        c = _fresh()
        self.assertEqual(c.get_limit(), 300_000)

    def test_opus_1m_via_kaizen_env(self):
        os.environ["KAIZEN_MODEL_ID"] = "claude-opus-4-7[1m]"
        c = _fresh()
        self.assertEqual(c.get_limit(), 1_000_000)

    def test_opus_1m_via_claude_env(self):
        os.environ["CLAUDE_MODEL_ID"] = "claude-opus-4-7[1m]"
        c = _fresh()
        self.assertEqual(c.get_limit(), 1_000_000)

    def test_standard_opus_uses_200k(self):
        os.environ["KAIZEN_MODEL_ID"] = "claude-opus-4-5"
        c = _fresh()
        self.assertEqual(c.get_limit(), 200_000)

    def test_standard_sonnet_uses_200k(self):
        os.environ["KAIZEN_MODEL_ID"] = "claude-sonnet-4-6"
        c = _fresh()
        self.assertEqual(c.get_limit(), 200_000)

    def test_dash_1m_suffix_recognized(self):
        """Heuristic: any model id with -1m or [1m] is 1M context."""
        os.environ["KAIZEN_MODEL_ID"] = "some-future-1m-model"
        c = _fresh()
        self.assertEqual(c.get_limit(), 1_000_000)

    def test_unknown_model_falls_back_to_200k(self):
        os.environ["KAIZEN_MODEL_ID"] = "completely-unknown-model"
        c = _fresh()
        self.assertEqual(c.get_limit(), 200_000)

    def test_limit_for_model_pure_fn(self):
        """Direct test of the pure helper — no env coupling."""
        c = _fresh()
        self.assertEqual(c.limit_for_model("claude-opus-4-7[1m]"), 1_000_000)
        self.assertEqual(c.limit_for_model("claude-opus-4-7-1m"), 1_000_000)
        self.assertEqual(c.limit_for_model("claude-opus-4-5"), 200_000)
        self.assertEqual(c.limit_for_model(""), 200_000)
        self.assertEqual(c.limit_for_model(None), 200_000)

    def test_defensive_autodetect_from_observed_usage(self):
        """If observed peak > 200k, the active model MUST be 1M context.
        CC's JSONL strips the [1m] suffix from the model field, so the
        usage signal is the authoritative tell."""
        c = _fresh()
        # Stub get_usage_summary to simulate a session with 320k peak
        # (only possible on a 1M-context model)
        orig = c.get_usage_summary
        try:
            c.get_usage_summary = lambda cwd_path=None: {
                "current_tokens": 320_000, "peak_tokens": 320_000,
                "peak_pre_compact": False, "compact_count": 0,
            }
            self.assertEqual(c.get_limit(), 1_000_000)
        finally:
            c.get_usage_summary = orig

    def test_defensive_autodetect_skipped_when_peak_under_200k(self):
        c = _fresh()
        orig = c.get_usage_summary
        try:
            c.get_usage_summary = lambda cwd_path=None: {
                "current_tokens": 150_000, "peak_tokens": 150_000,
                "peak_pre_compact": False, "compact_count": 0,
            }
            self.assertEqual(c.get_limit(), 200_000)
        finally:
            c.get_usage_summary = orig

class TestZone(unittest.TestCase):
    def setUp(self):
        self.c = _fresh()

    def test_green(self):
        self.assertEqual(self.c.zone_of(0), "green")
        self.assertEqual(self.c.zone_of(59), "green")

    def test_yellow(self):
        self.assertEqual(self.c.zone_of(60), "yellow")
        self.assertEqual(self.c.zone_of(79), "yellow")

    def test_red(self):
        self.assertEqual(self.c.zone_of(80), "red")
        self.assertEqual(self.c.zone_of(100), "red")
        self.assertEqual(self.c.zone_of(150), "red")  # over-limit still red

    def test_unknown(self):
        self.assertEqual(self.c.zone_of(None), "unknown")

# ─── BK-015: peak-aware get_usage_summary ───────────────────────────

import json
import tempfile

def _usage_record(tokens: int, ts: str = "2026-01-01T00:00:00Z") -> dict:
    """Build a minimal assistant JSONL record with the given total tokens
    split across the four usage fields the same way CC reports them."""
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "usage": {
                "input_tokens": tokens // 4,
                "cache_creation_input_tokens": tokens // 4,
                "cache_read_input_tokens": tokens // 4,
                "output_tokens": tokens - 3 * (tokens // 4),
            },
        },
    }

def _compact_marker() -> dict:
    return {
        "type": "user",
        "timestamp": "2026-01-01T00:00:30Z",
        "isCompactSummary": True,
        "isVisibleInTranscriptOnly": True,
        "message": {"role": "user", "content": "summary…"},
    }

class PeakAwareReaderBase(unittest.TestCase):
    def setUp(self):
        self._cwd0 = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.fake_home = self.tmp / "home"
        self.cwd = self.tmp / "repo"
        self.cwd.mkdir()
        self._orig_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.fake_home)
        os.chdir(self.cwd)
        # Pre-create the project slug dir
        slug = str(self.cwd.resolve()).replace("/", "-")
        self.proj = self.fake_home / ".claude" / "projects" / slug
        self.proj.mkdir(parents=True)
        self.sid = "test-sid-peak"
        self.jsonl = self.proj / f"{self.sid}.jsonl"
        _clear_env()

    def tearDown(self):
        try: os.chdir(self._cwd0)
        except OSError: pass
        self._tmp.cleanup()
        if self._orig_home is None: os.environ.pop("HOME", None)
        else: os.environ["HOME"] = self._orig_home

    def _write_jsonl(self, records: list[dict]):
        with self.jsonl.open("w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

class TestPeakDetection(PeakAwareReaderBase):
    def test_peak_equals_max_assistant_usage(self):
        self._write_jsonl([
            _usage_record(50_000),
            _usage_record(120_000),
            _usage_record(80_000),
        ])
        c = _fresh()
        summary = c.get_usage_summary(cwd_path=self.cwd)
        self.assertEqual(summary["peak_tokens"], 120_000)
        self.assertEqual(summary["current_tokens"], 80_000)
        self.assertEqual(summary["compact_count"], 0)
        self.assertFalse(summary["peak_pre_compact"])

    def test_peak_pre_compact_when_max_before_marker(self):
        # Rising to 950K, then compact, then 30K (post-compact)
        self._write_jsonl([
            _usage_record(100_000),
            _usage_record(500_000),
            _usage_record(950_000),
            _compact_marker(),
            _usage_record(30_000),
            _usage_record(45_000),
        ])
        c = _fresh()
        summary = c.get_usage_summary(cwd_path=self.cwd)
        self.assertEqual(summary["peak_tokens"], 950_000)
        self.assertEqual(summary["current_tokens"], 45_000)
        self.assertEqual(summary["compact_count"], 1)
        self.assertTrue(summary["peak_pre_compact"])

    def test_peak_post_compact_when_max_after_marker(self):
        self._write_jsonl([
            _usage_record(100_000),
            _compact_marker(),
            _usage_record(200_000),
            _usage_record(150_000),
        ])
        c = _fresh()
        summary = c.get_usage_summary(cwd_path=self.cwd)
        self.assertEqual(summary["peak_tokens"], 200_000)
        self.assertEqual(summary["compact_count"], 1)
        self.assertFalse(summary["peak_pre_compact"])

    def test_multiple_compact_markers_counted(self):
        self._write_jsonl([
            _usage_record(800_000),
            _compact_marker(),
            _usage_record(50_000),
            _compact_marker(),
            _usage_record(20_000),
        ])
        c = _fresh()
        summary = c.get_usage_summary(cwd_path=self.cwd)
        self.assertEqual(summary["compact_count"], 2)
        self.assertEqual(summary["peak_tokens"], 800_000)
        self.assertEqual(summary["current_tokens"], 20_000)
        self.assertTrue(summary["peak_pre_compact"])

    def test_no_jsonl_returns_all_none(self):
        # No JSONL exists at all
        c = _fresh()
        summary = c.get_usage_summary(cwd_path=self.cwd)
        self.assertIsNone(summary["current_tokens"])
        self.assertIsNone(summary["peak_tokens"])
        self.assertEqual(summary["compact_count"], 0)
        self.assertFalse(summary["peak_pre_compact"])

    def test_empty_jsonl_returns_all_none(self):
        self.jsonl.write_text("")
        c = _fresh()
        summary = c.get_usage_summary(cwd_path=self.cwd)
        self.assertIsNone(summary["peak_tokens"])

    def test_existing_get_tokens_from_jsonl_unchanged(self):
        # Backward-compat: the existing single-turn API still returns
        # just the LAST assistant turn's total.
        self._write_jsonl([
            _usage_record(800_000),
            _compact_marker(),
            _usage_record(30_000),
        ])
        c = _fresh()
        self.assertEqual(c.get_tokens_from_jsonl(cwd_path=self.cwd), 30_000)

class TestStatuslineLineSubcommand(unittest.TestCase):
    """`context.py line` emits a pre-formatted statusline segment
    (icon + tokens/limit + pct) in ONE python3 spawn — replacing the
    5-spawn pattern in statusline.sh."""

    def _run(self, stdin_text: str = "",
              env_extra: dict | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        for k in ("CLAUDE_CONTEXT_TOKENS", "CLAUDE_USAGE_TOTAL_TOKENS",
                   "KAIZEN_CONTEXT_LIMIT"):
            env.pop(k, None)
        if env_extra:
            env.update(env_extra)
        script = (Path(__file__).resolve().parent.parent
                   / "scripts" / "util" / "context.py")
        return subprocess.run(
            ["python3", str(script), "line"],
            input=stdin_text, capture_output=True, text=True,
            timeout=10, env=env,
        )

    def test_green_zone_emits_green_icon(self):
        env = {"KAIZEN_CONTEXT_LIMIT": "200000"}
        r = self._run('{"total_tokens": 50000}', env_extra=env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("🟢", r.stdout)
        self.assertIn("50k", r.stdout)
        self.assertIn("25%", r.stdout)

    def test_yellow_zone(self):
        env = {"KAIZEN_CONTEXT_LIMIT": "100000"}
        r = self._run('{"total_tokens": 70000}', env_extra=env)
        self.assertIn("🟡", r.stdout)

    def test_red_zone(self):
        env = {"KAIZEN_CONTEXT_LIMIT": "100000"}
        r = self._run('{"total_tokens": 90000}', env_extra=env)
        self.assertIn("🔴", r.stdout)

    def test_unknown_emits_empty(self):
        r = self._run("")  # no env, no stdin
        self.assertEqual(r.returncode, 0)
        # Empty stdout (or whitespace) — caller treats as "no segment"
        self.assertEqual(r.stdout.strip(), "")

# Imports needed by the subprocess test above (added at use site to
# avoid pollution of earlier classes that use `_fresh()` reimport).
import subprocess

if __name__ == "__main__":
    unittest.main(verbosity=2)
