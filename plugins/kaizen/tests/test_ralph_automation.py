"""TDD — Ralph full-automation gaps surfaced by the stale-loop bug.

Two net-new features:
  #1 — hour-resolution TTL (KAIZEN_LOOP_MAX_AGE_HOURS, default 12)
       Existing _is_stale checks days only (default 30); too coarse to
       catch the same-session stuck state we hit.
  #2 — session-boundary auto-archive
       stop-ralph.sh currently silent-exits when state.session_id ≠
       hook.session_id. Should archive + delete instead so the next
       loop in a new session starts clean.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_LEDGER = _KZ_DIR / "skills/workflow/scripts/loop_ledger.py"
_HOOK = _KZ_DIR / "hooks/claude/stop-ralph.sh"


def _load_ledger():
    spec = importlib.util.spec_from_file_location("loop_ledger_auto", _LEDGER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["loop_ledger_auto"] = mod
    spec.loader.exec_module(mod)
    return mod


def _seed_state(cwd: Path, *, started_at: str,
                  session_id: str = "",
                  iteration: int = 1,
                  body: str = "do the thing") -> Path:
    state = cwd / ".kaizen" / "loop.state.md"
    state.parent.mkdir(parents=True, exist_ok=True)
    fm = textwrap.dedent(f"""\
        ---
        active: true
        iteration: {iteration}
        session_id: "{session_id}"
        max_iterations: 0
        completion_promise: null
        started_at: "{started_at}"
        ---
        """)
    state.write_text(fm + body + "\n")
    return state


# ─── #1 — hour-resolution TTL ────────────────────────────────────────


class TestHourResolutionTtl(unittest.TestCase):
    def setUp(self):
        self.led = _load_ledger()
        self._orig_env = dict(os.environ)
        os.environ["KAIZEN_LOOP_MAX_AGE_HOURS"] = "12"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)

    def _started_at(self, hours_ago: float) -> str:
        ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago)
        return ts.isoformat().replace("+00:00", "Z")

    def test_fresh_state_not_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = _seed_state(Path(tmp),
                                  started_at=self._started_at(hours_ago=1))
            fm, _ = self.led.split_frontmatter(state.read_text())
            stale, _ = self.led._is_stale(fm)
            self.assertFalse(stale, "1h-old state must NOT be stale")

    def test_hours_old_state_is_stale(self):
        """Bug repro — pre-fix, 24h-old state was not stale (default 30d).
        Post-fix, the hour-resolution check catches it at the 12h default."""
        with tempfile.TemporaryDirectory() as tmp:
            state = _seed_state(Path(tmp),
                                  started_at=self._started_at(hours_ago=24))
            fm, _ = self.led.split_frontmatter(state.read_text())
            stale, _age = self.led._is_stale(fm)
            self.assertTrue(stale, "24h-old state must be stale at threshold=12h")

    def test_env_knob_controls_threshold(self):
        os.environ["KAIZEN_LOOP_MAX_AGE_HOURS"] = "48"
        with tempfile.TemporaryDirectory() as tmp:
            state = _seed_state(Path(tmp),
                                  started_at=self._started_at(hours_ago=24))
            fm, _ = self.led.split_frontmatter(state.read_text())
            stale, _ = self.led._is_stale(fm)
            self.assertFalse(stale,
                              "24h-old must NOT be stale when threshold raised to 48h")

    def test_decide_returns_stale_action_when_old(self):
        """Full decide() pipeline returns complete-empty with mode='stale'."""
        with tempfile.TemporaryDirectory() as tmp:
            state = _seed_state(Path(tmp),
                                  started_at=self._started_at(hours_ago=24))
            out = self.led.decide(state, iteration=1)
            self.assertEqual(out["action"], "complete-empty")
            self.assertEqual(out["mode"], "stale")


# ─── #2 — session-boundary auto-archive ──────────────────────────────


class TestSessionBoundaryArchive(unittest.TestCase):
    """When the Stop hook fires in session B but the state file is
    pinned to session A, current behavior: silent `exit 0`. Fixed
    behavior: archive the orphan state under .kaizen/loops/archive/
    so the next loop starts clean."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _run_hook(self, payload: dict) -> tuple[int, str]:
        proc = subprocess.run(
            ["bash", str(_HOOK)], input=json.dumps(payload),
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(_KZ_DIR)},
        )
        return proc.returncode, proc.stdout

    def test_orphan_state_archived_not_silently_ignored(self):
        """Cross-session repro — state pinned to session A, hook fires
        in session B. Post-fix: state moved to archive dir, original
        removed."""
        # Fresh started_at so the new yaml-default 12h TTL doesn't fire first.
        fresh = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        _seed_state(self.cwd, session_id="session-A",
                     started_at=fresh)
        rc, _ = self._run_hook({
            "session_id": "session-B",
            "cwd": str(self.cwd),
            "transcript_path": "/tmp/t.jsonl",
            "last_assistant_message": "next turn",
        })
        self.assertEqual(rc, 0)
        # Original state file must be gone
        self.assertFalse(
            (self.cwd / ".kaizen/loop.state.md").exists(),
            "orphan state must be removed after archive",
        )
        # Archive must contain at least one file
        archive_dir = self.cwd / ".kaizen/loops/archive"
        self.assertTrue(archive_dir.is_dir(),
                         "archive dir must be created")
        archives = list(archive_dir.glob("*.md"))
        self.assertEqual(len(archives), 1,
                          f"expected 1 archived file, got {len(archives)}")
        # Archived content must include the original session_id
        self.assertIn("session-A", archives[0].read_text())

    def test_same_session_state_preserved(self):
        """Sanity — when session matches, state is NOT archived."""
        # Fresh started_at so the new yaml-default 12h TTL doesn't fire first.
        fresh = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        _seed_state(self.cwd, session_id="session-A",
                     started_at=fresh)
        self._run_hook({
            "session_id": "session-A",
            "cwd": str(self.cwd),
            "transcript_path": "/tmp/t.jsonl",
            "last_assistant_message": "same session",
        })
        self.assertTrue((self.cwd / ".kaizen/loop.state.md").exists(),
                         "same-session state must be preserved")


