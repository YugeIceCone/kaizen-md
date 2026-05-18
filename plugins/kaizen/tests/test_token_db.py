"""TDD: verify tree-sitter deps reachable via the PEP-723 uv-script
invocation path that _token_db.py uses in production.

Phase 1 (T1) — confirms the `#!/usr/bin/env -S uv run --script` shebang
+ inline dep manifest in `_token_db.py` resolves all 3 grammars when
the script is actually invoked. (System Python doesn't see uv-managed
deps; that's by design — uv keeps per-script venvs isolated.)
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "skills" / "workflow" / "scripts" / "_token_db.py"
)


def _uv_import_check(modname: str) -> subprocess.CompletedProcess:
    """Run the script via uv (which loads its PEP-723 deps) and probe an import."""
    return subprocess.run(
        ["uv", "run", "--script", str(SCRIPT), "-c",
         f"import {modname}; print('ok')"],
        capture_output=True, text=True, timeout=30,
    )


class TestTreesitterDepAvailable(unittest.TestCase):
    def test_script_file_exists(self):
        self.assertTrue(SCRIPT.exists(), f"missing: {SCRIPT}")

    def test_tree_sitter_importable_via_uv_script(self):
        r = _uv_import_check("tree_sitter")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("ok", r.stdout)

    def test_tree_sitter_rust_importable_via_uv_script(self):
        r = _uv_import_check("tree_sitter_rust")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("ok", r.stdout)

    def test_tree_sitter_python_importable_via_uv_script(self):
        r = _uv_import_check("tree_sitter_python")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("ok", r.stdout)


if __name__ == "__main__":
    unittest.main()
