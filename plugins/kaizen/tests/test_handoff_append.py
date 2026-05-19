"""Tests for `kaizen handoff append` — mid-session entry append.

Per Task #40 (handoff upgrades) — closes 2 of 6 remaining: mid-session
append. Before this, agents had to re-scaffold the whole handoff yaml
to add a done-task or finding. Now they can append in place.

Scope (v1): line-based insertion at the end of a body list-section.
Supported sections: done_this_session (dict entries) +
{blockers, questions, decisions, findings, worked, failed, next}
(string entries).

Non-goals (defer):
  - frontmatter sections (status / outcome)
  - scalar sections (goal / now / test)
  - dict sections (files / session_meta / code_context)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_HANDOFF = _KZ / "skills/workflow/scripts/handoff.py"

sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/rules"))
import handoff as _h  # noqa: E402


# ─── Fixtures ──────────────────────────────────────────────────────────

_BASE_YAML = """---
session: kaizen-md
date: 2026-05-18
status: partial
outcome: IN_PROGRESS
---

session_meta:
  cc_session_uuid: 'abc-123'
  handoff_generated_at: '2026-05-18T20:00:00Z'

goal: 'work in progress'
now: 'do something'
test: TBD

done_this_session:
  - task: 'first task'
    files: []

blockers: []
questions: []
"""

_EMPTY_DONE_YAML = """---
session: kaizen-md
status: partial
---

done_this_session: []
blockers: []
"""


# ─── _append_to_list_section ───────────────────────────────────────────

class TestAppendToListSection(unittest.TestCase):
    def test_append_dict_entry_to_populated_section(self):
        out = _h._append_to_list_section(
            _BASE_YAML, "done_this_session",
            {"task": "second task", "files": ["a.py", "b.py"]}
        )
        # Original task preserved
        self.assertIn("'first task'", out)
        # New task present
        self.assertIn("second task", out)
        # Two entries under done_this_session
        self.assertEqual(out.count("  - task:"), 2)

    def test_append_to_empty_section_inflates_inline_list(self):
        # `done_this_session: []` → `done_this_session:\n  - task: foo\n    files: []`
        out = _h._append_to_list_section(
            _EMPTY_DONE_YAML, "done_this_session",
            {"task": "first ever", "files": []}
        )
        self.assertIn("first ever", out)
        self.assertNotIn("done_this_session: []", out)
        # blockers: [] untouched
        self.assertIn("blockers: []", out)

    def test_append_string_entry_to_list_section(self):
        out = _h._append_to_list_section(
            _BASE_YAML, "blockers", "watchdog process unresponsive"
        )
        self.assertIn("watchdog process unresponsive", out)
        # done_this_session preserved
        self.assertIn("'first task'", out)

    def test_append_to_missing_section_creates_it(self):
        # decisions: not in fixture; append should add the section
        self.assertNotIn("decisions:", _BASE_YAML)
        out = _h._append_to_list_section(
            _BASE_YAML, "decisions", "use posix sh not bash for portability"
        )
        self.assertIn("decisions:", out)
        self.assertIn("posix sh", out)

    def test_unknown_section_raises_or_returns_unchanged(self):
        # Adding to a non-list section (goal is scalar) should not corrupt
        # the file. We raise ValueError to be loud.
        with self.assertRaises(ValueError):
            _h._append_to_list_section(_BASE_YAML, "goal", "x")


# ─── CLI integration ───────────────────────────────────────────────────

class TestHandoffAppendCLI(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.yaml = self.tmp / "test.yaml"
        self.yaml.write_text(_BASE_YAML, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_HANDOFF), *args],
            capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )

    def test_append_task_writes_to_done_this_session(self):
        r = self._run("append", "--file", str(self.yaml),
                       "--section", "done_this_session",
                       "--task", "new TDD task")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.yaml.read_text(encoding="utf-8")
        self.assertIn("new TDD task", text)
        # Frontmatter preserved
        self.assertIn("status: partial", text)

    def test_append_with_files_attaches_them(self):
        r = self._run("append", "--file", str(self.yaml),
                       "--section", "done_this_session",
                       "--task", "wired the handler",
                       "--files", "src/x.py,tests/test_x.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.yaml.read_text(encoding="utf-8")
        self.assertIn("wired the handler", text)
        self.assertIn("src/x.py", text)
        self.assertIn("tests/test_x.py", text)

    def test_append_string_entry(self):
        # blockers / decisions / findings / etc — pass --entry instead of --task
        r = self._run("append", "--file", str(self.yaml),
                       "--section", "blockers",
                       "--entry", "watcher process didn't start")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.yaml.read_text(encoding="utf-8")
        self.assertIn("watcher process didn't start", text)

    def test_append_missing_file_fails(self):
        r = self._run("append", "--file", str(self.tmp / "nope.yaml"),
                       "--section", "blockers", "--entry", "x")
        self.assertNotEqual(r.returncode, 0)

    def test_append_idempotent_on_replay(self):
        # Two appends of the same content → 2 entries (not deduped — by design).
        self._run("append", "--file", str(self.yaml),
                   "--section", "blockers", "--entry", "same thing")
        self._run("append", "--file", str(self.yaml),
                   "--section", "blockers", "--entry", "same thing")
        text = self.yaml.read_text(encoding="utf-8")
        self.assertEqual(text.count("same thing"), 2)


if __name__ == "__main__":
    unittest.main()
