"""Tests for loop_state.py — controlled CRUD on .kaizen/loop.state.md.

Pairs with test_loop_merge.py (which tests the Stop-hook side). This file
tests the AGENT-FACING tools: add_item, list_pending, list_completed,
status, complete_item, cancel. Plus the bin/kaizen-loop wrapper.

Run:
    python3 -m unittest tests.test_loop_state -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "workflow" / "scripts"))

import loop_state as ls  # noqa: E402

SETUP_SCRIPT = PLUGIN_ROOT / "skills" / "loop" / "scripts" / "setup-ralph-loop.sh"
BIN_LOOP = PLUGIN_ROOT / "bin" / "kaizen-loop"


def _init_loop(tmpdir: Path, items: list[str] | None = None,
               max_iter: int = 10) -> Path:
    """Initialize a loop in `tmpdir` and return the state path."""
    args = ["bash", str(SETUP_SCRIPT), "--max-iterations", str(max_iter)]
    if items:
        for it in items:
            args.extend(["--item", it])
    else:
        args.append("seed prompt")
    subprocess.run(args, cwd=tmpdir, check=True, capture_output=True)
    return tmpdir / ".kaizen" / "loop.state.md"


class _CwdMixin:
    """Run each test from a private tmpdir so loop_state's cwd resolution works."""

    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpcm = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpcm.name)
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpcm.cleanup()


class TestAddItem(_CwdMixin, unittest.TestCase):
    def test_appends_with_auto_id(self):
        _init_loop(self.tmp, items=["First|true", "Second"])
        item = ls.add_item("Third", verify="grep -q x file.py")
        self.assertEqual(item["id"], "i3")
        self.assertEqual(item["desc"], "Third")
        self.assertEqual(item["verify"], "grep -q x file.py")
        pending = ls.list_pending()
        self.assertEqual(len(pending), 3)
        self.assertEqual(pending[2]["id"], "i3")

    def test_empty_desc_rejected(self):
        _init_loop(self.tmp, items=["First|true"])
        with self.assertRaises(ValueError):
            ls.add_item("", verify="true")

    def test_no_verify_becomes_null(self):
        _init_loop(self.tmp, items=["First|true"])
        item = ls.add_item("Trust-based")
        self.assertIsNone(item["verify"])

    def test_id_avoids_collision_with_completed(self):
        """Auto-IDs skip IDs already in completed (i.e. previously moved out)."""
        _init_loop(self.tmp, items=["a|true", "b|true", "c"])
        # Manually move i3 to completed via complete_item
        ls.complete_item("i3", note="manual")
        # Add a new item — id should be i4, not i3
        new_item = ls.add_item("Fourth")
        self.assertEqual(new_item["id"], "i4")

    def test_missing_state_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            ls.add_item("anything")


class TestListAndStatus(_CwdMixin, unittest.TestCase):
    def test_list_pending_after_setup(self):
        _init_loop(self.tmp, items=["A|true", "B"])
        pending = ls.list_pending()
        self.assertEqual(len(pending), 2)
        self.assertEqual(pending[0]["id"], "i1")
        self.assertEqual(pending[1]["id"], "i2")

    def test_list_completed_empty_initially(self):
        _init_loop(self.tmp, items=["A|true"])
        self.assertEqual(ls.list_completed(), [])

    def test_status_reports_counts(self):
        _init_loop(self.tmp, items=["A|true", "B|true"], max_iter=5)
        s = ls.status()
        self.assertTrue(s["active"])
        self.assertEqual(s["iteration"], 1)
        self.assertEqual(s["max_iterations"], 5)
        self.assertEqual(s["pending_count"], 2)
        self.assertEqual(s["completed_count"], 0)

    def test_status_inactive_when_no_loop(self):
        s = ls.status()
        self.assertFalse(s["active"])


class TestCompleteItem(_CwdMixin, unittest.TestCase):
    def test_complete_verify_null_item(self):
        _init_loop(self.tmp, items=["A|true", "B"])  # i2 = verify=null
        entry = ls.complete_item("i2", note="checked")
        self.assertEqual(entry["id"], "i2")
        self.assertEqual(entry["desc"], "B")
        self.assertTrue(entry["manual"])
        self.assertEqual(entry["note"], "checked")
        self.assertIn("iteration", entry)
        self.assertIn("completed_at", entry)
        # Item is gone from pending
        pending = ls.list_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["id"], "i1")
        # And in completed
        completed = ls.list_completed()
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["id"], "i2")

    def test_complete_refuses_verify_bearing_item(self):
        """Items with verify must pass the hook's verify gate — cannot be
        manually completed (cheat-proof)."""
        _init_loop(self.tmp, items=["A|grep x file.py"])
        with self.assertRaises(ValueError) as ctx:
            ls.complete_item("i1")
        self.assertIn("verify", str(ctx.exception))
        # Item stayed in pending
        self.assertEqual(len(ls.list_pending()), 1)
        self.assertEqual(ls.list_completed(), [])

    def test_complete_by_desc_substring(self):
        _init_loop(self.tmp, items=["Long item description"])
        # Note: "Long item description" has no verify, so it can be completed.
        # But we have no verify because of how --item parses. Actually it has
        # verify: None since there's no "|" in the input.
        entry = ls.complete_item("item descrip")  # substring match
        self.assertEqual(entry["id"], "i1")

    def test_complete_unknown_raises(self):
        _init_loop(self.tmp, items=["A"])
        with self.assertRaises(KeyError):
            ls.complete_item("nonexistent")


