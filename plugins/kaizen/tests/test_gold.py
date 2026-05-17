"""Tests for kaizen-gold — incidental-discovery + learnings tracker."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "skills/workflow/scripts/gold.py"


class GoldBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.store = self.tmp / "gold.jsonl"
        self.env = {"KAIZEN_GOLD_FILE": str(self.store)}

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_SCRIPT), *args],
            capture_output=True, text=True, timeout=5,
            env={**os.environ, **self.env},
        )


class TestCapture(GoldBase):
    def test_capture_creates_entry_with_id_1(self):
        r = self._run("capture", "first pattern", "--tag", "test", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = json.loads(r.stdout)
        self.assertEqual(rec["id"], 1)
        self.assertEqual(rec["tag"], "test")
        self.assertEqual(rec["pattern"], "first pattern")
        self.assertFalse(rec["promoted"])

    def test_subsequent_ids_increment(self):
        self._run("capture", "first")
        self._run("capture", "second")
        self._run("capture", "third", "--json")
        recs = [json.loads(l) for l in self.store.read_text().strip().splitlines()]
        self.assertEqual([r["id"] for r in recs], [1, 2, 3])

    def test_capture_persists_to_jsonl(self):
        self._run("capture", "persisted",
                   "--source", "skills/x.py:42", "--learned", "from bug")
        self.assertTrue(self.store.is_file())
        rec = json.loads(self.store.read_text().strip())
        self.assertEqual(rec["source"], "skills/x.py:42")
        self.assertEqual(rec["learned"], "from bug")


class TestList(GoldBase):
    def test_list_empty_returns_no_entries(self):
        r = self._run("list")
        self.assertIn("no entries", r.stdout)

    def test_list_after_capture(self):
        self._run("capture", "alpha", "--tag", "X")
        self._run("capture", "beta", "--tag", "Y")
        r = self._run("list")
        self.assertIn("alpha", r.stdout)
        self.assertIn("beta", r.stdout)

    def test_list_tag_filter(self):
        self._run("capture", "alpha", "--tag", "keep")
        self._run("capture", "beta", "--tag", "drop")
        r = self._run("list", "--tag", "keep")
        self.assertIn("alpha", r.stdout)
        self.assertNotIn("beta", r.stdout)

    def test_list_unpromoted_filter(self):
        self._run("capture", "alpha")
        self._run("capture", "beta")
        # promote one
        target = self.tmp / "target.md"
        self._run("promote", "1", "--to", str(target))
        # unpromoted should only show beta
        r = self._run("list", "--unpromoted", "--json")
        recs = json.loads(r.stdout)
        ids = [r["id"] for r in recs]
        self.assertEqual(ids, [2])


class TestShow(GoldBase):
    def test_show_existing(self):
        self._run("capture", "specific pattern")
        r = self._run("show", "1", "--json")
        rec = json.loads(r.stdout)
        self.assertEqual(rec["pattern"], "specific pattern")

    def test_show_missing_exits_1(self):
        r = self._run("show", "999")
        self.assertEqual(r.returncode, 1)


class TestPromote(GoldBase):
    def test_promote_appends_and_marks(self):
        self._run("capture", "important pattern", "--tag", "T")
        target = self.tmp / "rules.md"
        r = self._run("promote", "1", "--to", str(target))
        self.assertEqual(r.returncode, 0, r.stderr)
        # Target file got the gold line
        self.assertTrue(target.is_file())
        body = target.read_text()
        self.assertIn("[gold #1]", body)
        self.assertIn("important pattern", body)
        # Source record marked promoted
        rec = json.loads(self.store.read_text().strip().splitlines()[0])
        self.assertTrue(rec["promoted"])
        self.assertEqual(rec["promoted_to"], str(target))
        self.assertIn("promoted_at", rec)

    def test_promote_with_note_appended(self):
        self._run("capture", "p")
        target = self.tmp / "out.md"
        self._run("promote", "1", "--to", str(target), "--note", "context here")
        self.assertIn("(context here)", target.read_text())

    def test_promote_already_promoted_exits_1(self):
        self._run("capture", "p")
        target = self.tmp / "out.md"
        self._run("promote", "1", "--to", str(target))
        r = self._run("promote", "1", "--to", str(target))
        self.assertEqual(r.returncode, 1)

    def test_promote_missing_id_exits_1(self):
        r = self._run("promote", "999", "--to", "/tmp/x.md")
        self.assertEqual(r.returncode, 1)


class TestPromoteBrain(GoldBase):
    """`promote --brain` creates a Note file with proper frontmatter
    when the target doesn't exist. Existing-file path stays append."""

    def test_brain_creates_note_with_frontmatter(self):
        self._run("capture", "pattern that became a belief",
                   "--tag", "skill-routing",
                   "--source", "skills/skill-suggest/SKILL.md",
                   "--learned", "discovered building frontmatter axis")
        note = self.tmp / "Notes" / "gold-skill-routing.md"
        r = self._run("promote", "1", "--to", str(note), "--brain")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(note.is_file())
        body = note.read_text()
        # Frontmatter block
        self.assertTrue(body.startswith("---\n"))
        self.assertIn("type: belief", body)
        self.assertIn("confidence:", body)
        self.assertIn("sources_count: 1", body)
        self.assertIn("tags:", body)
        self.assertIn("gold", body)  # tag list mentions gold
        # H1 title = the pattern
        self.assertIn("# pattern that became a belief", body)
        # Body carries provenance
        self.assertIn("skills/skill-suggest/SKILL.md", body)
        self.assertIn("discovered building frontmatter axis", body)

    def test_brain_existing_note_appends_under_sources(self):
        """If the target note exists, --brain appends a `- [gold #N]`
        line at the end (keeps the create-new-only semantics simple)."""
        note = self.tmp / "existing.md"
        note.write_text("---\ntype: belief\n---\n\n# Existing\n\nbody\n")
        self._run("capture", "second pattern")
        r = self._run("promote", "1", "--to", str(note), "--brain")
        self.assertEqual(r.returncode, 0)
        body = note.read_text()
        # Original preserved
        self.assertIn("# Existing", body)
        # Appended
        self.assertIn("[gold #1]", body)
        self.assertIn("second pattern", body)

    def test_brain_marks_promoted_with_destination(self):
        self._run("capture", "x")
        note = self.tmp / "Notes" / "n.md"
        self._run("promote", "1", "--to", str(note), "--brain")
        rec = json.loads(self.store.read_text().strip().splitlines()[0])
        self.assertTrue(rec["promoted"])
        self.assertEqual(rec["promoted_to"], str(note))