class TestSchemaYamlDrivenDefaults(unittest.TestCase):
    """Schema+yaml+json driven: automation.yaml ships defaults, env
    vars override. Schema validates the yaml shape."""

    def setUp(self):
        self._orig_env = dict(os.environ)
        # Wipe env overrides so we exercise the yaml-defaults path.
        for k in ("KAIZEN_LOOP_MAX_AGE_HOURS",
                   "KAIZEN_LOOP_MAX_AGE_DAYS",
                   "KAIZEN_LOOP_STUCK_ITERATIONS"):
            os.environ.pop(k, None)
        self.led = _load_ledger()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)

    def test_automation_yaml_loaded(self):
        """The yaml ships with the plugin; loader must produce a non-empty dict."""
        self.assertIsInstance(self.led._AUTOMATION, dict)
        self.assertEqual(self.led._AUTOMATION.get("version"), 1)
        self.assertIn("ttl", self.led._AUTOMATION)
        self.assertIn("stuck", self.led._AUTOMATION)
        self.assertIn("session_boundary", self.led._AUTOMATION)

    def test_yaml_default_hours_is_null_opt_in(self):
        """Yaml ships with hour-TTL DISABLED (opt-in). Users enable
        either via env knob or by editing automation.yaml. This keeps
        the long-running loop use-case unbroken by default."""
        self.assertIsNone(self.led._max_age_hours())

    def test_yaml_default_stuck_iterations_is_5(self):
        self.assertEqual(self.led._stuck_iterations(), 5)

    def test_env_overrides_yaml(self):
        """3-tier resolution: env > yaml > hardcoded. Setting env wins."""
        os.environ["KAIZEN_LOOP_MAX_AGE_HOURS"] = "48"
        # Reload to clear cached env-vs-yaml state (functions read env on every call).
        self.assertEqual(self.led._max_age_hours(), 48)
        os.environ["KAIZEN_LOOP_STUCK_ITERATIONS"] = "10"
        self.assertEqual(self.led._stuck_iterations(), 10)

    def test_schema_validates_shipped_yaml(self):
        """JSON Schema for automation.yaml exists + the shipped yaml conforms."""
        schema_path = _KZ_DIR / "skills/loop/domain/schemas/automation.schema.json"
        self.assertTrue(schema_path.is_file(),
                         f"missing schema: {schema_path}")
        schema = json.loads(schema_path.read_text())
        self.assertEqual(schema["title"], "kaizen loop-automation")
        # Required fields per schema
        for req in schema["required"]:
            self.assertIn(req, self.led._AUTOMATION,
                           f"shipped yaml missing required field: {req}")
        # Enum check: on_mismatch must be one of {archive,delete,silent}
        on_mismatch = self.led._AUTOMATION["session_boundary"]["on_mismatch"]
        allowed = schema["properties"]["session_boundary"]["properties"]["on_mismatch"]["enum"]
        self.assertIn(on_mismatch, allowed)


if __name__ == "__main__":
    unittest.main()
