"""Tests for kaizen-bundle — session-folder management for .kaizen/superpowers/.

Convention (per user 2026-05-18):
  .kaizen/superpowers/<YYYY-MM-DD>-<project>-<short-sid>/multiple-files.md

Each session's artifacts (specs, plans, brainstorms, notes) bundle into
ONE date+project+sid folder. Templates and durable references stay
outside session folders (templates/ at top level).

Subcommands:
  init   — scaffold a new bundle folder (idempotent on re-run)
  list   — show bundles (filter by --project, --since DUR)
  path   — print the path of a bundle by spec
  add    — move a file INTO a bundle (preserves prefix-stripped name)

Iron-laws (same family as kaizen-progress/learn/observer-events):
  - PROGRAMMABLE — pure functions + scriptable CLI
  - REPRODUCIBLE — same inputs → same folder + same path
  - CONSISTENT   — env-overridable root via KAIZEN_SUPERPOWERS_DIR
  - DETERMINISTIC — folder name is a pure function of (date, project, sid)
  - REUSABLE     — works for any multi-project bundle layout
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_BUNDLE_PY = _KZ_DIR / "scripts/util/superpower_bundle.py"


class _BundleBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "superpowers"
        self.root.mkdir()
        self._orig = os.environ.get("KAIZEN_SUPERPOWERS_DIR")
        os.environ["KAIZEN_SUPERPOWERS_DIR"] = str(self.root)

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig is None:
            os.environ.pop("KAIZEN_SUPERPOWERS_DIR", None)
        else:
            os.environ["KAIZEN_SUPERPOWERS_DIR"] = self._orig

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_BUNDLE_PY), *args],
            capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )


class TestBundleFolderName:
    """Pure-function tests (no I/O) — folder name is deterministic."""

    def test_with_full_sid(self):
        import sys
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        from superpower_bundle import bundle_folder_name
        name = bundle_folder_name("2026-05-18", "kaizen-md",
                                    "6ebbb7cb-11ff-4316-a34c-15566eb24925")
        assert name == "2026-05-18-kaizen-md-6ebbb7cb"

    def test_short_sid_passthrough(self):
        from superpower_bundle import bundle_folder_name
        name = bundle_folder_name("2026-05-18", "kaizen-md", "6ebbb7cb")
        assert name == "2026-05-18-kaizen-md-6ebbb7cb"

    def test_no_sid(self):
        from superpower_bundle import bundle_folder_name
        name = bundle_folder_name("2026-05-18", "kaizen-md", None)
        assert name == "2026-05-18-kaizen-md"

    def test_project_kebab_case_enforced(self):
        from superpower_bundle import bundle_folder_name
        name = bundle_folder_name("2026-05-18", "Kaizen MD", "abc")
        # Kebab-cased + lowercase
        assert name == "2026-05-18-kaizen-md-abc"

    def test_invalid_date_raises(self):
        from superpower_bundle import bundle_folder_name, BundleError
        import pytest
        with pytest.raises(BundleError):
            bundle_folder_name("not-a-date", "p", None)


class TestInit(_BundleBase):
    def test_creates_folder(self):
        r = self._run("init", "--date", "2026-05-18",
                       "--project", "kaizen-md", "--sid", "6ebbb7cb")
        self.assertEqual(r.returncode, 0, r.stderr)
        folder = self.root / "2026-05-18-kaizen-md-6ebbb7cb"
        self.assertTrue(folder.is_dir())
        # Stub README explaining bundle scope
        self.assertTrue((folder / "README.md").is_file())

    def test_idempotent_on_rerun(self):
        for _ in range(3):
            r = self._run("init", "--date", "2026-05-18",
                           "--project", "kaizen-md", "--sid", "6ebbb7cb")
            self.assertEqual(r.returncode, 0)
        # Still exactly one folder, no errors
        folders = list(self.root.iterdir())
        self.assertEqual(len(folders), 1)

    def test_no_sid_creates_dateproject_only(self):
        r = self._run("init", "--date", "2026-05-17",
                       "--project", "kaizen-md")
        self.assertEqual(r.returncode, 0, r.stderr)
        folder = self.root / "2026-05-17-kaizen-md"
        self.assertTrue(folder.is_dir())


class TestList(_BundleBase):
    def test_lists_existing_bundles(self):
        self._run("init", "--date", "2026-05-17", "--project", "kaizen-md")
        self._run("init", "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc")
        self._run("init", "--date", "2026-05-18",
                   "--project", "clever-lama-mcp", "--sid", "def")
        r = self._run("list", "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(len(data), 3)
        names = {d["name"] for d in data}
        self.assertIn("2026-05-17-kaizen-md", names)
        self.assertIn("2026-05-18-kaizen-md-abc", names)
        self.assertIn("2026-05-18-clever-lama-mcp-def", names)

    def test_filter_by_project(self):
        self._run("init", "--date", "2026-05-18", "--project", "kaizen-md")
        self._run("init", "--date", "2026-05-18",
                   "--project", "clever-lama-mcp")
        r = self._run("list", "--project", "kaizen-md", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(len(data), 1)
        self.assertIn("kaizen-md", data[0]["name"])


class TestPath(_BundleBase):
    def test_path_for_existing(self):
        self._run("init", "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc")
        r = self._run("path", "--date", "2026-05-18",
                       "--project", "kaizen-md", "--sid", "abc")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.strip().endswith(
            "2026-05-18-kaizen-md-abc"))

    def test_path_for_nonexistent_still_prints(self):
        """path is a pure compute; doesn't require the folder to exist."""
        r = self._run("path", "--date", "2026-05-18",
                       "--project", "kaizen-md", "--sid", "abc")
        self.assertEqual(r.returncode, 0)
        self.assertIn("2026-05-18-kaizen-md-abc", r.stdout)


class TestAdd(_BundleBase):
    def test_moves_file_into_bundle(self):
        # Seed a "loose" file outside bundles
        src = self.tmp / "loose-spec.md"
        src.write_text("# spec\n")
        # Init the bundle
        self._run("init", "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc")
        # Move into it
        r = self._run("add", "--file", str(src),
                       "--date", "2026-05-18",
                       "--project", "kaizen-md", "--sid", "abc")
        self.assertEqual(r.returncode, 0, r.stderr)
        # File now lives in the bundle, with prefix-stripped name
        target = self.root / "2026-05-18-kaizen-md-abc" / "loose-spec.md"
        self.assertTrue(target.is_file())
        self.assertFalse(src.exists())   # original moved (not copied)

    def test_add_creates_bundle_if_absent(self):
        src = self.tmp / "spec.md"
        src.write_text("# x\n")
        r = self._run("add", "--file", str(src),
                       "--date", "2026-05-18",
                       "--project", "kaizen-md", "--sid", "abc")
        self.assertEqual(r.returncode, 0, r.stderr)
        bundle = self.root / "2026-05-18-kaizen-md-abc"
        self.assertTrue(bundle.is_dir())
        self.assertTrue((bundle / "spec.md").is_file())


if __name__ == "__main__":
    unittest.main()