class TestPath(GoldBase):
    def test_path_prints_storage_location(self):
        r = self._run("path")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), str(self.store))


class TestTraceEmission(GoldBase):
    """capture + promote write trace events so `kaizen trace search`
    can surface them. Best-effort: trace failures never break the CLI."""

    def setUp(self):
        super().setUp()
        self.trace_dir = self.tmp / "trace"
        self.trace_dir.mkdir()
        self.env["KAIZEN_TRACE_DIR"] = str(self.trace_dir)

    def _trace_lines(self) -> list[dict]:
        p = self.trace_dir / "events.jsonl"
        if not p.is_file():
            return []
        return [json.loads(l) for l in p.read_text().strip().splitlines() if l]

    def test_capture_emits_gold_captured_event(self):
        r = self._run("capture", "trace-me", "--tag", "T")
        self.assertEqual(r.returncode, 0, r.stderr)
        events = [e for e in self._trace_lines() if e.get("evt") == "gold.captured"]
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual(e["data"]["id"], 1)
        self.assertEqual(e["data"]["tag"], "T")
        self.assertEqual(e["data"]["pattern"], "trace-me")

    def test_promote_emits_gold_promoted_event(self):
        self._run("capture", "p")
        target = self.tmp / "out.md"
        r = self._run("promote", "1", "--to", str(target))
        self.assertEqual(r.returncode, 0)
        events = [e for e in self._trace_lines() if e.get("evt") == "gold.promoted"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["data"]["id"], 1)
        self.assertEqual(events[0]["data"]["to"], str(target))

    def test_disabled_env_suppresses_emission(self):
        env = dict(self.env)
        env["KAIZEN_GOLD_DISABLE"] = "1"
        r = subprocess.run(
            [sys.executable, str(_SCRIPT), "capture", "silent"],
            capture_output=True, text=True, timeout=5,
            env={**os.environ, **env},
        )
        self.assertEqual(r.returncode, 0)
        self.assertEqual([e for e in self._trace_lines()
                           if e.get("evt") == "gold.captured"], [])


if __name__ == "__main__":
    unittest.main()
