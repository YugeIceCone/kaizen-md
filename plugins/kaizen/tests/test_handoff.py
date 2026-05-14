"""Tests for the handoff feature — _handoff.py core + handoff.py CLI.

The handoff store + YAML dir are sandboxed via KAIZEN_HANDOFF_DB and
KAIZEN_HANDOFF_DIR so tests never touch the real ~/.claude/.
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
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))

import _handoff  # noqa: E402
import handoff as handoff_cli  # noqa: E402


_SAMPLE_HANDOFF = """\
---
session: test-sess
date: 2026-05-14
status: complete
outcome: SUCCEEDED
---

goal: built the thing
now: ship it
done_this_session:
  - task: wrote code
    files: [a.py]

decisions:
  - separate-store: handoff stays standalone, not merged into brain
  - upsert-on-path: re-saving a handoff updates the row, no duplicates

findings:
  - the-real-bug: stores.py was never shipped with the plugin

worked:
  - discovery-first before any destructive sweep

failed:
  - a blanket -name build delete would have nuked Rust source

next:
  - wire the handoff to brain bridge
blockers: []
"""


class SandboxBase(unittest.TestCase):
    """Sandboxes the handoff DB + YAML dir into a temp dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.db = root / "handoff.db"
        self.ydir = root / "handoffs"
        self.ydir.mkdir()
        self._orig = {
            "KAIZEN_HANDOFF_DB": os.environ.get("KAIZEN_HANDOFF_DB"),
            "KAIZEN_HANDOFF_DIR": os.environ.get("KAIZEN_HANDOFF_DIR"),
        }
        os.environ["KAIZEN_HANDOFF_DB"] = str(self.db)
        os.environ["KAIZEN_HANDOFF_DIR"] = str(self.ydir)

    def tearDown(self):
        self._tmp.cleanup()
        for k, v in self._orig.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _write_yaml(self, name: str, body: str = "goal: x\nnow: y\n") -> Path:
        p = self.ydir / name
        p.write_text(body, encoding="utf-8")
        return p


