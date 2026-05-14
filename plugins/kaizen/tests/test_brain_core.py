"""Tests for _brain.py — schema-driven Second-Brain core primitives.

Covers:
- Path resolution (env > default; project slug)
- Config loading from yaml domain files
- detect_type heuristics (world-fact / belief / observation / experience)
- Frontmatter parse + serialize round-trip
- write_note atomic + auto-stamp
- slugify
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))

import _brain  # noqa: E402


# ─── Path resolution ──────────────────────────────────────────────────


class TestPathResolution(unittest.TestCase):
    def _restore(self, name, val):
        if val is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = val

    def test_default_brain_root(self):
        orig1 = os.environ.pop("REMEMBER_BRAIN_PATH", None)
        orig2 = os.environ.pop("KAIZEN_BRAIN_PATH", None)
        try:
            root = _brain.brain_root()
            self.assertEqual(str(root), str(Path("~/.claude/brain").expanduser().resolve()))
        finally:
            self._restore("REMEMBER_BRAIN_PATH", orig1)
            self._restore("KAIZEN_BRAIN_PATH", orig2)

    def test_remember_brain_path_env_used_when_no_kaizen(self):
        # When only REMEMBER_BRAIN_PATH is set, it's used.
        orig_r = os.environ.get("REMEMBER_BRAIN_PATH")
        orig_k = os.environ.pop("KAIZEN_BRAIN_PATH", None)
        os.environ["REMEMBER_BRAIN_PATH"] = "/tmp/legacy-brain"
        try:
            self.assertEqual(str(_brain.brain_root()), "/tmp/legacy-brain")
        finally:
            self._restore("REMEMBER_BRAIN_PATH", orig_r)
            self._restore("KAIZEN_BRAIN_PATH", orig_k)

    def test_kaizen_brain_path_wins_over_remember(self):
        # KAIZEN_BRAIN_PATH is kaizen-specific and should shadow legacy
        orig_r = os.environ.get("REMEMBER_BRAIN_PATH")
        orig_k = os.environ.get("KAIZEN_BRAIN_PATH")
        os.environ["REMEMBER_BRAIN_PATH"] = "/tmp/legacy-brain"
        os.environ["KAIZEN_BRAIN_PATH"] = "/tmp/kaizen-brain"
        try:
            self.assertEqual(str(_brain.brain_root()), "/tmp/kaizen-brain")
        finally:
            self._restore("REMEMBER_BRAIN_PATH", orig_r)
            self._restore("KAIZEN_BRAIN_PATH", orig_k)

    def test_envvar_substitution_in_path(self):
        # Literal $HOME in env value gets expanded
        orig = os.environ.get("KAIZEN_BRAIN_PATH")
        os.environ["KAIZEN_BRAIN_PATH"] = "$HOME/.claude/some-brain"
        try:
            root = str(_brain.brain_root())
            self.assertNotIn("$HOME", root)
            self.assertTrue(root.endswith(".claude/some-brain"))
        finally:
            self._restore("KAIZEN_BRAIN_PATH", orig)

    def test_project_slug_for(self):
        slug = _brain.project_slug_for(Path("/home/x/workspace/shodan"))
        self.assertEqual(slug, "-home-x-workspace-shodan")

    def test_project_slug_for_relative(self):
        # Resolve to absolute, then slug
        rel = Path(".").resolve()
        s = _brain.project_slug_for(rel)
        self.assertTrue(s.startswith("-"))


# ─── Config loading ───────────────────────────────────────────────────


class TestConfigLoad(unittest.TestCase):
    def test_load_default_config(self):
        cfg = _brain.Config.load()
        # All four types present
        for t in ("world-fact", "belief", "observation", "experience"):
            self.assertIn(t, cfg.types)
        # Default type
        self.assertEqual(cfg.default_type, "world-fact")
        # Detection priority has all four
        self.assertEqual(set(cfg.detection_priority), {"world-fact", "belief", "observation", "experience"})
        # Tier rules non-empty
        self.assertGreater(len(cfg.tier_rules), 0)

    def test_belief_requires_confidence(self):
        cfg = _brain.Config.load()
        spec = cfg.types["belief"]
        self.assertIn("confidence", spec.required_keys)

    def test_world_fact_does_not_require_confidence(self):
        cfg = _brain.Config.load()
        spec = cfg.types["world-fact"]
        self.assertNotIn("confidence", spec.required_keys)

    def test_capture_rules_loaded(self):
        cfg = _brain.Config.load()
        self.assertGreater(len(cfg.capture_when), 0)
        self.assertGreater(len(cfg.skip_when), 0)


# ─── Type detection ──────────────────────────────────────────────────


class TestTypeDetection(unittest.TestCase):
    def setUp(self):
        self.cfg = _brain.Config.load()

    def test_world_fact(self):
        self.assertEqual(
            _brain.detect_type("we decided to use sqlite for the index", self.cfg),
            "world-fact",
        )
        self.assertEqual(
            _brain.detect_type("going with redis over memcached", self.cfg),
            "world-fact",
        )

    def test_belief(self):
        self.assertEqual(
            _brain.detect_type("I think we should prefer simple code", self.cfg),
            "belief",
        )
        self.assertEqual(
            _brain.detect_type("user prefers terse output", self.cfg),
            "belief",
        )

    def test_observation(self):
        self.assertEqual(
            _brain.detect_type("Alice leads the team on backend", self.cfg),
            "observation",
        )
        self.assertEqual(
            _brain.detect_type("the user works as a senior engineer", self.cfg),
            "observation",
        )

    def test_experience_date_marker(self):
        self.assertEqual(
            _brain.detect_type("on 2026-05-14 we deployed the new index", self.cfg),
            "experience",
        )

    def test_experience_event_verb(self):
        self.assertEqual(
            _brain.detect_type("met with the data team today", self.cfg),
            "experience",
        )

    def test_empty_input_returns_default(self):
        self.assertEqual(_brain.detect_type("", self.cfg), self.cfg.default_type)

    def test_unrecognized_text_returns_default(self):
        self.assertEqual(
            _brain.detect_type("xyzzy plugh", self.cfg),
            self.cfg.default_type,
        )

    def test_case_insensitive(self):
        self.assertEqual(
            _brain.detect_type("WE DECIDED TO USE X", self.cfg),
            "world-fact",
        )


# ─── Frontmatter parse + serialize ───────────────────────────────────


class TestFrontmatterRoundTrip(unittest.TestCase):
    def test_parse_basic(self):
        text = """---
