"""Tests for pretooluse-brain-redirect — auto-nudge Read→brain show.

Per user 2026-05-19 — "automate it don't rely on skills."

When the agent calls Read on a Markdown file under brain/ or
project-memory/, this PreToolUse hook intercepts the event JSON
on stdin and emits a hook-decision JSON on stdout containing
`additionalContext` with the file's heading-paths + the precise
`kaizen-brain show` command to use instead. Never blocks; advisory.

Bypass: KAIZEN_BRAIN_REDIRECT_DISABLE=1.

Pure core: should_redirect(tool, input) → bool; build_hint(path) → str
Adapter: hook reads stdin JSON, calls pure functions, writes stdout JSON.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_HOOK = _KZ / "hooks/claude/_brain_redirect.py"

sys.path.insert(0, str(_KZ / "hooks/claude"))
import _brain_redirect as br  # noqa: E402


_SAMPLE = """# Note

## Beliefs

- Belief 1
- Belief 2

## Evidence

- Quote 1
"""


# ─── should_redirect — pure ────────────────────────────────────────────

class TestShouldRedirect(unittest.TestCase):
    def test_read_on_brain_markdown_matches(self):
        self.assertTrue(br.should_redirect(
            "Read", {"file_path": "/home/u/.claude/.kaizen/brain/Persona.md"}))

    def test_read_on_brain_note_matches(self):
        self.assertTrue(br.should_redirect(
            "Read", {"file_path": "/home/u/.claude/.kaizen/brain/Notes/pref-x.md"}))

    def test_read_on_project_memory_matches(self):
        self.assertTrue(br.should_redirect(
            "Read", {"file_path": "/home/u/.claude/projects/-repo/memory/feedback_x.md"}))

    def test_read_on_non_markdown_skips(self):
        self.assertFalse(br.should_redirect(
            "Read", {"file_path": "/home/u/.claude/.kaizen/brain/brain.db"}))

    def test_read_on_project_claude_md_matches(self):
        # CLAUDE.md is the rulebook — Read should nudge to brain show.
        # Even short ~5KB CLAUDE.md re-loads waste tokens when only one
        # section is wanted.
        self.assertTrue(br.should_redirect(
            "Read", {"file_path": "/home/u/workspace/repo/CLAUDE.md"}))

    def test_read_on_user_global_claude_md_matches(self):
        self.assertTrue(br.should_redirect(
            "Read", {"file_path": "/home/u/.claude/CLAUDE.md"}))

    def test_read_on_claude_local_md_matches(self):
        self.assertTrue(br.should_redirect(
            "Read", {"file_path": "/home/u/workspace/repo/CLAUDE.local.md"}))

    def test_read_on_unrelated_md_skips(self):
        self.assertFalse(br.should_redirect(
            "Read", {"file_path": "/home/u/workspace/repo/README.md"}))

    def test_non_read_tool_skips(self):
        self.assertFalse(br.should_redirect(
            "Edit", {"file_path": "/home/u/.claude/.kaizen/brain/Persona.md"}))

    def test_missing_file_path_skips(self):
        self.assertFalse(br.should_redirect("Read", {}))


# ─── build_hint — pure ─────────────────────────────────────────────────

class TestBuildHint(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.note = self.tmp / "Note.md"
        self.note.write_text(_SAMPLE, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_hint_lists_blocks_and_commands(self):
        hint = br.build_hint(self.note)
        # Mentions the addressable blocks
        self.assertIn("Beliefs", hint)
        self.assertIn("Evidence", hint)
        # Mentions the precise CLI to use
        self.assertIn("kaizen-brain show", hint)
        self.assertIn(str(self.note), hint)

    def test_hint_handles_no_headings(self):
        flat = self.tmp / "flat.md"
        flat.write_text("Just text, no headings.\n", encoding="utf-8")
        hint = br.build_hint(flat)
        # Should still suggest the CLI (full-file extract is OK fallback)
        self.assertIn("kaizen-brain", hint)

    def test_hint_handles_missing_file(self):
        # File-not-found shouldn't raise — hint is best-effort advisory
        hint = br.build_hint(self.tmp / "nope.md")
        # Empty or minimal string is fine; just must not crash
        self.assertIsInstance(hint, str)


# ─── disable env knob ──────────────────────────────────────────────────

class TestDisable(unittest.TestCase):
    def test_disable_env_suppresses_redirect(self):
        _orig = os.environ.get("KAIZEN_BRAIN_REDIRECT_DISABLE")
        try:
            os.environ["KAIZEN_BRAIN_REDIRECT_DISABLE"] = "1"
            self.assertFalse(br.should_redirect(
                "Read", {"file_path": "/home/u/.claude/.kaizen/brain/Persona.md"}))
        finally:
            if _orig is None:
                os.environ.pop("KAIZEN_BRAIN_REDIRECT_DISABLE", None)
            else:
                os.environ["KAIZEN_BRAIN_REDIRECT_DISABLE"] = _orig


# ─── shell hook integration ────────────────────────────────────────────

class TestHookCLI(unittest.TestCase):
    """End-to-end: feed JSON via stdin, expect hook-decision JSON on stdout."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.note = self.tmp / "Persona.md"
        self.note.write_text(_SAMPLE, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, event: dict):
        import subprocess as sp
        return sp.run(
            [sys.executable, str(_HOOK)],
            input=json.dumps(event), capture_output=True, text=True, timeout=10,
            env=os.environ.copy(),
        )

    def test_brain_path_emits_additional_context(self):
        # Create a fake brain path under the tempdir (substring matters,
        # not real location). Hook matches on ".kaizen/brain/" substring.
        fake_brain = self.tmp / ".kaizen" / "brain"
        fake_brain.mkdir(parents=True)
        fake_note = fake_brain / "Persona.md"
        fake_note.write_text(_SAMPLE, encoding="utf-8")
        event = {"tool_name": "Read",
                 "tool_input": {"file_path": str(fake_note)}}
        r = self._run(event)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        # Hook emits hook-decision JSON with additionalContext
        self.assertIn("hookSpecificOutput", out)
        self.assertIn("kaizen-brain", out["hookSpecificOutput"]
                       ["additionalContext"])

    def test_non_brain_path_emits_empty(self):
        event = {"tool_name": "Read",
                 "tool_input": {"file_path": "/tmp/random.md"}}
        r = self._run(event)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        # No redirect → empty object
        self.assertEqual(out, {})


if __name__ == "__main__":
    unittest.main()
