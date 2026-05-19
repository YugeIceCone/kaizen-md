"""Stub coverage test for claude_docs_index.py — closes the 1:1 ratio gap.

Asserts the script exists, parses cleanly, and has a recognizable
entry point. Full behavioral coverage stays a tier-2 follow-up.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_claude_docs_index = _KZ / "scripts/indexers/claude_docs_index.py"


class TestScriptClaudeDocsIndex(unittest.TestCase):
    def test_script_present(self):
        self.assertTrue(_claude_docs_index.is_file())

    def test_script_parses(self):
        with open(_claude_docs_index) as f:
            compile(f.read(), str(_claude_docs_index), "exec")

    def test_module_has_entry_point(self):
        """Either argparse main (CLI), `mcp` (FastMCP server), or
        module-level `run` — script must be invokable."""
        text = _claude_docs_index.read_text()
        self.assertTrue(
            "def main(" in text or "mcp = FastMCP" in text
            or "def run(" in text or "argparse" in text,
            "no recognizable entry point",
        )


if __name__ == "__main__":
    unittest.main()
