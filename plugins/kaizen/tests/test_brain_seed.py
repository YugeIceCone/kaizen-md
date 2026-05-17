"""Tests for `brain.py seed` — onboarding starter brain.

Lets a new user bootstrap a working brain from a curated starter
(shipped in `assets/starters/<name>/`):

    kaizen-brain seed <name>          → copy starter into KAIZEN_BRAIN_DIR
    kaizen-brain seed list            → list available starters
    kaizen-brain seed default --force → overwrite-on-conflict

Written test-first per TDD. Pre-fix: `cmd_seed` doesn't exist; tests
fail with AttributeError. Post-fix: starter copies into the sandbox
brain dir, idempotent, refuses overwrite without --force.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
sys.path.insert(0, str(_SCRIPTS))


class _BaseSeedCase(unittest.TestCase):
    """Sandbox: tempdir as brain root via KAIZEN_BRAIN_DIR."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.brain = self.tmp / "brain"
        self._orig_env = dict(os.environ)
        os.environ["KAIZEN_BRAIN_DIR"] = str(self.brain)
        for mod in ("_paths", "_brain", "brain"):
            sys.modules.pop(mod, None)
        import _paths   # noqa: F401
        import brain
        self.brain_mod = brain

    def tearDown(self):
        for mod in ("_paths", "_brain", "brain"):
            sys.modules.pop(mod, None)
        for k in list(os.environ):
            if k.startswith("KAIZEN_") and k not in self._orig_env:
                os.environ.pop(k, None)
        os.environ.update(self._orig_env)
        self._tmp.cleanup()

    def _args(self, **kw):
        import argparse
        ns = argparse.Namespace(starter="default", force=False, json=False)
        for k, v in kw.items():
            setattr(ns, k, v)
        return ns


class SeedListing(_BaseSeedCase):

    def test_seed_list_returns_default(self):
        starters = self.brain_mod.list_starters()
        self.assertIn("default", starters,
                       f"`default` starter missing from {starters}")


class SeedHappyPath(_BaseSeedCase):

    def test_seed_default_creates_brain_with_persona_and_notes(self):
        rc = self.brain_mod.cmd_seed(self._args())
        self.assertEqual(rc, 0)
        self.assertTrue(self.brain.is_dir())
        persona = self.brain / "Persona.md"
        self.assertTrue(persona.is_file())
        notes = self.brain / "Notes"
        self.assertTrue((notes / "pref-no-deletions.md").is_file())
        self.assertTrue((notes / "pref-tdd-for-new-code.md").is_file())
        self.assertTrue((notes / "kaizen-allow-log-deletions.md").is_file())

    def test_seed_substitutes_today_placeholder(self):
        self.brain_mod.cmd_seed(self._args())
        today = dt.date.today().isoformat()
        persona_text = (self.brain / "Persona.md").read_text()
        self.assertIn(today, persona_text,
                       "{{today}} placeholder should be substituted")

    def test_seed_creates_para_subdirs(self):
        self.brain_mod.cmd_seed(self._args())
        for sub in ("Inbox", "Journal", "Projects", "People", "Areas",
                    "Resources", "Tasks", "Templates", "Archive"):
            self.assertTrue((self.brain / sub).is_dir(),
                              f"missing PARA dir: {sub}")


class SeedIdempotency(_BaseSeedCase):

    def test_seed_refuses_overwrite_without_force(self):
        self.brain.mkdir(parents=True)
        (self.brain / "Persona.md").write_text("user-written content\n")
        rc = self.brain_mod.cmd_seed(self._args())
        self.assertNotEqual(rc, 0,
                            "must refuse to overwrite existing brain")
        self.assertEqual(
            (self.brain / "Persona.md").read_text(),
            "user-written content\n")

    def test_seed_force_overwrites(self):
        self.brain.mkdir(parents=True)
        (self.brain / "Persona.md").write_text("old\n")
        rc = self.brain_mod.cmd_seed(self._args(force=True))
        self.assertEqual(rc, 0)
        text = (self.brain / "Persona.md").read_text()
        self.assertIn("# Persona", text)
        self.assertNotEqual(text, "old\n")


class SeedErrors(_BaseSeedCase):

    def test_seed_missing_starter_returns_nonzero(self):
        rc = self.brain_mod.cmd_seed(self._args(starter="does-not-exist"))
        self.assertNotEqual(rc, 0)
        self.assertFalse(self.brain.is_dir())


if __name__ == "__main__":
    unittest.main()