class TestCancel(_CwdMixin, unittest.TestCase):
    def test_cancel_removes_state_file(self):
        _init_loop(self.tmp, items=["A|true"])
        result = ls.cancel()
        self.assertTrue(result["cancelled"])
        self.assertEqual(result["iteration"], 1)
        self.assertFalse((self.tmp / ".kaizen" / "loop.state.md").is_file())

    def test_cancel_no_loop_returns_noop(self):
        result = ls.cancel()
        self.assertFalse(result["cancelled"])


class TestBinWrapper(unittest.TestCase):
    """The bin/kaizen-loop bash wrapper exists and forwards subcommands."""

    def test_wrapper_exists_and_executable(self):
        self.assertTrue(BIN_LOOP.is_file())
        self.assertTrue(os.access(BIN_LOOP, os.X_OK))

    def test_wrapper_bash_syntax_clean(self):
        result = subprocess.run(
            ["bash", "-n", str(BIN_LOOP)], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrapper_help_subcommand(self):
        result = subprocess.run(
            ["bash", str(BIN_LOOP), "--help"],
            capture_output=True, text=True, timeout=5,
            env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("add", result.stdout)
        self.assertIn("complete", result.stdout)

    def test_wrapper_add_subcommand_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _init_loop(tmp, items=["existing"])
            env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)}
            result = subprocess.run(
                ["bash", str(BIN_LOOP), "add", "from CLI", "--verify", "true"],
                cwd=tmp,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("added", result.stdout.lower())
            # State file should now have 2 items
            state = (tmp / ".kaizen" / "loop.state.md").read_text()
            body = state.split("---\n", 2)[-1].strip()
            data = json.loads(body)
            self.assertEqual(len(data["pending"]), 2)


class TestMcpServerImports(unittest.TestCase):
    """loop_mcp.py imports cleanly and exposes the expected tools."""

    def test_mcp_module_loads(self):
        sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "workflow" / "scripts"))
        if "loop_mcp" in sys.modules:
            del sys.modules["loop_mcp"]
        import loop_mcp  # noqa: E402
        for name in (
            "loop_add_item", "loop_list_pending", "loop_list_completed",
            "loop_status", "loop_complete_item", "loop_cancel",
        ):
            self.assertTrue(
                hasattr(loop_mcp, name),
                f"loop_mcp missing tool: {name}",
            )


class TestSetupAutoIds(unittest.TestCase):
    """Setup script auto-assigns IDs to --item entries (lets `complete <id>` work)."""

    def test_items_get_sequential_ids(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _init_loop(tmp, items=["A|true", "B", "C|false"])
            state = (tmp / ".kaizen" / "loop.state.md").read_text()
            body = state.split("---\n", 2)[-1].strip()
            data = json.loads(body)
            ids = [it["id"] for it in data["pending"]]
            self.assertEqual(ids, ["i1", "i2", "i3"])

    def test_ledger_file_import_assigns_missing_ids(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger = tmp / "in.json"
            # Pre-existing items: one with id, one without
            ledger.write_text(json.dumps({
                "pending": [
                    {"id": "iX", "desc": "has id", "verify": "true"},
                    {"desc": "no id", "verify": None},
                ]
            }))
            subprocess.run(
                ["bash", str(SETUP_SCRIPT), "--ledger", str(ledger)],
                cwd=tmp,
                check=True,
                capture_output=True,
            )
            state = (tmp / ".kaizen" / "loop.state.md").read_text()
            body = state.split("---\n", 2)[-1].strip()
            data = json.loads(body)
            self.assertEqual(data["pending"][0]["id"], "iX")  # preserved
            # The auto-assigned id should NOT collide with iX
            self.assertNotEqual(data["pending"][1].get("id"), "iX")
            self.assertTrue(data["pending"][1].get("id"))


if __name__ == "__main__":
    unittest.main()
