"""Tests for the loop concern's user-facing wiring.

Historical context: prior to consolidate-2 D1, the loop concern was
surfaced as a dedicated slash `/kaizen:loop` with a P3 super-menu
wizard (Q1 budget × Q2 stop-conditions) baked into the slash body.
The pre-fold suite in this file asserted properties of that slash
body (frontmatter / Auto-honor / Interactive wizard / Q1+Q2 /
Arg assembly / Backcompat).

Post-fold (consolidate-2 D1): the slash is retired and the loop
concern now reaches users via:
  - `kaizen-loop` bin (canonical invocation; argument-mode + wizard)
  - `/kaizen:workflow` Q2 = "Loop" (the workflow wizard surfaces loop
    as a run-mode and persists --loop-its + --loop-stop via
    kaizen-workflow-config)
  - `commands/workflow.md` "Folded surface" section (the menu pointer
    that documents the bin as the direct entry point)

Behavior of the bin + setup script + Stop hook is covered by
test_loop_merge / test_loop_state / test_loop_hardening /
test_loop_promise_robust. This file now asserts the post-fold
USER-FACING wiring only — the pre-fold body assertions are skipped
with an explicit reason (no-deletion rule).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_LOOP_BIN = _KZ_DIR / "bin" / "kaizen-loop"
_WORKFLOW_CMD = _KZ_DIR / "commands" / "workflow.md"

_FOLDED_REASON = (
    "Pre-fold: asserted properties of commands/loop.md. Post consolidate-2 "
    "D1 the slash is retired; the loop concern is reached via kaizen-loop "
    "bin + /kaizen:workflow Q2=Loop. See test_loop_merge for the new "
    "wiring asserts."
)


@unittest.skip(_FOLDED_REASON)
class TestSessionModeAutoHonor(unittest.TestCase):
    """Retired with the slash. Behavior preserved in kaizen-loop bin."""


@unittest.skip(_FOLDED_REASON)
class TestP3WizardFrontmatter(unittest.TestCase):
    """Retired with the slash. Wizard now lives in /kaizen:workflow Q2."""


@unittest.skip(_FOLDED_REASON)
class TestP3WizardStructure(unittest.TestCase):
    """Retired with the slash. Workflow wizard owns Q1+Q2."""


@unittest.skip(_FOLDED_REASON)
class TestP3BridgeFromWorkflow(unittest.TestCase):
    """Retired with the slash. The /kaizen:workflow Q2=Loop bridge is
    now intrinsic, not documented in a separate slash."""


@unittest.skip(_FOLDED_REASON)
class TestP3ArgAssembly(unittest.TestCase):
    """Retired with the slash. Arg assembly lives in setup-ralph-loop.sh."""


@unittest.skip(_FOLDED_REASON)
class TestP3Backcompat(unittest.TestCase):
    """Retired with the slash. Bin still supports --item/--cancel/promise."""


# Post-fold positive assertions — the loop concern reaches users via
# the bin and the workflow Folded surface.


class TestPostFoldLoopWiring(unittest.TestCase):
    """Post consolidate-2 D1: assert the loop concern's new entry points."""

    def test_loop_bin_exists_and_executable(self):
        self.assertTrue(_LOOP_BIN.is_file(), f"missing {_LOOP_BIN}")
        # POSIX permission bit check — bin must be runnable.
        import stat
        mode = _LOOP_BIN.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR, f"{_LOOP_BIN} not user-executable")

    def test_workflow_folded_surface_advertises_loop_bin(self):
        text = _WORKFLOW_CMD.read_text(encoding="utf-8")
        self.assertIn("Folded surface", text)
        self.assertIn("kaizen-loop", text)
        # The retired slash name is documented in the "was" column to
        # help users transitioning from the old menu.
        self.assertIn("/kaizen:loop", text)

    def test_workflow_q2_loop_label_present(self):
        """The /kaizen:workflow wizard must still expose Loop as a Q2
        run-mode option — that's the user-facing replacement for the
        retired slash's P3 wizard entry."""
        text = _WORKFLOW_CMD.read_text(encoding="utf-8")
        self.assertRegex(text, r"Loop\s*\(Ralph\)", )


if __name__ == "__main__":
    unittest.main()
