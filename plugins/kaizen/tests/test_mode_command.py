"""Retirement tests for /kaizen:mode + /kaizen:session-mode.

History:
- /kaizen:mode renamed to /kaizen:session-mode (slash/bin alignment).
- /kaizen:mode alias retired 2026-05-17 (P0 of menu consolidation).
- /kaizen:session-mode FOLDED INTO /kaizen:workflow 2026-05-17 (this commit) —
  the 3-scope picker (session / project / global) covers what
  session-mode used to own as a separate slash. session-mode.json,
  kaizen-session-mode bin, and session_mode.py all stay (consumed
  directly by auto-handoff.sh / userprompt-skills-reminder.sh /
  session-intake.sh).

This test pins both retirements so a future drift re-adds neither.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_RETIRED_MODE = _KZ_DIR / "commands/mode.md"
_RETIRED_SESSION_MODE = _KZ_DIR / "commands/session-mode.md"
_CANONICAL = _KZ_DIR / "commands/workflow.md"


class TestRetiredAliases(unittest.TestCase):
    def test_mode_alias_retired(self):
        """commands/mode.md was retired in P0 (commit 15392f1)."""
        self.assertFalse(
            _RETIRED_MODE.is_file(),
            f"retired alias re-appeared: {_RETIRED_MODE}",
        )

    def test_session_mode_slash_retired(self):
        """commands/session-mode.md folded into /kaizen:workflow.
        Only the slash retires — bin + python module + storage file
        stay (consumed by hooks)."""
        self.assertFalse(
            _RETIRED_SESSION_MODE.is_file(),
            f"retired slash re-appeared: {_RETIRED_SESSION_MODE}",
        )


class TestCanonicalSurface(unittest.TestCase):
    """The fold's canonical surface is /kaizen:workflow Q1=Session."""

    def setUp(self):
        self.assertTrue(_CANONICAL.is_file(),
                          f"canonical slash missing: {_CANONICAL}")
        self.text = _CANONICAL.read_text(encoding="utf-8")

    def test_workflow_slash_covers_session_scope(self):
        """Q1 must list 'This session only' as a scope option."""
        self.assertIn("This session only", self.text)

    def test_workflow_slash_dispatches_kaizen_session_mode_bin(self):
        """Session scope keeps using kaizen-session-mode under the hood."""
        self.assertIn("kaizen-session-mode", self.text)


class TestBackingInfrastructureKept(unittest.TestCase):
    """Even with the slash retired, the bin + python module + storage
    file must stay — hooks consume them directly."""

    def test_bin_kaizen_session_mode_present(self):
        bin_path = _KZ_DIR / "bin/kaizen-session-mode"
        self.assertTrue(bin_path.is_file(),
                         f"backing bin removed: {bin_path}")

    def test_session_mode_py_present(self):
        py_path = _KZ_DIR / "scripts/workflow/session_mode.py"
        self.assertTrue(py_path.is_file(),
                         f"backing module removed: {py_path}")


if __name__ == "__main__":
    unittest.main()
