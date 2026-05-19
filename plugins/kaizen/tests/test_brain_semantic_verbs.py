"""Tests for the 3 semantic verbs on Persona blocks.

These are thin wrappers over kaizen-brain edit + _brain_blocks.
The verbs eliminate the "agent must construct full --file --block --append
incantation" friction by encoding the canonical operations:

- log-evidence "<quote>"   → append to Persona's Evidence Log
- new-directive "<rule>" --note <slug>  → append to Persona's Directives
- promote-belief <note-slug>            → append to Persona's Top Beliefs

Each verb is atomic (tempfile-then-rename), idempotent on already-present
content, surfaces errors clearly (file missing / block missing / malformed
input), and never partially-writes.

Sandboxed via KAIZEN_BRAIN_DIR.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parents[1]
_BRAIN = _KZ / "scripts/brain/brain.py"


_SAMPLE_PERSONA = """---
created: 2026-05-10
updated: 2026-05-19
tags: [persona, system]
---

# Persona

## Mission

- **Role:** _to be filled in_

## Directives

- **No deletions.** See [[Notes/pref-no-deletions]].
- **Onion / DDD mandatory.** See [[Notes/pref-onion-architecture-strict]].

## Top Beliefs

1. [[Notes/pref-no-deletions.md]] — conf=0.98 sources=5 freshness=stable
2. [[Notes/pref-onion-architecture-strict.md]] — conf=0.97 sources=5 freshness=stable

## Evidence Log

- [2026-05-10] First evidence.
"""


class _PersonaSandbox(unittest.TestCase):
    """Per-test sandbox: write a fake brain root with Persona.md."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name) / "brain"
        self.brain.mkdir()
        self.persona = self.brain / "Persona.md"
        self.persona.write_text(_SAMPLE_PERSONA, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _env(self):
        e = os.environ.copy()
        e["KAIZEN_BRAIN_DIR"] = str(self.brain)
        return e

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(_BRAIN), *args],
            capture_output=True, text=True, timeout=15, env=self._env(),
        )


class TestLogEvidence(_PersonaSandbox):

    def test_appends_to_evidence_log_block(self):
        r = self._run("log-evidence", "Quote: \"X\" → Y conclusion.")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.persona.read_text()
        self.assertIn("Quote: \"X\" → Y conclusion.", text)
        # Preserves existing evidence
        self.assertIn("First evidence.", text)
        # Lands inside the Evidence Log block (after it, before EOF or next ##)
        idx_log = text.index("## Evidence Log")
        idx_quote = text.index("Quote: \"X\"")
        self.assertGreater(idx_quote, idx_log)

    def test_prepends_iso_date_when_omitted(self):
        r = self._run("log-evidence", "raw quote with no date")
        self.assertEqual(r.returncode, 0)
        text = self.persona.read_text()
        # Auto-prefixed with [YYYY-MM-DD]
        import re
        self.assertRegex(text, r"\[\d{4}-\d{2}-\d{2}\] raw quote with no date")

    def test_preserves_existing_iso_date_prefix(self):
        r = self._run("log-evidence", "[2099-01-01] explicit date wins")
        self.assertEqual(r.returncode, 0)
        text = self.persona.read_text()
        self.assertIn("[2099-01-01] explicit date wins", text)
        # Must NOT double-prefix
        self.assertNotIn("] [2099-", text)

    def test_idempotent_on_exact_duplicate(self):
        self._run("log-evidence", "duplicate-check")
        r = self._run("log-evidence", "duplicate-check")
        self.assertEqual(r.returncode, 0)
        text = self.persona.read_text()
        # Should appear EXACTLY once (verb is idempotent on exact match)
        self.assertEqual(text.count("duplicate-check"), 1)


class TestNewDirective(_PersonaSandbox):

    def test_appends_to_directives_block_with_note_link(self):
        r = self._run("new-directive",
                       "Always commit per-phase.",
                       "--note", "Notes/pref-phased-commits")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.persona.read_text()
        self.assertIn("Always commit per-phase", text)
        self.assertIn("[[Notes/pref-phased-commits]]", text)
        # Preserves existing directives
        self.assertIn("No deletions", text)

    def test_requires_note_flag(self):
        r = self._run("new-directive", "Rule with no note link")
        self.assertNotEqual(r.returncode, 0,
            "directive without --note should fail (every directive must link a Note)")
        self.assertIn("note", r.stderr.lower() + r.stdout.lower())

    def test_idempotent_on_dup(self):
        self._run("new-directive", "Test rule.", "--note", "Notes/pref-x")
        r = self._run("new-directive", "Test rule.", "--note", "Notes/pref-x")
        self.assertEqual(r.returncode, 0)
        text = self.persona.read_text()
        # Both rule text + note link appear exactly once
        self.assertEqual(text.count("Test rule"), 1)


class TestPromoteBelief(_PersonaSandbox):

    def test_appends_to_top_beliefs_with_next_rank(self):
        r = self._run("promote-belief", "Notes/pref-jsonl",
                       "--conf", "0.92", "--sources", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.persona.read_text()
        # Existing beliefs preserved
        self.assertIn("pref-no-deletions.md", text)
        # New belief landed with next rank (3, since 1 + 2 existed)
        import re
        new_line = re.search(
            r"^3\.\s+\[\[Notes/pref-jsonl\.?md?\]\][^\n]+",
            text, re.M,
        )
        self.assertIsNotNone(new_line,
            "new belief should be rank 3 with conf + sources metadata")
        self.assertIn("conf=0.92", new_line.group(0))
        self.assertIn("sources=3", new_line.group(0))

    def test_normalizes_note_ref_to_md_suffix(self):
        """Promote accepts Notes/pref-x OR Notes/pref-x.md — both render as .md."""
        self._run("promote-belief", "Notes/pref-y", "--conf", "0.8")
        text = self.persona.read_text()
        self.assertIn("[[Notes/pref-y.md]]", text)

    def test_idempotent_on_already_promoted(self):
        self._run("promote-belief", "Notes/pref-z", "--conf", "0.7")
        r = self._run("promote-belief", "Notes/pref-z", "--conf", "0.99")
        self.assertEqual(r.returncode, 0)
        text = self.persona.read_text()
        # Belief appears once (no duplicate). Update-or-skip: first wins
        # by default. The second invocation reports "already promoted"
        # but does not error.
        self.assertEqual(text.count("Notes/pref-z.md"), 1)
        self.assertIn("already", r.stdout.lower() + r.stderr.lower())


class TestErrorHandling(_PersonaSandbox):

    def test_log_evidence_when_persona_missing(self):
        self.persona.unlink()
        r = self._run("log-evidence", "X")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Persona", r.stderr + r.stdout)

    def test_log_evidence_when_evidence_block_missing(self):
        """When the block doesn't exist, the verb creates it rather than
        erroring — semantic verbs are best-effort + auto-seed."""
        broken = self.brain / "Persona.md"
        broken.write_text("# Persona\n\n## Directives\n\n- **X.** See [[Notes/x]].\n")
        r = self._run("log-evidence", "first evidence")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = broken.read_text()
        self.assertIn("## Evidence Log", text)
        self.assertIn("first evidence", text)

    def test_promote_belief_rejects_empty_note(self):
        r = self._run("promote-belief", "", "--conf", "0.8")
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
