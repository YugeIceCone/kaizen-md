"""Tests for BK-010 — handoff ↔ dxm integration loops.

Three integration points:
- scaffold: mined_summary.dxm_event_count surfaces live dxm count
- verify:   data.recent_tool_churn surfaces last-60s tool counts
- auto-finalize: --parent-session flag calls kaizen-dxm link

All integrations are best-effort — if dxm dir is empty or env knob
disables, fields are present with sensible empty/null values.
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
_HANDOFF_PY = _SCRIPTS / "handoff.py"
_DXM_PY = _SCRIPTS / "dxm.py"


class IntegrationBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

        self.fake_home = self.tmp / "home"
        self.fake_home.mkdir()

        self.handoffs_dir = self.tmp / "handoffs"
        self.handoffs_dir.mkdir()

        self.dxm_dir = self.tmp / "dxm"
        self.dxm_dir.mkdir()

        # Sandbox env
        self._orig: dict[str, str | None] = {}
        for k, v in (
            ("HOME", str(self.fake_home)),
            ("KAIZEN_HANDOFF_DIR", str(self.handoffs_dir)),
            ("KAIZEN_HANDOFF_DB", str(self.tmp / "handoff.db")),
            ("KAIZEN_DXM_DIR", str(self.dxm_dir)),
        ):
            self._orig[k] = os.environ.get(k)
            os.environ[k] = v

    def tearDown(self):
        self._tmp.cleanup()
        for k, orig in self._orig.items():
            if orig is None: os.environ.pop(k, None)
            else: os.environ[k] = orig

    def _dxm(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_DXM_PY), *args],
            input=stdin, capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )

    def _handoff(self, *args: str, cwd=None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_HANDOFF_PY), *args],
            capture_output=True, text=True, timeout=30,
            cwd=str(cwd) if cwd else None,
            env=os.environ.copy(),
        )

    def _make_repo(self) -> Path:
        repo = self.tmp / "repo"
        repo.mkdir()
        for cmd in (["git", "init", "-q"],
                     ["git", "config", "user.email", "t@t"],
                     ["git", "config", "user.name", "t"]):
            subprocess.run(cmd, cwd=str(repo), check=True, capture_output=True)
        (repo / "x").write_text("1")
        subprocess.run(["git", "add", "x"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=str(repo),
                        check=True, capture_output=True)
        return repo


# ─── scaffold surfaces dxm event count ───────────────────────────────


class TestScaffoldDxmIntegration(IntegrationBase):
    def test_mined_summary_carries_dxm_event_count(self):
        repo = self._make_repo()
        # Seed CC JSONL so scaffold can mine it
        slug = str(repo.resolve()).replace("/", "-")
        proj = self.fake_home / ".claude" / "projects" / slug
        proj.mkdir(parents=True)
        sid = "sess-int"
        (proj / f"{sid}.jsonl").write_text(json.dumps({
            "type": "ai-title", "aiTitle": "test goal"}) + "\n")
        # Seed dxm with 3 events for this session
        for i in range(3):
            self._dxm("capture", stdin=json.dumps({
                "session_id": sid, "evt_type": "PreToolUse",
                "tool_name": "Bash"}))
            time.sleep(0.005)

        r = self._handoff(
            "scaffold", "--session", "sess-int",
            "--goal", "g", "--now", "n",
            "--at", "2026-05-17_05-00", "--json",
            cwd=repo,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        ms = env["data"].get("mined_summary", {})
        # New field: dxm_event_count
        self.assertIn("dxm_event_count", ms,
                       f"missing dxm_event_count in mined_summary: {ms}")
        self.assertEqual(ms["dxm_event_count"], 3)

    def test_no_dxm_data_is_zero_not_error(self):
        """When no dxm events exist for the session, scaffold still
        reports cleanly with dxm_event_count = 0."""
        repo = self._make_repo()
        slug = str(repo.resolve()).replace("/", "-")
        proj = self.fake_home / ".claude" / "projects" / slug
        proj.mkdir(parents=True)
        (proj / "sess-empty.jsonl").write_text("{}\n")
        r = self._handoff(
            "scaffold", "--session", "sess-empty",
            "--goal", "g", "--now", "n",
            "--at", "2026-05-17_05-00", "--json",
            cwd=repo,
        )
        env = json.loads(r.stdout)
        ms = env["data"].get("mined_summary", {})
        self.assertEqual(ms.get("dxm_event_count"), 0)


# ─── verify surfaces dxm recent-churn ────────────────────────────────


def _make_handoff_yaml(date: str = "2026-05-17") -> str:
    return (
        "---\n"
        f"session: test-verify\ndate: {date}\n"
        "status: complete\noutcome: SUCCEEDED\n---\n\n"
        "goal: g\nnow: n\ntest: noop\n\n"
        "done_this_session: []\n"
        "blockers: []\nquestions: []\ndecisions: []\nfindings: []\n"
        "worked: []\nfailed: []\nnext: []\n"
        "files:\n  created: []\n  modified: []\n"
    )


class TestVerifyDxmIntegration(IntegrationBase):
    def test_verify_envelope_carries_recent_tool_churn(self):
        repo = self._make_repo()
        # Write a handoff YAML
        yaml = self.tmp / "h.yaml"
        yaml.write_text(_make_handoff_yaml())
        # Seed dxm with recent tool activity
        sid = "sess-vfy"
        for tool in ("Bash", "Bash", "Edit", "Bash"):
            self._dxm("capture", stdin=json.dumps({
                "session_id": sid, "evt_type": "PreToolUse",
                "tool_name": tool}))
            time.sleep(0.005)

        r = self._handoff(
            "verify", "--file", str(yaml),
            "--dxm-session", sid, "--json",
            cwd=repo,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        churn = env["data"].get("recent_tool_churn")
        self.assertIsNotNone(churn,
                              f"missing recent_tool_churn in envelope.data; got {list(env['data'].keys())}")
        self.assertEqual(churn.get("Bash"), 3)
        self.assertEqual(churn.get("Edit"), 1)

    def test_verify_without_dxm_session_omits_churn_field(self):
        """When --dxm-session not passed, recent_tool_churn is omitted."""
        repo = self._make_repo()
        yaml = self.tmp / "h.yaml"
        yaml.write_text(_make_handoff_yaml())
        r = self._handoff("verify", "--file", str(yaml), "--json", cwd=repo)
        env = json.loads(r.stdout)
        # Field absent → mining wasn't asked for
        self.assertNotIn("recent_tool_churn", env["data"])


# ─── auto-finalize records lineage ───────────────────────────────────


_PLACEHOLDER_YAML = textwrap.dedent("""\
    ---
    session: sess-fin
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


