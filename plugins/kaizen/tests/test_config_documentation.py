"""Tests for the centralized-config documentation surface.

Validates:
  1. config.py docstring cross-references _paths.py + _paths.sh
  2. config.py CLI smoke (--defaults works)
  3. CLAUDE.md has a Configuration & paths section linking the trio
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_REPO_CLAUDE_MD = _KZ_DIR.parent.parent / "CLAUDE.md"
_CONFIG_PY = _KZ_DIR / "scripts/util/config.py"
_PATHS_PY = _KZ_DIR / "scripts/io/_paths.py"
_PATHS_SH = _KZ_DIR / "skills/workflow/scripts/_paths.sh"  # .sh still in legacy dir (Phase 6)


class TestConfigPyDocstring(unittest.TestCase):
    def setUp(self):
        self.text = _CONFIG_PY.read_text(encoding="utf-8")

    def test_docstring_lists_the_trio(self):
        """The docstring must name all 3 files in the config trio."""
        self.assertIn("config.py", self.text)
        self.assertIn("_paths.py", self.text)
        self.assertIn("_paths.sh", self.text)

    def test_docstring_documents_resolution_order(self):
        self.assertIn("Resolution order", self.text)
        self.assertIn("PLUGIN_DEFAULTS", self.text)
        self.assertIn(".kaizen.toml", self.text)

    def test_docstring_lists_env_overrides(self):
        for env in ("KAIZEN_DIR", "KAIZEN_HANDOFF_DIR",
                     "KAIZEN_*_DISABLE"):
            self.assertIn(env, self.text)


class TestConfigPyCliSmoke(unittest.TestCase):
    def test_defaults_flag_works(self):
        r = subprocess.run(
            [sys.executable, str(_CONFIG_PY), "--defaults"],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        # Output should contain at least the embedding-model knob
        self.assertTrue(len(r.stdout) > 50)


class TestPathsTrioExists(unittest.TestCase):
    def test_paths_py_exists(self):
        self.assertTrue(_PATHS_PY.is_file())

    def test_paths_sh_exists(self):
        self.assertTrue(_PATHS_SH.is_file())

    def test_paths_sh_exports_kaizen_dir(self):
        body = _PATHS_SH.read_text(encoding="utf-8")
        self.assertIn("KAIZEN_USER_DIR", body)
        self.assertIn("KAIZEN_DIR", body)


class TestClaudeMdConfigSection(unittest.TestCase):
    def setUp(self):
        self.body = _REPO_CLAUDE_MD.read_text(encoding="utf-8")

    def test_section_present(self):
        self.assertIn("Configuration & paths", self.body)

    def test_lists_the_trio(self):
        for f in ("config.py", "_paths.py", "_paths.sh"):
            self.assertIn(f, self.body, f"CLAUDE.md missing {f}")

    def test_documents_resolution_order(self):
        self.assertIn("Resolution order", self.body)

    def test_documents_inspect_commands(self):
        self.assertIn("kaizen-config", self.body)
        # The grep-env example
        self.assertIn("grep KAIZEN_", self.body)


if __name__ == "__main__":
    unittest.main()
