"""todo-inventory (idea #2): inventory TODO/FIXME with file:line refs."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/quality"))

import todo_inventory  # noqa: E402


class TestTodoInventory(unittest.TestCase):
    def test_scan_finds_todo_and_fixme(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text("# TODO: refactor\nx = 1  # FIXME later\n")
            (root / "b.py").write_text("clean code\n")
            rep = todo_inventory.scan(root=root)
            kinds = {f["kind"] for f in rep["findings"]}
            self.assertIn("TODO", kinds)
            self.assertIn("FIXME", kinds)
            self.assertEqual(rep["count"], 2)


if __name__ == "__main__":
    unittest.main()