class TestAutoFinalizeDxmLink(IntegrationBase):
    def test_parent_session_flag_creates_dxm_link(self):
        # Write YAML inside a session-named dir so fp.parent.name resolves
        # to the expected session_id (matches the handoff skill convention).
        sess_dir = self.handoffs_dir / "sess-fin"
        sess_dir.mkdir()
        yaml = sess_dir / "f.yaml"
        yaml.write_text(_PLACEHOLDER_YAML)
        r = self._handoff(
            "auto-finalize", "--file", str(yaml),
            "--outcome", "SUCCEEDED",
            "--parent-session", "prev-sess-xyz",
            "--json",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        # sessions.jsonl should now have the link record
        sessions = self.dxm_dir / "sessions.jsonl"
        self.assertTrue(sessions.is_file(),
                          f"sessions.jsonl not created: {self.dxm_dir.iterdir()}")
        records = [json.loads(l) for l in sessions.read_text().splitlines() if l.strip()]
        link = records[-1]
        self.assertEqual(link["parent_session_id"], "prev-sess-xyz")
        # Child = sess-fin (the handoff's session name)
        self.assertEqual(link["child_session_id"], "sess-fin")

    def test_without_parent_session_no_link_created(self):
        sess_dir = self.handoffs_dir / "sess-no-parent"
        sess_dir.mkdir()
        yaml = sess_dir / "f2.yaml"
        yaml.write_text(_PLACEHOLDER_YAML)
        r = self._handoff(
            "auto-finalize", "--file", str(yaml),
            "--outcome", "SUCCEEDED",
            "--json",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        sessions = self.dxm_dir / "sessions.jsonl"
        self.assertFalse(sessions.is_file())


if __name__ == "__main__":
    unittest.main()
