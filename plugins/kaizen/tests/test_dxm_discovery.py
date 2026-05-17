"""Tests for dxm session-id discovery + multi-hop chain walk + agent_id capture.

Three additions to the kaizen-dxm CLI:
- `session-id` — autodiscover active session_id from cwd → slug → latest JSONL
- `chain --session SID` — walk parent_session_id back to root
- agent_id captured from sub-agent events (hook script + capture)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
_DXM_PY = _SCRIPTS / "dxm.py"
_HOOK = _KZ_DIR / "hooks/claude/dxm-event.sh"


class DiscoveryBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Fake HOME so cwd→slug points into our tempdir
        self.fake_home = self.tmp / "home"
        self.fake_home.mkdir()
        self._orig_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.fake_home)

        self.dxm_dir = self.tmp / "dxm"
        self._orig_dxm = os.environ.get("KAIZEN_DXM_DIR")
        os.environ["KAIZEN_DXM_DIR"] = str(self.dxm_dir)

    def tearDown(self):
        self._tmp.cleanup()
        for var, orig in (("HOME", self._orig_home),
                           ("KAIZEN_DXM_DIR", self._orig_dxm)):
            if orig is None: os.environ.pop(var, None)
            else: os.environ[var] = orig

    def _run(self, *args: str, cwd=None, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_DXM_PY), *args],
            input=stdin, capture_output=True, text=True, timeout=15,
            cwd=str(cwd) if cwd else None,
            env=os.environ.copy(),
        )


# ─── session-id discovery ────────────────────────────────────────────


class TestSessionId(DiscoveryBase):
    def _make_project(self, cwd: Path, sessions: list[str]):
        """Seed fake ~/.claude/projects/<slug>/<sid>.jsonl files."""
        slug = str(cwd.resolve()).replace("/", "-")
        proj_dir = self.fake_home / ".claude" / "projects" / slug
        proj_dir.mkdir(parents=True)
        for i, sid in enumerate(sessions):
            p = proj_dir / f"{sid}.jsonl"
            p.write_text("{}\n")
            time.sleep(0.01)  # ensure distinct mtimes
        return proj_dir

    def test_returns_latest_session_jsonl_filename_minus_ext(self):
        cwd = self.tmp / "project"
        cwd.mkdir()
        self._make_project(cwd, ["sess-old", "sess-new"])
        r = self._run("session-id", "--json", cwd=cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["session_id"], "sess-new")

    def test_explicit_cwd_flag_overrides(self):
        cwd = self.tmp / "actual"
        cwd.mkdir()
        self._make_project(cwd, ["sess-z"])
        # Invoke from a different cwd, pass --cwd
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        r = self._run("session-id", "--cwd", str(cwd), "--json",
                       cwd=elsewhere)
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["session_id"], "sess-z")

    def test_no_project_dir_returns_null(self):
        cwd = self.tmp / "no-project"
        cwd.mkdir()
        # No ~/.claude/projects/<slug>/ at all
        r = self._run("session-id", "--json", cwd=cwd)
        env = json.loads(r.stdout)
        self.assertIsNone(env["data"]["session_id"])

    def test_empty_project_dir_returns_null(self):
        cwd = self.tmp / "empty-proj"
        cwd.mkdir()
        slug = str(cwd.resolve()).replace("/", "-")
        (self.fake_home / ".claude" / "projects" / slug).mkdir(parents=True)
        # No .jsonl files
        r = self._run("session-id", "--json", cwd=cwd)
        env = json.loads(r.stdout)
        self.assertIsNone(env["data"]["session_id"])

    def test_envelope_carries_jsonl_path_when_found(self):
        cwd = self.tmp / "p2"
        cwd.mkdir()
        self._make_project(cwd, ["sess-a"])
        r = self._run("session-id", "--json", cwd=cwd)
        env = json.loads(r.stdout)
        self.assertIn("jsonl_path", env["data"])
        self.assertTrue(env["data"]["jsonl_path"].endswith("sess-a.jsonl"))


# ─── chain walk ──────────────────────────────────────────────────────


class TestChain(DiscoveryBase):
    def _link(self, parent: str, child: str):
        self._run("link", "--parent", parent, "--child", child)

    def test_single_hop_chain(self):
        self._link("A", "B")
        r = self._run("chain", "--session", "B", "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["chain"], ["A", "B"])

    def test_multi_hop_chain_walks_to_root(self):
        self._link("A", "B")
        self._link("B", "C")
        self._link("C", "D")
        r = self._run("chain", "--session", "D", "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["chain"], ["A", "B", "C", "D"])

    def test_unlinked_session_returns_single_element_chain(self):
        r = self._run("chain", "--session", "lonely", "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["chain"], ["lonely"])

    def test_chain_max_depth_caps_walk(self):
        # Cycle protection: if A→B and B→A, chain bails out
        self._link("X", "Y")
        self._link("Y", "X")
        r = self._run("chain", "--session", "X", "--max-depth", "5", "--json")
        env = json.loads(r.stdout)
        # Result is bounded — won't loop forever
        self.assertLessEqual(len(env["data"]["chain"]), 6)

    def test_chain_envelope_carries_depth_and_truncated(self):
        self._link("A", "B")
        r = self._run("chain", "--session", "B", "--json")
        env = json.loads(r.stdout)
        self.assertIn("depth", env["data"])
        self.assertIn("truncated", env["data"])
        self.assertFalse(env["data"]["truncated"])
        self.assertEqual(env["data"]["depth"], 2)


# ─── agent_id capture (hook + dxm.py) ────────────────────────────────


class TestAgentIdCapture(DiscoveryBase):
    def test_hook_captures_agent_id_when_present(self):
        # Feed event with agent_id (sub-agent context) through the hook
        event = {
            "session_id": "parent-sess",
            "tool_name": "Bash",
            "tool_use_id": "toolu_inner",
            "agent_id": "agent-abc123",
        }
        r = subprocess.run(
            ["bash", str(_HOOK), "PreToolUse"],
            input=json.dumps(event), capture_output=True, text=True,
            timeout=5, env=os.environ.copy(),
        )
        self.assertEqual(r.returncode, 0)
        events_file = self.dxm_dir / "events-parent-sess.jsonl"
        self.assertTrue(events_file.is_file())
        line = events_file.read_text().strip().splitlines()[-1]
        rec = json.loads(line)
        self.assertEqual(rec.get("agent_id"), "agent-abc123")

    def test_hook_omits_agent_id_when_absent(self):
        event = {"session_id": "ps2", "tool_name": "Bash"}
        subprocess.run(
            ["bash", str(_HOOK), "PreToolUse"],
            input=json.dumps(event), capture_output=True, text=True,
            timeout=5, env=os.environ.copy(),
        )
        rec = json.loads(
            (self.dxm_dir / "events-ps2.jsonl").read_text().strip().splitlines()[-1])
        self.assertNotIn("agent_id", rec)


# ─── tail --agent filter ─────────────────────────────────────────────


class TestTailAgentFilter(DiscoveryBase):
    def test_tail_filters_to_one_agent(self):
        # Seed events: 2 for agent-X, 1 for agent-Y, 1 with no agent
        for agent in ("X", "X", "Y", None):
            evt = {"session_id": "s", "evt_type": "PreToolUse",
                    "tool_name": "Bash"}
            if agent: evt["agent_id"] = f"agent-{agent}"
            self._run("capture", stdin=json.dumps(evt))
            time.sleep(0.005)
        r = self._run("tail", "--session", "s", "--agent", "agent-X", "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["count"], 2)
        self.assertTrue(all(e.get("agent_id") == "agent-X"
                              for e in env["data"]["events"]))


# ─── Help ────────────────────────────────────────────────────────────


class TestHelp(unittest.TestCase):
    def test_session_id_help_works(self):
        r = subprocess.run([sys.executable, str(_DXM_PY), "session-id", "--help"],
                            capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0)

    def test_chain_help_works(self):
        r = subprocess.run([sys.executable, str(_DXM_PY), "chain", "--help"],
                            capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
