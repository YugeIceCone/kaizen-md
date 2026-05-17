"""Tests for auto_handoff.py — threshold-driven handoff prompt."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "skills/workflow/scripts/auto_handoff.py"


class _Sandbox(unittest.TestCase):
    def setUp(self):
        self._cwd0 = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.fake_home = self.tmp / "home"
        self.fake_home.mkdir()
        self.dxm_dir = self.tmp / "dxm"
        self.dxm_dir.mkdir()
        self.cwd = self.tmp / "repo"
        self.cwd.mkdir()
        self.session_mode_path = self.tmp / "session-mode.json"

        self._orig = {}
        for k, v in (("HOME", str(self.fake_home)),
                      ("KAIZEN_DXM_DIR", str(self.dxm_dir)),
                      ("KAIZEN_SESSION_MODE_PATH", str(self.session_mode_path)),
                      ("KAIZEN_CONTEXT_LIMIT", "100000")):
            self._orig[k] = os.environ.get(k)
            os.environ[k] = v
        os.chdir(self.cwd)

    def tearDown(self):
        try: os.chdir(self._cwd0)
        except OSError: pass
        self._tmp.cleanup()
        for k, v in self._orig.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    def _seed_jsonl(self, sid: str, total_tokens: int):
        """Plant a fake CC session JSONL with one assistant turn at total_tokens."""
        slug = str(self.cwd.resolve()).replace("/", "-")
        proj = self.fake_home / ".claude" / "projects" / slug
        proj.mkdir(parents=True, exist_ok=True)
        rec = {
            "type": "assistant", "timestamp": "2026-05-17T08:00:00Z",
            "message": {"usage": {
                "input_tokens": total_tokens // 4,
                "cache_creation_input_tokens": total_tokens // 4,
                "cache_read_input_tokens": total_tokens // 4,
                "output_tokens": total_tokens - 3 * (total_tokens // 4),
            }},
        }
        (proj / f"{sid}.jsonl").write_text(json.dumps(rec) + "\n")

    def _set_mode(self, threshold: int | None):
        """Plant a session-mode state with the threshold."""
        state = {"mode": "loop", "skills": [], "bundles": [],
                 "set_at": "2026-05-17T07:00:00Z", "session_id": "",
                 "auto_handoff_threshold": threshold}
        self.session_mode_path.write_text(json.dumps(state))

    def _run(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_SCRIPT), "check", "--session", "sid-x"],
            capture_output=True, text=True, timeout=10,
            env=os.environ.copy(),
        )

    def _events(self, sid: str) -> list[dict]:
        f = self.dxm_dir / f"events-{sid}.jsonl"
        if not f.is_file(): return []
        return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


class TestFiresWhenThresholdCrossed(_Sandbox):
    def test_emits_block_decision_at_75pct_threshold(self):
        """Default config.on_fire.decision = 'block' — Stop is BLOCKED."""
        self._set_mode(75)
        self._seed_jsonl("sid-x", 80_000)  # 80% of 100k limit
        r = self._run()
        out = json.loads(r.stdout)
        self.assertEqual(out.get("decision"), "block",
                          f"expected decision=block, got {out!r}")
        self.assertIn("80%", out["reason"])
        self.assertIn("threshold 75%", out["reason"])

    def test_block_reason_has_imperative_handoff_steps(self):
        self._set_mode(75)
        self._seed_jsonl("sid-x", 80_000)
        r = self._run()
        out = json.loads(r.stdout)
        reason = out["reason"]
        # Mandatory language + the handoff scaffold invocation
        self.assertIn("MANDATORY", reason)
        self.assertIn("kaizen-handoff scaffold", reason)

    def test_writes_dxm_dedupe_marker(self):
        self._set_mode(75)
        self._seed_jsonl("sid-x", 80_000)
        self._run()
        events = self._events("sid-x")
        marker = [e for e in events if e["evt_type"] == "auto_handoff.requested"]
        self.assertEqual(len(marker), 1)
        self.assertEqual(marker[0]["payload"]["pct"], 80)
        self.assertEqual(marker[0]["payload"]["threshold"], 75)


class TestNoFireBelowThreshold(_Sandbox):
    def test_below_threshold_no_emit(self):
        self._set_mode(75)
        self._seed_jsonl("sid-x", 50_000)  # 50%, below 75% threshold
        r = self._run()
        self.assertEqual(r.stdout.strip(), "{}")


class TestDedupeOnlyFiresOnce(_Sandbox):
    def test_second_call_returns_empty(self):
        self._set_mode(75)
        self._seed_jsonl("sid-x", 80_000)
        r1 = self._run()
        self.assertEqual(json.loads(r1.stdout).get("decision"), "block")
        r2 = self._run()
        # Second call sees the dxm marker → no-op (block released)
        self.assertEqual(r2.stdout.strip(), "{}")


class TestNoSessionModeNoOp(_Sandbox):
    def test_unset_mode_no_emit(self):
        # No _set_mode call → no state file
        self._seed_jsonl("sid-x", 80_000)
        r = self._run()
        self.assertEqual(r.stdout.strip(), "{}")


class TestThresholdDisabledNoOp(_Sandbox):
    def test_threshold_None_no_emit_even_at_99pct(self):
        self._set_mode(None)  # explicitly disabled
        self._seed_jsonl("sid-x", 99_000)  # 99%
        r = self._run()
        self.assertEqual(r.stdout.strip(), "{}")


class TestBypassEnv(_Sandbox):
    def test_KAIZEN_AUTO_HANDOFF_DISABLE_no_op(self):
        self._set_mode(25)
        self._seed_jsonl("sid-x", 80_000)
        env = os.environ.copy()
        env["KAIZEN_AUTO_HANDOFF_DISABLE"] = "1"
        r = subprocess.run(
            [sys.executable, str(_SCRIPT), "check", "--session", "sid-x"],
            capture_output=True, text=True, timeout=10, env=env,
        )
        self.assertEqual(r.stdout.strip(), "{}")


class TestEachThresholdLevel(_Sandbox):
    def test_25pct_fires_at_30pct_usage(self):
        self._set_mode(25)
        self._seed_jsonl("sid-x", 30_000)  # 30%
        r = self._run()
        self.assertEqual(json.loads(r.stdout).get("decision"), "block")

    def test_85pct_does_not_fire_at_50pct_usage(self):
        self._set_mode(85)
        self._seed_jsonl("sid-x", 50_000)
        r = self._run()
        self.assertEqual(r.stdout.strip(), "{}")


class TestConfigOverride(_Sandbox):
    """User-tweaked config should override the default decision +
    template. Validates that config is actually consumed by the loader."""

    def test_systemMessage_mode_via_config_override(self):
        cfg = self.tmp / "cfg.yaml"
        cfg.write_text(
            "version: 1\n"
            "valid_thresholds: [25, 50, 75, 85]\n"
            "dedupe_event_type: auto_handoff.requested\n"
            "on_fire:\n"
            "  decision: systemMessage\n"
            "  reason_template: 'soft custom warning at {pct}%'\n"
        )
        env = os.environ.copy()
        env["KAIZEN_AUTO_HANDOFF_CONFIG"] = str(cfg)
        self._set_mode(50)
        self._seed_jsonl("sid-x", 60_000)
        r = subprocess.run(
            [sys.executable, str(_SCRIPT), "check", "--session", "sid-x"],
            capture_output=True, text=True, timeout=10, env=env,
        )
        out = json.loads(r.stdout)
        self.assertIn("systemMessage", out)
        self.assertNotIn("decision", out)
        self.assertIn("soft custom warning at 60%", out["systemMessage"])


class TestSchemaValidation(unittest.TestCase):
    """Validate the shipped config.yaml against config.schema.json,
    and the dxm event payload + hook output shapes against their
    respective schemas."""

    def test_shipped_config_validates(self):
        try:
            import jsonschema  # type: ignore
        except ImportError:
            self.skipTest("jsonschema not installed")
        import yaml
        cfg = yaml.safe_load(
            (_KZ_DIR / "skills/auto-handoff/domain/config.yaml").read_text()
        )
        schema = json.loads(
            (_KZ_DIR / "skills/auto-handoff/domain/schemas/config.schema.json").read_text()
        )
        jsonschema.validate(cfg, schema)  # no raise

    def test_block_decision_validates_against_schema(self):
        try:
            import jsonschema  # type: ignore
        except ImportError:
            self.skipTest("jsonschema not installed")
        schema = json.loads(
            (_KZ_DIR / "skills/auto-handoff/domain/schemas/decision.schema.json").read_text()
        )
        # Three valid shapes per the oneOf in the schema
        jsonschema.validate({}, schema)
        jsonschema.validate({"decision": "block",
                              "reason": "x" * 40}, schema)
        jsonschema.validate({"systemMessage": "x" * 40}, schema)

    def test_event_payload_validates_against_schema(self):
        try:
            import jsonschema  # type: ignore
        except ImportError:
            self.skipTest("jsonschema not installed")
        schema = json.loads(
            (_KZ_DIR / "skills/auto-handoff/domain/schemas/event.schema.json").read_text()
        )
        jsonschema.validate({"pct": 80, "threshold": 75,
                              "tokens": 80000, "peak_tokens": 95000}, schema)


if __name__ == "__main__":
    unittest.main()
