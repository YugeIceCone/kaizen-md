"""Tests for the Python ports of scripts/upstream/{session_start,
user_prompt, build_context}.js.

Each port preserves the upstream JS behavior: env-disable, brain-root
resolution, keyword detection, REMEMBER.md section merging, Evidence
Log truncation. The ports replace the runtime Node.js dependency of
the SessionStart + UserPromptSubmit hooks with pure-Python equivalents.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "scripts"))

import build_context as bc  # noqa: E402
import session_start as ss  # noqa: E402
import user_prompt as up  # noqa: E402


class TestParseSections(unittest.TestCase):
    """build_context.parse_sections: extract `## Header\\n body` blocks."""

    def test_empty_string_returns_empty(self):
        self.assertEqual(bc.parse_sections(""), [])

    def test_single_section(self):
        text = "## Routing\n- a → b\n- c → d"
        sections = bc.parse_sections(text)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["name"], "Routing")
        self.assertIn("a → b", sections[0]["content"])

    def test_multiple_sections_preserve_order(self):
        text = "## First\nA\n\n## Second\nB\n\n## Third\nC"
        names = [s["name"] for s in bc.parse_sections(text)]
        self.assertEqual(names, ["First", "Second", "Third"])

    def test_content_trimmed(self):
        text = "## X\n\n   body  \n\n"
        s = bc.parse_sections(text)[0]
        self.assertEqual(s["content"], "body")


class TestMergeSections(unittest.TestCase):
    """build_context.merge_sections: plugin defaults + user overrides."""

    def test_default_when_no_user_section(self):
        plugin = [{"name": "Routing", "content": "default routing"}]
        merged, extras = bc.merge_sections(plugin, [])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source"], "default")
        self.assertEqual(extras, [])

    def test_user_section_with_same_name_appends(self):
        plugin = [{"name": "Routing", "content": "default"}]
        user = [{"name": "Routing", "content": "user-extra"}]
        merged, _ = bc.merge_sections(plugin, user)
        self.assertEqual(merged[0]["source"], "append")
        self.assertIn("default", merged[0]["content"])
        self.assertIn("user-extra", merged[0]["content"])

    def test_override_prefix_replaces_default(self):
        plugin = [{"name": "Routing", "content": "default"}]
        user = [{"name": "Override: Routing", "content": "user-replacement"}]
        merged, _ = bc.merge_sections(plugin, user)
        self.assertEqual(merged[0]["source"], "override")
        self.assertEqual(merged[0]["content"], "user-replacement")
        self.assertNotIn("default", merged[0]["content"])

    def test_extra_user_section_no_default_match(self):
        plugin = [{"name": "Routing", "content": "x"}]
        user = [{"name": "MyCustom", "content": "y"}]
        merged, extras = bc.merge_sections(plugin, user)
        self.assertEqual(len(merged), 1)  # plugin section only
        self.assertEqual(len(extras), 1)
        self.assertEqual(extras[0]["name"], "MyCustom")

    def test_case_insensitive_name_match(self):
        plugin = [{"name": "Routing", "content": "default"}]
        user = [{"name": "ROUTING", "content": "user"}]
        merged, _ = bc.merge_sections(plugin, user)
        self.assertEqual(merged[0]["source"], "append")


class TestRenderSections(unittest.TestCase):
    def test_renders_headers_with_content(self):
        out = bc.render_sections([{"name": "X", "content": "body"}])
        self.assertEqual(out, "## X\nbody")

    def test_drops_empty_content(self):
        sections = [
            {"name": "X", "content": "body"},
            {"name": "Y", "content": ""},
            {"name": "Z", "content": "   "},
        ]
        out = bc.render_sections(sections)
        self.assertIn("## X", out)
        self.assertNotIn("## Y", out)
        self.assertNotIn("## Z", out)


class TestTruncateEvidenceLog(unittest.TestCase):
    """session_start.truncate_evidence_log: cap log size in Persona."""

    def test_no_evidence_section_passes_through(self):
        persona = "## Mission\n- be helpful\n\n## Directives\n- be kind\n"
        out = ss.truncate_evidence_log(persona, max_lines=5)
        self.assertEqual(out, persona)

    def test_under_limit_unchanged(self):
        entries = "\n".join(f"- [2026-05-{i:02d}] event {i}" for i in range(1, 4))
        persona = f"## Evidence Log\n{entries}\n"
        out = ss.truncate_evidence_log(persona, max_lines=5)
        # 3 entries, max 5 — unchanged
        self.assertIn("event 1", out)
        self.assertIn("event 3", out)

    def test_over_limit_keeps_last_n(self):
        entries = "\n".join(f"- [2026-05-{i:02d}] event {i}" for i in range(1, 11))
        persona = f"## Evidence Log\n{entries}\n"
        out = ss.truncate_evidence_log(persona, max_lines=3)
        # 10 entries, max 3 — only last 3 (events 8, 9, 10) retained
        self.assertNotIn("event 1\n", out)
        self.assertNotIn("event 7", out)
        self.assertIn("event 8", out)
        self.assertIn("event 10", out)

    def test_preserves_section_after_evidence(self):
        entries = "\n".join(f"- [2026-05-{i:02d}] e{i}" for i in range(1, 11))
        persona = (
            f"## Evidence Log\n{entries}\n\n## After Section\n- preserved\n"
        )
        out = ss.truncate_evidence_log(persona, max_lines=3)
        self.assertIn("## After Section", out)
        self.assertIn("- preserved", out)


class TestSessionStartMain(unittest.TestCase):
    def test_remember_processing_env_exits_0(self):
        with patch.dict(os.environ, {"REMEMBER_PROCESSING": "1"}, clear=False):
            self.assertEqual(ss.main(), 0)

    def test_missing_brain_dir_exits_0_silently(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"KAIZEN_BRAIN_DIR": str(Path(td) / "nope")}):
                self.assertEqual(ss.main(), 0)

    def test_emits_banner_and_persona(self):
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            brain.mkdir()
            (brain / "Persona.md").write_text(
                "## Mission\nbe a good agent\n", encoding="utf-8",
            )
            env = {"KAIZEN_BRAIN_DIR": str(brain),
                   "REMEMBER_PROCESSING": ""}
            import io
            buf = io.StringIO()
            with patch.dict(os.environ, env, clear=False), \
                 patch("sys.stdout", buf):
                rc = ss.main()
            out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("REMEMBER BRAIN LOADED", out)
        self.assertIn("be a good agent", out)


class TestUserPromptMain(unittest.TestCase):
    def test_remember_processing_env_exits_0(self):
        with patch.dict(os.environ, {"REMEMBER_PROCESSING": "1"}, clear=False):
            self.assertEqual(up.main(), 0)

    def test_no_keyword_match_no_output(self):
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            brain.mkdir()
            import io
            buf = io.StringIO()
            env = {"KAIZEN_BRAIN_DIR": str(brain), "REMEMBER_PROCESSING": ""}
            stdin_text = "just a regular question, nothing to save\n"
            with patch.dict(os.environ, env, clear=False), \
                 patch("sys.stdin", io.StringIO(stdin_text)), \
                 patch("sys.stdout", buf):
                rc = up.main()
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "")

    def test_keyword_match_emits_hookspecificoutput(self):
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            brain.mkdir()
            import io
            buf = io.StringIO()
            env = {"KAIZEN_BRAIN_DIR": str(brain), "REMEMBER_PROCESSING": ""}
            stdin_text = "remember this: hello\n"
            with patch.dict(os.environ, env, clear=False), \
                 patch("sys.stdin", io.StringIO(stdin_text)), \
                 patch("sys.stdout", buf):
                rc = up.main()
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("hookSpecificOutput", payload)
        self.assertEqual(
            payload["hookSpecificOutput"]["hookEventName"],
            "UserPromptSubmit",
        )
        self.assertIn("BRAIN DUMP", payload["hookSpecificOutput"]["additionalContext"])

    def test_json_event_shape_prompt_field_extracted(self):
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            brain.mkdir()
            import io
            buf = io.StringIO()
            env = {"KAIZEN_BRAIN_DIR": str(brain), "REMEMBER_PROCESSING": ""}
            # Claude Code's actual shape: JSON event with `prompt` field.
            stdin_text = json.dumps({
                "prompt": "save this to brain please",
                "session_id": "abc",
            })
            with patch.dict(os.environ, env, clear=False), \
                 patch("sys.stdin", io.StringIO(stdin_text)), \
                 patch("sys.stdout", buf):
                rc = up.main()
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("hookSpecificOutput", payload)


if __name__ == "__main__":
    unittest.main()
