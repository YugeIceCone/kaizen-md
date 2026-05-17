"""TDD — setup-ralph-loop.sh seeds the ledger from `- [ ]` checkboxes
in the prompt when no --item / --ledger was provided.

Ralph brainstorm #6. Pragmatic ergonomics: pasting a markdown TODO
list directly creates the structured ledger without re-typing each
item as --item. Explicit --item / --ledger flags always win.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SETUP_SCRIPT = PLUGIN_ROOT / "skills" / "loop" / "scripts" / "setup-ralph-loop.sh"


class _CwdSandbox(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        os.chdir(self.tmp)
        # Isolate workflow-config so this doesn't pick up the user's real
        # loop.max_iterations default (would interfere with assertions).
        self._orig_env = dict(os.environ)
        os.environ["KAIZEN_WORKFLOW_CONFIG_PATH"] = str(
            self.tmp / ".kaizen" / "workflow.json")
        os.environ["KAIZEN_WORKFLOW_GLOBAL_CONFIG_PATH"] = str(
            self.tmp / "global" / "workflow-global.json")

    def tearDown(self):
        os.chdir(self._cwd)
        os.environ.clear()
        os.environ.update(self._orig_env)
        self._tmp.cleanup()

    def _run(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SETUP_SCRIPT), *args],
            cwd=self.tmp, capture_output=True, text=True,
            env=os.environ.copy(), timeout=20,
        )

    def _ledger_body(self) -> dict:
        text = (self.tmp / ".kaizen" / "loop.state.md").read_text()
        parts = text.split("---", 2)
        return json.loads(parts[2].strip())


class TestImplicitLedgerFromTodos(_CwdSandbox):
    def test_prompt_with_checkboxes_becomes_ledger(self):
        prompt = (
            "Work plan:\n"
            "- [ ] First step\n"
            "- [ ] Second step\n"
            "- [ ] Third step\n"
        )
        proc = self._run(prompt)
        self.assertEqual(proc.returncode, 0,
                          f"stderr={proc.stderr}\nstdout={proc.stdout}")
        body = self._ledger_body()
        descs = [it["desc"] for it in body["pending"]]
        self.assertEqual(descs, ["First step", "Second step", "Third step"])
        # The stderr surfaces the auto-conversion for observability.
        self.assertIn("implicit", proc.stderr.lower())

    def test_prompt_without_checkboxes_stays_freeform(self):
        proc = self._run("plain prompt with no todos here")
        self.assertEqual(proc.returncode, 0)
        text = (self.tmp / ".kaizen" / "loop.state.md").read_text()
        parts = text.split("---", 2)
        # Body is plain text (NOT JSON ledger)
        body = parts[2].strip()
        self.assertNotIn("pending", body)
        self.assertIn("plain prompt", body)

    def test_explicit_item_disables_implicit_parsing(self):
        """User passed --item explicitly → ignore `- [ ]` in the prompt."""
        proc = self._run("- [ ] Should be ignored", "--item", "explicit|true")
        self.assertEqual(proc.returncode, 0)
        body = self._ledger_body()
        descs = [it["desc"] for it in body["pending"]]
        self.assertEqual(descs, ["explicit"])

    def test_checked_items_skipped(self):
        """`- [x]` (already done) are NOT seeded as pending items."""
        prompt = (
            "- [x] Already done\n"
            "- [ ] Still todo\n"
            "- [X] Also done (capital X)\n"
        )
        proc = self._run(prompt)
        self.assertEqual(proc.returncode, 0)
        body = self._ledger_body()
        descs = [it["desc"] for it in body["pending"]]
        self.assertEqual(descs, ["Still todo"])


if __name__ == "__main__":
    unittest.main()