class TestModuleAndDomain(unittest.TestCase):
    def test_modules_parse(self):
        for mod in ("_handoff.py", "handoff.py"):
            path = _KZ_DIR / "skills/workflow/scripts" / mod
            compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_domain_yaml_loads(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        import yaml
        d = yaml.safe_load(
            (_KZ_DIR / "skills/handoff/domain/handoff.yaml").read_text())
        self.assertEqual(d["version"], 1)
        self.assertEqual(tuple(d["status"]), _handoff.VALID_STATUS)
        self.assertIn("SUCCEEDED", d["outcome"])
        self.assertIn("IN_PROGRESS", d["outcome"])

    def test_record_schema_valid(self):
        s = json.loads(
            (_KZ_DIR / "skills/handoff/domain/schemas/handoff-record.schema.json")
            .read_text())
        self.assertEqual(
            s["required"],
            ["id", "session_id", "created_at", "file_path", "status"])
        self.assertFalse(s["additionalProperties"])


class TestPaths(SandboxBase):
    def test_db_path_env_override(self):
        self.assertEqual(_handoff.handoff_db_path(), self.db)

    def test_dir_env_override(self):
        self.assertEqual(_handoff.handoffs_dir(), self.ydir)

    def test_now_iso_shape(self):
        ts = _handoff.now_iso()
        self.assertTrue(ts.endswith("Z"))
        self.assertIn("T", ts)


class TestStore(SandboxBase):
    def test_save_inserts_and_returns_id(self):
        f = self._write_yaml("h1.yaml")
        rid = _handoff.save_handoff("sess-a", f.read_text(), str(f))
        self.assertIsInstance(rid, int)
        rows = _handoff.latest_handoffs(1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["session_id"], "sess-a")
        self.assertEqual(rows[0]["status"], "partial")

    def test_save_upserts_on_file_path(self):
        f = self._write_yaml("h1.yaml", "goal: original\n")
        rid1 = _handoff.save_handoff("sess-a", "goal: original\n", str(f))
        rid2 = _handoff.save_handoff(
            "sess-a", "goal: updated\n", str(f), status="complete")
        self.assertEqual(rid1, rid2)  # same row, not a duplicate
        rows = _handoff.list_handoffs()
        self.assertEqual(len(rows), 1)
        latest = _handoff.latest_handoffs(1)[0]
        self.assertEqual(latest["status"], "complete")
        self.assertIn("updated", latest["content"])

    def test_save_bad_status_coerced(self):
        f = self._write_yaml("h1.yaml")
        _handoff.save_handoff("s", f.read_text(), str(f), status="weird")
        self.assertEqual(_handoff.latest_handoffs(1)[0]["status"], "partial")

    def test_save_empty_file_path_raises(self):
        with self.assertRaises(ValueError):
            _handoff.save_handoff("s", "content", "")

    def test_latest_empty_when_no_db(self):
        # Nothing saved yet — must return [] not raise.
        self.assertEqual(_handoff.latest_handoffs(1), [])
        self.assertEqual(_handoff.list_handoffs(), [])

    def test_latest_returns_newest(self):
        import time
        f1 = self._write_yaml("h1.yaml")
        _handoff.save_handoff("sess-a", "first", str(f1))
        time.sleep(0.01)
        f2 = self._write_yaml("h2.yaml")
        rid2 = _handoff.save_handoff("sess-b", "second", str(f2))
        latest = _handoff.latest_handoffs(1)
        self.assertEqual(latest[0]["id"], rid2)
        self.assertEqual(latest[0]["session_id"], "sess-b")

    def test_list_session_filter(self):
        fa = self._write_yaml("a.yaml")
        fb = self._write_yaml("b.yaml")
        _handoff.save_handoff("proj-a", "x", str(fa))
        _handoff.save_handoff("proj-b", "y", str(fb))
        self.assertEqual(len(_handoff.list_handoffs()), 2)
        only_a = _handoff.list_handoffs(session_id="proj-a")
        self.assertEqual(len(only_a), 1)
        self.assertEqual(only_a[0]["session_id"], "proj-a")
        # list output is metadata-only — no `content` key
        self.assertNotIn("content", only_a[0])


class TestBridge(unittest.TestCase):
    """extract_brain_candidates is pure — no sandbox needed."""

    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")

    def test_pulls_only_durable_sections(self):
        cands = _handoff.extract_brain_candidates(_SAMPLE_HANDOFF)
        # 2 decisions + 1 finding + 1 worked + 1 failed = 5
        self.assertEqual(len(cands), 5)
        sections = sorted(c["section"] for c in cands)
        self.assertEqual(
            sections, ["decisions", "decisions", "failed", "findings", "worked"])

    def test_skips_ephemeral_sections(self):
        blob = " ".join(
            c["text"] for c in _handoff.extract_brain_candidates(_SAMPLE_HANDOFF))
        # session-state must NOT leak into brain candidates
        for ephemeral in ("built the thing", "ship it", "wrote code",
                          "wire the handoff"):
            self.assertNotIn(ephemeral, blob)
        # but durable learnings must be present
        self.assertIn("handoff stays standalone", blob)
        self.assertIn("stores.py was never shipped", blob)

    def test_dict_items_normalised(self):
        cands = _handoff.extract_brain_candidates(_SAMPLE_HANDOFF)
        dec = [c for c in cands if c["section"] == "decisions"][0]
        # single-key dict -> "name: detail"
        self.assertIn(":", dec["text"])
        self.assertTrue(dec["text"].startswith("separate-store"))

    def test_empty_when_no_learning_sections(self):
        bare = "---\nsession: x\n---\n\ngoal: just a goal\nnow: nothing durable\n"
        self.assertEqual(_handoff.extract_brain_candidates(bare), [])

    def test_bad_yaml_returns_empty_not_raise(self):
        self.assertEqual(
            _handoff.extract_brain_candidates("::: not : valid : yaml :::"), [])

    def test_strip_frontmatter(self):
        body = _handoff._strip_frontmatter(_SAMPLE_HANDOFF)
        self.assertFalse(body.lstrip().startswith("---"))
        self.assertIn("goal: built the thing", body)
        self.assertNotIn("session: test-sess", body)


class TestCli(SandboxBase):
    def _run(self, *args):
        script = _KZ_DIR / "skills/workflow/scripts/handoff.py"
        return subprocess.run(
            ["python3", str(script), *args],
            capture_output=True, text=True, timeout=30,
            env={**os.environ},
        )

    def test_path_subcommand(self):
        r = self._run("path")
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertEqual(out["db"], str(self.db))
        self.assertEqual(out["yaml_dir"], str(self.ydir))

    def test_save_then_latest(self):
        f = self._write_yaml("cli.yaml", "goal: cli test\n")
        r = self._run("save", "--session", "cli-sess", "--file", str(f),
                      "--status", "complete", "--json")
        self.assertEqual(r.returncode, 0)
        saved = json.loads(r.stdout)
        self.assertEqual(saved["session_id"], "cli-sess")
        r2 = self._run("latest", "--json")
        self.assertEqual(r2.returncode, 0)
        h = json.loads(r2.stdout)["handoff"]
        self.assertEqual(h["session_id"], "cli-sess")
        self.assertEqual(h["status"], "complete")
        self.assertIn("cli test", h["content"])

    def test_save_missing_file_exits_1(self):
        r = self._run("save", "--session", "s", "--file", "/nonexistent/x.yaml")
        self.assertEqual(r.returncode, 1)
        self.assertIn("error", json.loads(r.stdout))

    def test_latest_empty_exits_0(self):
        r = self._run("latest", "--json")
        self.assertEqual(r.returncode, 0)
        self.assertIsNone(json.loads(r.stdout)["handoff"])

    def test_bare_invocation_is_latest(self):
        r = self._run()
        self.assertEqual(r.returncode, 0)
        self.assertIn("no handoffs", r.stdout)

    def test_bridge_lists_candidates(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        f = self._write_yaml("bridge.yaml", _SAMPLE_HANDOFF)
        r = self._run("bridge", "--file", str(f), "--json")
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertEqual(out["count"], 5)
        self.assertEqual(len(out["candidates"]), 5)
        self.assertIn("section", out["candidates"][0])

    def test_bridge_missing_file_exits_1(self):
        r = self._run("bridge", "--file", "/nonexistent/h.yaml")
        self.assertEqual(r.returncode, 1)
        self.assertIn("error", json.loads(r.stdout))

    def test_bridge_no_learnings_is_count_zero(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        f = self._write_yaml("bare.yaml", "---\nsession: x\n---\n\ngoal: g\nnow: n\n")
        r = self._run("bridge", "--file", str(f), "--json")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)["count"], 0)


if __name__ == "__main__":
    unittest.main()
