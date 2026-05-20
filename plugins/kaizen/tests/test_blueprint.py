"""Tests for scripts/util/blueprint.py — one-shot planning-blueprint creator.

Surface:
    kaizen-blueprint create [--project SLUG] [--out FILE] [--summary S]
        [--plan T]... [--research T]... [--task-list T]... [--spec T]...
        [--decision T]... [--idea T]... [--note T]... [--audit T]...
        [--brainstorm T]... [--guide T]...                       (aliases note)
        [--no-session-meta] [--no-auto-link] [--json]

Each --<kind> flag is repeatable. Items get sequential ids (01, 02, ...).
First item is the root; subsequent items auto-link via parents=[01] +
the root's children list. Session_meta auto-derived from git + the
most-recent CC JSONL; skip with --no-session-meta.

Output matches `templates/planning-blueprint/blueprint.schema.json`.
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
_SCRIPT = _KZ_DIR / "scripts/util/blueprint.py"


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Bare git repo so session_meta git probes don't die
        subprocess.run(["git", "init", "-q"], cwd=str(self.tmp), check=True,
                        capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"],
                        cwd=str(self.tmp), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "t"],
                        cwd=str(self.tmp), check=True, capture_output=True)
        (self.tmp / "README.md").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=str(self.tmp),
                        check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"],
                        cwd=str(self.tmp), check=True, capture_output=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_SCRIPT), "create", *args],
            capture_output=True, text=True, timeout=15,
            cwd=str(self.tmp), env={**os.environ},
        )


class TestSkeletonFromOnePlan(_Base):
    def test_single_plan_produces_one_item(self):
        r = self._run("--project", "demo", "--plan", "Ship X",
                       "--no-session-meta")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["project"], "demo")
        self.assertEqual(len(d["items"]), 1)
        self.assertEqual(d["items"][0]["id"], "01")
        self.assertEqual(d["items"][0]["kind"], "plan")
        self.assertEqual(d["items"][0]["title"], "Ship X")
        self.assertEqual(d["items"][0]["status"], "draft")


class TestMultipleKindsSequentialIds(_Base):
    def test_kinds_get_sequential_ids_in_argv_order(self):
        r = self._run(
            "--project", "demo",
            "--plan", "P1",
            "--research", "R1",
            "--task-list", "T1",
            "--idea", "I1",
            "--note", "N1",
            "--no-session-meta",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual([i["id"] for i in d["items"]],
                          ["01", "02", "03", "04", "05"])
        self.assertEqual([i["kind"] for i in d["items"]],
                          ["plan", "research", "task-list", "idea", "note"])


class TestAutoLinkRootToChildren(_Base):
    def test_first_item_is_root_others_link_to_it(self):
        r = self._run(
            "--project", "demo",
            "--plan", "Root",
            "--research", "Child A",
            "--idea", "Child B",
            "--no-session-meta",
        )
        d = json.loads(r.stdout)
        root, c1, c2 = d["items"]
        self.assertEqual(root["links"]["parents"], [])
        self.assertEqual(root["links"]["children"], ["02", "03"])
        self.assertEqual(c1["links"]["parents"], ["01"])
        self.assertEqual(c2["links"]["parents"], ["01"])

    def test_no_auto_link_keeps_links_empty(self):
        r = self._run(
            "--project", "demo",
            "--plan", "Root",
            "--idea", "Solo",
            "--no-auto-link",
            "--no-session-meta",
        )
        d = json.loads(r.stdout)
        for item in d["items"]:
            self.assertEqual(item["links"]["parents"], [])
            self.assertEqual(item["links"]["children"], [])


class TestSessionMetaDerivation(_Base):
    def test_session_meta_present_by_default_with_git_head(self):
        r = self._run("--project", "demo", "--plan", "Ship X")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertIn("session_meta", d)
        meta = d["session_meta"]
        self.assertIn("head_at_generation", meta)
        # the init commit's HEAD is in head_at_generation under the project key
        self.assertIn("demo", meta["head_at_generation"])
        self.assertRegex(meta["head_at_generation"]["demo"], r"^[a-f0-9]{7,40}$")
        self.assertEqual(meta["primary_branch"].get("demo"), "master")
        self.assertEqual(meta["author"], "agent")
        self.assertEqual(meta["producer_tool"], "kaizen-blueprint")

    def test_no_session_meta_skips_block_entirely(self):
        r = self._run("--project", "demo", "--plan", "Ship X",
                       "--no-session-meta")
        d = json.loads(r.stdout)
        self.assertNotIn("session_meta", d)


class TestGuideAliasMapsToNote(_Base):
    def test_guide_kind_becomes_note_with_guide_tag(self):
        r = self._run(
            "--project", "demo",
            "--guide", "How to dispatch",
            "--no-session-meta",
        )
        d = json.loads(r.stdout)
        self.assertEqual(d["items"][0]["kind"], "note")
        self.assertIn("guide", d["items"][0]["tags"])


class TestOutFileWritesJson(_Base):
    def test_out_file_writes_atomically(self):
        out = self.tmp / "blueprint.json"
        r = self._run(
            "--project", "demo",
            "--plan", "P",
            "--no-session-meta",
            "--out", str(out),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(out.is_file())
        d = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(d["items"][0]["title"], "P")


class TestNothingSpecifiedErrors(_Base):
    def test_no_items_exits_2(self):
        r = self._run("--project", "demo", "--no-session-meta")
        self.assertEqual(r.returncode, 2)
        self.assertIn("at least one", r.stderr.lower())


if __name__ == "__main__":
    unittest.main()
