"""Tests for auto_load — daemon-built CLAUDE.md companion.

Per user 2026-05-19: exploit ~/.claude/CLAUDE.md as the auto-loader
for the kaizen backend. The daemon rebuilds ~/.claude/.kaizen/auto-load.md
from top-N Persona beliefs + active gates each tick; CLAUDE.md
imports it via `@~/.claude/.kaizen/auto-load.md`.

Pure layer: parse_persona(text) + build_auto_load(persona, top_n, budget).
Adapter (daemon job): reads Persona, writes auto-load.md atomically.
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "workflow" / "scripts"))


_SAMPLE_PERSONA = """---
created: 2026-05-10
updated: 2026-05-19
tags: [persona, system]
---

# Persona

Loaded at every session start.

## Mission

- **Name:** User
- **Role:** _to be filled in_

## Directives

- **No deletions without explicit authorization.** Never `rm` until the user has explicitly approved. See [[Notes/pref-no-deletions]].
- **Onion / DDD is mandatory.** Inward-only deps. See [[Notes/pref-onion-architecture-strict]].
- **Brand new code is TDD.** RED → GREEN → REFACTOR. See [[Notes/pref-tdd-for-new-code]].

## Top Beliefs

1. [[Notes/pref-no-deletions.md]] — conf=0.98 sources=5 freshness=stable
2. [[Notes/pref-onion-architecture-strict.md]] — conf=0.97 sources=5 freshness=stable
3. [[Notes/pref-coding-skills-strict.md]] — conf=0.96 sources=5 freshness=stable
4. [[Notes/pref-optional-feature-graceful-fallback.md]] — conf=0.85 sources=4 freshness=stable
5. [[Notes/pref-handoff-over-raw-log.md]] — conf=0.90 sources=2 freshness=stable

## Evidence Log

- [2026-05-19] Quote: "automate it don't rely on skills" → PreToolUse redirect.
- [2026-05-19] Quote: "retire reliance on CLAUDE.md".
"""


class TestParsePersona(unittest.TestCase):
    """Pure: extract structured beliefs/directives from Persona markdown."""

    def test_extracts_directives(self):
        import auto_load as al
        parsed = al.parse_persona(_SAMPLE_PERSONA)
        directives = parsed["directives"]
        self.assertEqual(len(directives), 3)
        # Each directive has text + linked note
        no_del = directives[0]
        self.assertIn("No deletions", no_del["text"])
        self.assertEqual(no_del["note"], "Notes/pref-no-deletions")

    def test_extracts_top_beliefs_with_metadata(self):
        import auto_load as al
        parsed = al.parse_persona(_SAMPLE_PERSONA)
        beliefs = parsed["top_beliefs"]
        self.assertEqual(len(beliefs), 5)
        first = beliefs[0]
        self.assertEqual(first["rank"], 1)
        self.assertEqual(first["note"], "Notes/pref-no-deletions.md")
        self.assertEqual(first["confidence"], 0.98)
        self.assertEqual(first["sources"], 5)

    def test_handles_persona_without_top_beliefs(self):
        import auto_load as al
        minimal = "# Persona\n\n## Directives\n\n- **Rule.** See [[Notes/X]].\n"
        parsed = al.parse_persona(minimal)
        self.assertEqual(len(parsed["directives"]), 1)
        self.assertEqual(parsed["top_beliefs"], [])


class TestBuildAutoLoad(unittest.TestCase):
    """Pure: structured persona → markdown auto-load file."""

    def test_emits_hard_gate_for_must_not_rules(self):
        import auto_load as al
        out = al.build_auto_load(_SAMPLE_PERSONA, top_n=10, byte_budget=5000)
        # No-deletions has "Never" → wrapped in HARD-GATE
        self.assertIn("<HARD-GATE>", out)
        self.assertIn("</HARD-GATE>", out)
        # Note links preserved
        self.assertIn("[[Notes/pref-no-deletions]]", out)

    def test_top_n_caps_belief_list(self):
        import auto_load as al
        out = al.build_auto_load(_SAMPLE_PERSONA, top_n=2, byte_budget=5000)
        # Only top 2 beliefs in the body
        self.assertIn("pref-no-deletions.md", out)
        self.assertIn("pref-onion-architecture-strict.md", out)
        self.assertNotIn("pref-coding-skills-strict.md", out)

    def test_byte_budget_truncates(self):
        import auto_load as al
        out = al.build_auto_load(_SAMPLE_PERSONA, top_n=10, byte_budget=500)
        self.assertLessEqual(len(out.encode("utf-8")), 600,
                             "byte budget overrun (allow 100B slack for header)")

    def test_output_has_do_not_edit_warning(self):
        import auto_load as al
        out = al.build_auto_load(_SAMPLE_PERSONA, top_n=10, byte_budget=5000)
        # Daemon-managed file — warn human editors
        lower = out.lower()
        self.assertTrue(
            any(s in lower for s in ("do not edit", "auto-generated",
                                     "daemon", "rebuilt")),
            "must signal that the file is daemon-managed")

    def test_output_is_valid_markdown_with_heading(self):
        import auto_load as al
        out = al.build_auto_load(_SAMPLE_PERSONA, top_n=10, byte_budget=5000)
        self.assertTrue(out.startswith("# "),
                         "must start with a markdown heading")


class TestDaemonJob(unittest.TestCase):
    """Adapter: run_auto_load reads brain Persona, writes auto-load.md.

    Sandboxed via KAIZEN_BRAIN_DIR + KAIZEN_AUTO_LOAD_PATH.
    """

    def test_disabled_via_env_returns_skipped(self):
        import auto_load as al
        from unittest.mock import patch
        with patch.dict(os.environ, {"KAIZEN_DAEMON_AUTO_LOAD_DISABLE": "1"}):
            ok, msg, action = al.run_auto_load(state={})
        self.assertTrue(ok)
        self.assertEqual(action, "auto-load")
        self.assertIn("disabled", msg.lower())

    def test_writes_auto_load_md_when_enabled(self):
        import auto_load as al
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            brain.mkdir()
            (brain / "Persona.md").write_text(_SAMPLE_PERSONA)
            target = Path(td) / "auto-load.md"
            env = {
                "KAIZEN_BRAIN_DIR": str(brain),
                "KAIZEN_AUTO_LOAD_PATH": str(target),
            }
            from unittest.mock import patch
            with patch.dict(os.environ, env):
                ok, msg, action = al.run_auto_load(state={})
            self.assertTrue(ok)
            self.assertEqual(action, "auto-load")
            self.assertTrue(target.is_file())
            content = target.read_text()
            self.assertIn("pref-no-deletions", content)


if __name__ == "__main__":
    unittest.main()