name: Test note
description: A test
type: belief
confidence: 0.8
---

Body content here.
"""
        fm, body = _brain.parse_note(text)
        self.assertEqual(fm["name"], "Test note")
        self.assertEqual(fm["type"], "belief")
        self.assertEqual(fm["confidence"], 0.8)
        self.assertIn("Body content here.", body)

    def test_parse_no_frontmatter(self):
        text = "Just a body, no frontmatter.\n"
        fm, body = _brain.parse_note(text)
        self.assertEqual(fm, {})
        self.assertEqual(body.strip(), "Just a body, no frontmatter.")

    def test_parse_empty(self):
        fm, body = _brain.parse_note("")
        self.assertEqual(fm, {})
        self.assertEqual(body, "")

    def test_serialize_basic(self):
        fm = {
            "name": "Test",
            "description": "Test desc",
            "type": "belief",
            "confidence": 0.9,
            "tags": ["a", "b"],
        }
        out = _brain.serialize_frontmatter(fm)
        self.assertTrue(out.startswith("---\n"))
        self.assertTrue(out.endswith("---\n"))
        self.assertIn("name: Test", out)
        self.assertIn("confidence: 0.9", out)
        self.assertIn("[a, b]", out)

    def test_serialize_preserves_key_order(self):
        # Even if input is jumbled, output uses preferred order
        fm = {"confidence": 0.5, "name": "X", "type": "belief", "description": "Y"}
        out = _brain.serialize_frontmatter(fm)
        idx_name = out.find("name:")
        idx_desc = out.find("description:")
        idx_type = out.find("type:")
        idx_conf = out.find("confidence:")
        self.assertLess(idx_name, idx_desc)
        self.assertLess(idx_desc, idx_type)
        self.assertLess(idx_type, idx_conf)

    def test_roundtrip(self):
        fm = {
            "name": "RT", "description": "RT desc",
            "type": "world-fact",
            "tags": ["a", "b", "c"],
        }
        text = _brain.serialize_frontmatter(fm) + "\nbody text"
        parsed_fm, parsed_body = _brain.parse_note(text)
        self.assertEqual(parsed_fm["name"], "RT")
        self.assertEqual(parsed_fm["type"], "world-fact")
        self.assertEqual(parsed_fm["tags"], ["a", "b", "c"])
        self.assertIn("body text", parsed_body)


# ─── write_note ──────────────────────────────────────────────────────


class TestWriteNote(unittest.TestCase):
    def test_writes_with_today_stamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "Notes" / "test.md"
            _brain.write_note(p, {"name": "T", "description": "d", "type": "world-fact"}, "body")
            text = p.read_text()
            today = dt.date.today().isoformat()
            self.assertIn(f"created: {today}", text)
            self.assertIn(f"updated: {today}", text)
            self.assertIn("body", text)

    def test_preserves_existing_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.md"
            _brain.write_note(
                p,
                {"name": "X", "description": "d", "type": "belief",
                 "confidence": 0.7, "created": "2026-01-01"},
                "body",
            )
            text = p.read_text()
            self.assertIn("created: 2026-01-01", text)
            today = dt.date.today().isoformat()
            self.assertIn(f"updated: {today}", text)

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a" / "b" / "c" / "deep.md"
            _brain.write_note(p, {"name": "D", "description": "d", "type": "world-fact"}, "")
            self.assertTrue(p.is_file())


# ─── slugify ─────────────────────────────────────────────────────────


class TestSlugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_brain.slugify("Hello World"), "hello-world")
        self.assertEqual(_brain.slugify("foo BAR baz"), "foo-bar-baz")

    def test_strips_punct(self):
        self.assertEqual(_brain.slugify("X: a, b; c!"), "x-a-b-c")

    def test_truncates(self):
        long_s = "abc " * 50
        out = _brain.slugify(long_s, max_len=20)
        self.assertLessEqual(len(out), 20)
        self.assertFalse(out.endswith("-"))

    def test_empty(self):
        self.assertEqual(_brain.slugify(""), "note")
        self.assertEqual(_brain.slugify("   "), "note")


# ─── CLI invocation smoke test ───────────────────────────────────────


class TestCli(unittest.TestCase):
    def test_cli_shows_paths(self):
        import subprocess
        script = _KZ_DIR / "skills/workflow/scripts/_brain.py"
        result = subprocess.run(
            ["python3", str(script)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("brain_root", result.stdout)
        self.assertIn("types", result.stdout)


if __name__ == "__main__":
    unittest.main()
