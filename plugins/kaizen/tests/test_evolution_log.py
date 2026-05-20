"""Tests for evolution_log.py — append-only event log for evolve actions.

Mirrors the upstream remember-md/remember/tests/evolution-log.test.js shape.
Sandboxed via explicit log_path (no XDG_STATE_HOME pollution).
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_KZ / "scripts"))

import evolution_log as el  # noqa: E402


class TestAppendEvent(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log = Path(self._tmp.name) / "evolution.log"

    def tearDown(self):
        self._tmp.cleanup()

    def test_appends_iso_ts_type_message(self):
        el.append_event("PROMOTE", "Notes/pref-x.md → Persona.Top", log_path=self.log)
        text = self.log.read_text()
        # Format: <ISO-ts>  <TYPE>  <message>\n
        self.assertIn("PROMOTE", text)
        self.assertIn("Notes/pref-x.md → Persona.Top", text)
        # ISO timestamp ends with Z (UTC)
        self.assertTrue(text.split()[0].endswith("Z"))

    def test_appends_not_truncates(self):
        el.append_event("PROMOTE", "first", log_path=self.log)
        el.append_event("DEMOTE", "second", log_path=self.log)
        text = self.log.read_text()
        self.assertIn("first", text)
        self.assertIn("second", text)
        self.assertEqual(text.count("\n"), 2)

    def test_creates_parent_dirs(self):
        nested = Path(self._tmp.name) / "a" / "b" / "c" / "evolution.log"
        el.append_event("CONSOLIDATE", "nested", log_path=nested)
        self.assertTrue(nested.is_file())

    def test_rejects_unknown_event_type(self):
        with self.assertRaises(ValueError) as cm:
            el.append_event("INVALID_TYPE", "x", log_path=self.log)
        self.assertIn("unknown event type", str(cm.exception))

    def test_valid_types_match_upstream(self):
        """Locks the 7 event types upstream uses; preserving the contract
        across the JS → Python port keeps cross-tooling consumers safe."""
        self.assertEqual(
            el.VALID_TYPES,
            frozenset({"PROMOTE", "DEMOTE", "CONSOLIDATE", "REFLECT",
                       "STALE", "CONTRADICT", "ARCHIVE_CANDIDATE"}),
        )


class TestDefaultLogPath(unittest.TestCase):
    def test_uses_xdg_state_home_when_set(self):
        with self._patched_env({"XDG_STATE_HOME": "/tmp/custom-state"}):
            p = el.default_log_path()
            self.assertEqual(p, Path("/tmp/custom-state/remember/evolution.log"))

    def test_falls_back_to_dotlocal(self):
        with self._patched_env({"XDG_STATE_HOME": ""}):
            p = el.default_log_path()
            self.assertEqual(p.parent.parent.name, ".local")
            self.assertEqual(p.name, "evolution.log")

    def _patched_env(self, env):
        old = {k: os.environ.get(k) for k in env}

        class _Ctx:
            def __enter__(self_):
                for k, v in env.items():
                    if v:
                        os.environ[k] = v
                    else:
                        os.environ.pop(k, None)

            def __exit__(self_, *exc):
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        return _Ctx()


class TestCli(unittest.TestCase):
    def test_main_usage_on_too_few_args(self):
        rc = el.main([])
        self.assertEqual(rc, 1)

    def test_main_rejects_bad_type(self):
        rc = el.main(["BOGUS", "msg"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
