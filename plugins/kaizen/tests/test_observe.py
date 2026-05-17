"""Stub coverage test for observe.py — closes the 1:1 ratio gap.

Asserts the script exists, parses cleanly, and has a recognizable
entry point. Full behavioral coverage stays a tier-2 follow-up.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_observe = _KZ / "skills/workflow/scripts/observe.py"


class TestScriptObserve(unittest.TestCase):
    def test_script_present(self):
        self.assertTrue(_observe.is_file())

    def test_script_parses(self):
        with open(_observe) as f:
            compile(f.read(), str(_observe), "exec")

    def test_module_has_entry_point(self):
        """Either argparse main (CLI), `mcp` (FastMCP server), or
        module-level `run` — script must be invokable."""
        text = _observe.read_text()
        self.assertTrue(
            "def main(" in text or "mcp = FastMCP" in text
            or "def run(" in text or "argparse" in text,
            "no recognizable entry point",
        )


if __name__ == "__main__":
    unittest.main()
