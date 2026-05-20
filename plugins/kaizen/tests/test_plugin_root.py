"""Unit tests for `_plugin_root.py` — the kaizen plugin-root resolver.

Mirrors `tests/test_plugin_root.sh` 1:1 (same cases, bash side covers
the shell helper).

Run:
    python3 -m unittest tests.test_plugin_root -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Make _plugin_root importable from the canonical scripts dir.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

import _plugin_root as pr  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts" / "io"

class _ScrubEnv(unittest.TestCase):
    """Base class — strips CLAUDE_PLUGIN_ROOT + KAIZEN_PLUGIN_ROOT per-test."""

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in pr.ENV_VARS}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

def _make_plugin_dir(tmpdir: str, name: str = "fake-plugin") -> Path:
    """Create a fake plugin dir with .claude-plugin/plugin.json. Returns its path."""
    p = Path(tmpdir) / name
    (p / ".claude-plugin").mkdir(parents=True)
    (p / ".claude-plugin" / "plugin.json").write_text('{"name":"' + name + '"}\n')
    return p

class TestMarkerDetection(_ScrubEnv):
    def test_is_plugin_dir_true_when_marker_present(self):
        with tempfile.TemporaryDirectory() as td:
            p = _make_plugin_dir(td)
            self.assertTrue(pr._is_plugin_dir(p))

    def test_is_plugin_dir_false_when_marker_absent(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(pr._is_plugin_dir(Path(td)))

class TestEnvResolution(_ScrubEnv):
    def test_claude_plugin_root_used_when_set(self):
        with tempfile.TemporaryDirectory() as td:
            p = _make_plugin_dir(td, "via-claude")
            os.environ["CLAUDE_PLUGIN_ROOT"] = str(p)
            self.assertEqual(pr.plugin_root().resolve(), p.resolve())

    def test_kaizen_plugin_root_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            p = _make_plugin_dir(td, "via-kaizen")
            os.environ["KAIZEN_PLUGIN_ROOT"] = str(p)
            self.assertEqual(pr.plugin_root().resolve(), p.resolve())

    def test_claude_wins_over_kaizen(self):
        with tempfile.TemporaryDirectory() as td:
            a = _make_plugin_dir(td, "a-claude")
            b = _make_plugin_dir(td, "b-kaizen")
            os.environ["CLAUDE_PLUGIN_ROOT"] = str(a)
            os.environ["KAIZEN_PLUGIN_ROOT"] = str(b)
            self.assertEqual(pr.plugin_root().resolve(), a.resolve())

    def test_env_set_but_no_marker_falls_through(self):
        # Env points at a non-plugin dir → should ignore + try next strategy
        # (script-derived). Script-derived will find this repo's plugin root.
        with tempfile.TemporaryDirectory() as td:
            os.environ["CLAUDE_PLUGIN_ROOT"] = td  # no marker file → invalid
            resolved = pr.plugin_root()
            self.assertTrue((resolved / pr.MARKER).is_file())

    def test_env_blank_string_treated_as_unset(self):
        os.environ["CLAUDE_PLUGIN_ROOT"] = ""
        os.environ["KAIZEN_PLUGIN_ROOT"] = ""
        # Should fall through to script-derived path (finds this repo's plugin root).
        resolved = pr.plugin_root()
        self.assertTrue((resolved / pr.MARKER).is_file())

class TestScriptDerivedResolution(_ScrubEnv):
    def test_script_path_walks_up_to_find_marker(self):
        # _plugin_root.py itself lives under the plugin root, so the
        # derived path should resolve to the kaizen plugin root.
        resolved = pr.plugin_root()
        self.assertTrue((resolved / pr.MARKER).is_file())
        # Sanity: it's the kaizen plugin (not some unrelated marker)
        self.assertEqual(resolved.name, "kaizen")

    def test_from_script_path_returns_none_when_no_marker(self):
        with tempfile.TemporaryDirectory() as td:
            start = Path(td) / "nested" / "deep"
            start.mkdir(parents=True)
            self.assertIsNone(pr._from_script_path(start))

class TestStrictMode(_ScrubEnv):
    def test_strict_false_returns_none_when_unresolved(self):
        # Use a hypothetical path inside tmpdir whose walk-up won't hit a marker.
        with tempfile.TemporaryDirectory() as td:
            # Monkeypatch _from_script_path to simulate unresolved
            original = pr._from_script_path
            try:
                pr._from_script_path = lambda _start: None
                self.assertIsNone(pr.plugin_root(strict=False))
            finally:
                pr._from_script_path = original

    def test_strict_true_raises_when_unresolved(self):
        original = pr._from_script_path
        try:
            pr._from_script_path = lambda _start: None
            with self.assertRaises(pr.PluginRootNotFound):
                pr.plugin_root(strict=True)
        finally:
            pr._from_script_path = original

class TestContract(unittest.TestCase):
    """Lock the public surface — names + types — so callers don't drift."""

    def test_env_vars_order(self):
        # CLAUDE_PLUGIN_ROOT must come before KAIZEN_PLUGIN_ROOT.
        self.assertEqual(pr.ENV_VARS, ("CLAUDE_PLUGIN_ROOT", "KAIZEN_PLUGIN_ROOT"))

    def test_marker_path(self):
        self.assertEqual(pr.MARKER, Path(".claude-plugin") / "plugin.json")

    def test_plugin_root_returns_path(self):
        self.assertIsInstance(pr.plugin_root(), Path)

    def test_module_callable_via_main(self):
        # Smoke: __main__ exit code 0 + prints a path
        import subprocess

        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "_plugin_root.py")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue((Path(result.stdout.strip()) / pr.MARKER).is_file())

if __name__ == "__main__":
    unittest.main()
