"""Integration tests — handoff + intent handlers emit dxm events.

Each handler that completes should fire ONE event into the active
session's dxm jsonl. Lets agents `kaizen-dxm tail` to see exactly
which subcommands ran without parsing the OUTER Bash command string.

DRY/SOLID/KISS witness: each handler adds ONE _dxm_emit.emit_event
call; no per-handler duplicated session-discovery / JSON-build /
file-append logic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
_HANDOFF_PY = _KZ_DIR / "scripts/handoff/handoff.py"
_INTENT_PY = _SCRIPTS / "intent.py"


class HandlerEmitBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.fake_home = self.tmp / "home"
        self.fake_home.mkdir()
        self.handoffs_dir = self.tmp / "handoffs"
        self.handoffs_dir.mkdir()
        self.dxm_dir = self.tmp / "dxm"
        self.dxm_dir.mkdir()

        # The repo for handoff's git ops + auto-discovered session
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        for cmd in (["git", "init", "-q"],
                     ["git", "config", "user.email", "t@t"],
                     ["git", "config", "user.name", "t"]):
            subprocess.run(cmd, cwd=str(self.repo), check=True, capture_output=True)
        (self.repo / "x").write_text("1")
        subprocess.run(["git", "add", "x"], cwd=str(self.repo), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=str(self.repo),
                        check=True, capture_output=True)

        # Fake CC project dir so session-id discovery finds something
        slug = str(self.repo.resolve()).replace("/", "-")
        self.proj_dir = self.fake_home / ".claude" / "projects" / slug
        self.proj_dir.mkdir(parents=True)
        (self.proj_dir / "sess-emit-test.jsonl").write_text(
            '{"type":"ai-title","aiTitle":"goal text"}\n')

        self._orig: dict[str, str | None] = {}
        for k, v in (
            ("HOME", str(self.fake_home)),
            ("KAIZEN_HANDOFF_DIR", str(self.handoffs_dir)),
            ("KAIZEN_HANDOFF_DB", str(self.tmp / "handoff.db")),
            ("KAIZEN_DXM_DIR", str(self.dxm_dir)),
            ("KAIZEN_INTENTS_FILE", str(self.tmp / "intents.yaml")),
        ):
            self._orig[k] = os.environ.get(k)
            os.environ[k] = v

        # Default minimal intents.yaml
        (self.tmp / "intents.yaml").write_text(textwrap.dedent("""\
            version: 1
            intents:
              - id: t
                triggers: [{kind: phrase, pattern: "x"}]
                action: {suggest: "y", confidence: 0.9}
        """))

    def tearDown(self):
        self._tmp.cleanup()
        for k, v in self._orig.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    def _handoff(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_HANDOFF_PY), *args],
            capture_output=True, text=True, timeout=30,
            cwd=str(self.repo),
            env=os.environ.copy(),
        )

    def _intent(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_INTENT_PY), *args],
            input=stdin, capture_output=True, text=True, timeout=15,
            cwd=str(self.repo),
            env=os.environ.copy(),
        )

    def _events(self) -> list[dict]:
        p = self.dxm_dir / "events-sess-emit-test.jsonl"
        if not p.is_file(): return []
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


_PLACEHOLDER_YAML = textwrap.dedent("""\
    ---
    session: sess-emit-test
    date: 2026-05-17
    status: partial
    outcome: IN_PROGRESS
    ---

    goal: t
    now: u
    test: noop

    done_this_session: []
    blockers: []
    questions: []
    decisions: []
    findings: []
    worked: []
    failed: []
    next: []

    files:
      created: []
      modified: []
""")


# ─── handoff handlers ────────────────────────────────────────────────


class TestHandoffScaffoldEmits(HandlerEmitBase):
    def test_scaffold_emits_event(self):
        r = self._handoff(
            "scaffold", "--session", "s",
            "--goal", "g", "--now", "n",
            "--at", "2026-05-17_07-00", "--json",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._events()
        evt_types = [e["evt_type"] for e in events]
        self.assertIn("handoff.scaffold.complete", evt_types)


class TestHandoffVerifyEmits(HandlerEmitBase):
    def test_verify_emits_event(self):
        yaml = self.tmp / "v.yaml"
        yaml.write_text(_PLACEHOLDER_YAML)
        r = self._handoff("verify", "--file", str(yaml), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._events()
        evt_types = [e["evt_type"] for e in events]
        self.assertIn("handoff.verify.complete", evt_types)


class TestHandoffAssessEmits(HandlerEmitBase):
    def test_assess_emits_event(self):
        yaml = self.tmp / "a.yaml"
        yaml.write_text(_PLACEHOLDER_YAML)
        r = self._handoff("assess", "--file", str(yaml), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._events()
        evt_types = [e["evt_type"] for e in events]
        self.assertIn("handoff.assess.complete", evt_types)


class TestHandoffAutoFinalizeEmits(HandlerEmitBase):
    def test_auto_finalize_emits_event(self):
        sess_dir = self.handoffs_dir / "sess-emit-test"
        sess_dir.mkdir()
        yaml = sess_dir / "f.yaml"
        yaml.write_text(_PLACEHOLDER_YAML)
        r = self._handoff("auto-finalize", "--file", str(yaml),
                           "--outcome", "SUCCEEDED", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._events()
        evt_types = [e["evt_type"] for e in events]
        self.assertIn("handoff.auto-finalize.complete", evt_types)


# ─── intent handlers ─────────────────────────────────────────────────


class TestIntentMatchEmits(HandlerEmitBase):
    def test_match_emits_event(self):
        r = self._intent("match", "--text", "x is here", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._events()
        evt_types = [e["evt_type"] for e in events]
        self.assertIn("intent.match.complete", evt_types)


class TestIntentSuggestEmits(HandlerEmitBase):
    def test_suggest_emits_event(self):
        r = self._intent("suggest", "--text", "x in prompt", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._events()
        evt_types = [e["evt_type"] for e in events]
        self.assertIn("intent.suggest.complete", evt_types)


# ─── No emit when KAIZEN_DXM_DISABLE=1 ────────────────────────────────


class TestEmitBypass(HandlerEmitBase):
    def test_disable_env_suppresses_emit(self):
        os.environ["KAIZEN_DXM_DISABLE"] = "1"
        try:
            yaml = self.tmp / "y.yaml"
            yaml.write_text(_PLACEHOLDER_YAML)
            r = self._handoff("verify", "--file", str(yaml), "--json")
            self.assertEqual(r.returncode, 0)
            self.assertEqual(self._events(), [])
        finally:
            del os.environ["KAIZEN_DXM_DISABLE"]


if __name__ == "__main__":
    unittest.main()
