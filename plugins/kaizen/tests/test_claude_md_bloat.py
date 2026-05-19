"""Phase L: token-bloat axis for CLAUDE.md @import expansion.

Claude Code expands `@path/to/file` directives recursively at load
(max 5 hops). The total post-expansion size can be much larger than
the source CLAUDE.md. This axis measures the EFFECTIVE size + warns
when over budget.

Pure layer: expand_imports(text, base_dir, max_depth=5) → str.
Gate: _gate_claude_md_bloat → warn when over KAIZEN_CLAUDE_MD_BUDGET.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GATEKEEPER = _REPO_ROOT / "plugins/kaizen/skills/workflow/scripts/gatekeeper.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestExpandImports(unittest.TestCase):
    """Pure expansion of `@path` directives. Recursive up to max_depth."""

    def test_no_imports_returns_input(self):
        gk = _load("gk_bloat_a", _GATEKEEPER)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            out = gk._expand_imports("plain text\nno imports", base, max_depth=5)
        self.assertEqual(out, "plain text\nno imports")

    def test_resolves_relative_import(self):
        gk = _load("gk_bloat_b", _GATEKEEPER)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "included.md").write_text("INCLUDED BODY")
            text = "before\n@included.md\nafter"
            out = gk._expand_imports(text, base, max_depth=5)
        self.assertIn("INCLUDED BODY", out)
        self.assertIn("before", out)
        self.assertIn("after", out)

    def test_resolves_absolute_import(self):
        gk = _load("gk_bloat_c", _GATEKEEPER)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "abs.md"
            target.write_text("ABS BODY")
            out = gk._expand_imports(f"@{target}", base, max_depth=5)
        self.assertIn("ABS BODY", out)

    def test_resolves_home_relative_tilde(self):
        gk = _load("gk_bloat_d", _GATEKEEPER)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            fake_home = base / "home"
            fake_home.mkdir()
            (fake_home / "h.md").write_text("HOME BODY")
            with patch.object(gk.Path, "home", return_value=fake_home):
                out = gk._expand_imports("@~/h.md", base, max_depth=5)
        self.assertIn("HOME BODY", out)

    def test_recursive_import_up_to_max_depth(self):
        gk = _load("gk_bloat_e", _GATEKEEPER)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "a.md").write_text("A\n@b.md")
            (base / "b.md").write_text("B\n@c.md")
            (base / "c.md").write_text("C")
            out = gk._expand_imports("@a.md", base, max_depth=5)
        # All three bodies present, in order
        self.assertLess(out.index("A"), out.index("B"))
        self.assertLess(out.index("B"), out.index("C"))

    def test_max_depth_stops_expansion(self):
        gk = _load("gk_bloat_f", _GATEKEEPER)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "a.md").write_text("A\n@b.md")
            (base / "b.md").write_text("B\n@c.md")
            (base / "c.md").write_text("C\n@d.md")
            (base / "d.md").write_text("D")
            # max_depth=N follows N @-links. depth=2 visits a.md (link 1)
            # AND b.md (link 2), but NOT c.md (link 3 would exceed).
            out = gk._expand_imports("@a.md", base, max_depth=2)
        self.assertIn("A", out)
        self.assertIn("B", out)
        # c / d remain as literal @-lines (depth=2 stops before c.md)
        self.assertNotIn("C", out)
        self.assertNotIn("D", out)

    def test_missing_import_left_as_literal(self):
        gk = _load("gk_bloat_g", _GATEKEEPER)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            text = "@nonexistent.md\nrest"
            out = gk._expand_imports(text, base, max_depth=5)
        # The @-line stays literal (Claude Code also tolerates missing imports)
        self.assertIn("@nonexistent.md", out)
        self.assertIn("rest", out)

    def test_cycle_detection_prevents_infinite_loop(self):
        gk = _load("gk_bloat_h", _GATEKEEPER)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "a.md").write_text("A\n@b.md")
            (base / "b.md").write_text("B\n@a.md")
            # Cycle a → b → a → ... → must terminate
            out = gk._expand_imports("@a.md", base, max_depth=10)
        # Test completes (no hang) AND has both bodies at least once
        self.assertIn("A", out)
        self.assertIn("B", out)


class TestClaudeMdBloatGate(unittest.TestCase):
    """The claude-md-bloat gate warns when expanded CLAUDE.md exceeds
    KAIZEN_CLAUDE_MD_BUDGET (default 20000 bytes). Advisory only.
    """

    def setUp(self):
        self.gk = _load("gk_bloat_gate", _GATEKEEPER)

    def test_no_file_returns_no_findings(self):
        with tempfile.TemporaryDirectory() as td:
            fake_path = Path(td) / "absent.md"
            with patch.dict(os.environ, {
                "KAIZEN_CLAUDE_MD_PATH": str(fake_path),
            }):
                findings = self.gk._gate_claude_md_bloat("staged", _REPO_ROOT)
        self.assertEqual(findings, [])

    def test_within_budget_no_findings(self):
        with tempfile.TemporaryDirectory() as td:
            cmd = Path(td) / "CLAUDE.md"
            cmd.write_text("small file\n")
            with patch.dict(os.environ, {
                "KAIZEN_CLAUDE_MD_PATH": str(cmd),
                "KAIZEN_CLAUDE_MD_BUDGET": "10000",
            }):
                findings = self.gk._gate_claude_md_bloat("staged", _REPO_ROOT)
        self.assertEqual(findings, [])

    def test_over_budget_after_expansion_emits_warn(self):
        """CLAUDE.md is small but its @import expands to a huge file."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            big = base / "big.md"
            big.write_text("x" * 30_000)
            cmd = base / "CLAUDE.md"
            cmd.write_text("# tiny header\n@big.md\n")
            with patch.dict(os.environ, {
                "KAIZEN_CLAUDE_MD_PATH": str(cmd),
                "KAIZEN_CLAUDE_MD_BUDGET": "10000",
            }):
                findings = self.gk._gate_claude_md_bloat("staged", _REPO_ROOT)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "warn")
        self.assertEqual(findings[0].gate, "claude-md-bloat")
        # Message includes both expanded size + budget for diagnosis
        msg = findings[0].message
        self.assertIn("30", msg)  # ~30000B (the expanded size)
        self.assertIn("10000", msg)

    def test_in_subgates_registry(self):
        self.assertIn("claude-md-bloat", self.gk.SUB_GATES)


if __name__ == "__main__":
    unittest.main()
