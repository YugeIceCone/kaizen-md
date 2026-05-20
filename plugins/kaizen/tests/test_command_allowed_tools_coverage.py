"""allowed-tools coverage (idea #37): commands that invoke tools
should declare allowed-tools in frontmatter.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ / "scripts/quality"))

import command_allowed_tools_coverage as ctc  # noqa: E402

_HAS_TOOL_INVOKE = """---
name: x
description: does work
---
Run `kaizen-foo report --json` to see the surface.
"""

_NO_TOOL_INVOKE = """---
name: y
description: pure info
---
Just narrative prose. Pure documentation about a concept.
"""

_HAS_ALLOWED = """---
name: z
description: does work
allowed-tools: ["Bash(python3 foo:*)"]
---
Runs foo via bash.
"""

class TestCommandAllowedToolsCoverage(unittest.TestCase):
    def test_synthetic_missing_allowed_tools(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "needs.md").write_text(_HAS_TOOL_INVOKE)
            (d / "ok.md").write_text(_HAS_ALLOWED)
            (d / "noop.md").write_text(_NO_TOOL_INVOKE)
            rep = ctc.scan(commands_dir=d)
            names = {g["command"] for g in rep["gaps"]}
            self.assertIn("needs.md", names)
            self.assertNotIn("ok.md", names)
            self.assertNotIn("noop.md", names)

    def test_real_dir_scan_returns_shape(self):
        rep = ctc.scan(commands_dir=_KZ / "commands")
        for k in ("commands_total", "gaps", "coverage_pct"):
            self.assertIn(k, rep)

if __name__ == "__main__":
    unittest.main()
