"""Tests for kaizen-bundle scan — artifact tracker for the superpowers path.

Per user 2026-05-18: scan the assigned artifacts path (docs/superpowers/)
for orphan files (not yet inside a bundle folder), report metadata
(suggested target bundle + content-hash dupe check), optionally create
a git branch for the bundling pass + apply moves.

  kaizen-bundle scan [--apply] [--branch <name>]
                     # default: dry-run report; no mutations
                     # --apply: move orphans into target bundles
                     # --branch: create a git branch in nested repo before moving
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_BUNDLE_PY = _KZ_DIR / "skills/workflow/scripts/superpower_bundle.py"


class _ScanBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "superpowers"
        self.root.mkdir()
        self.backup = self.tmp / "backup"
        self.backup.mkdir()
        self._orig = os.environ.get("KAIZEN_SUPERPOWERS_DIR")
        self._orig_bk = os.environ.get("KAIZEN_BACKUP_DIR")
        os.environ["KAIZEN_SUPERPOWERS_DIR"] = str(self.root)
        os.environ["KAIZEN_BACKUP_DIR"] = str(self.backup)
        for k, v in (("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_AUTHOR_NAME", "t"),
                      ("GIT_COMMITTER_EMAIL", "t@t"),
                      ("GIT_COMMITTER_NAME", "t")):
            os.environ.setdefault(k, v)

    def tearDown(self):
        self._tmp.cleanup()
        for var, orig in (("KAIZEN_SUPERPOWERS_DIR", self._orig),
                           ("KAIZEN_BACKUP_DIR", self._orig_bk)):
            if orig is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = orig

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_BUNDLE_PY), *args],
            capture_output=True, text=True, timeout=20,
            env=os.environ.copy(),
        )


class TestScanEmpty(_ScanBase):
    def test_no_orphans_no_bundles(self):
        r = self._run("scan", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["orphans"], [])
        self.assertEqual(data["dupes"], [])

    def test_no_orphans_with_bundles(self):
        # Existing bundle with content → not an orphan
        bundle = self.root / "2026-05-18-kaizen-md-abc"
        bundle.mkdir()
        (bundle / "spec.md").write_text("# x\n")
        r = self._run("scan", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["orphans"], [])


class TestScanFindsOrphans(_ScanBase):
    def test_top_level_md_is_orphan(self):
        # Loose file at root — not in any bundle
        (self.root / "loose-spec.md").write_text("# loose\n")
        r = self._run("scan", "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(len(data["orphans"]), 1)
        orphan = data["orphans"][0]
        self.assertEqual(orphan["name"], "loose-spec.md")
        self.assertIn("size", orphan)
        self.assertIn("sha256", orphan)

    def test_readme_and_templates_skipped(self):
        # README.md at root is the convention spec — not an orphan
        (self.root / "README.md").write_text("# docs\n")
        # templates/ dir is durable; contents not orphans
        (self.root / "templates").mkdir()
        (self.root / "templates" / "loose.md").write_text("# tpl\n")
        r = self._run("scan", "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["orphans"], [],
                          f"unexpected orphans: {data['orphans']}")


class TestSuggestedTarget(_ScanBase):
    def test_date_prefix_in_filename_drives_target(self):
        # File with YYYY-MM-DD prefix → that date suggests the bundle
        (self.root / "2026-05-17-something.md").write_text("# x\n")
        r = self._run("scan", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(len(data["orphans"]), 1)
        self.assertEqual(data["orphans"][0]["suggested_date"], "2026-05-17")

    def test_no_date_falls_back_to_mtime(self):
        # No prefix → mtime drives the suggestion
        p = self.root / "untagged.md"
        p.write_text("# x\n")
        r = self._run("scan", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(len(data["orphans"]), 1)
        # Mtime fallback — has SOME date suggestion (today)
        self.assertIn("suggested_date", data["orphans"][0])


class TestDupeDetection(_ScanBase):
    def test_orphan_with_matching_content_in_bundle_flagged_dupe(self):
        # Existing bundle with a file
        bundle = self.root / "2026-05-18-kaizen-md-abc"
        bundle.mkdir()
        content = "# duplicate content\n"
        (bundle / "spec.md").write_text(content)
        # Orphan with identical bytes
        (self.root / "loose-spec.md").write_text(content)
        r = self._run("scan", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(len(data["dupes"]), 1)
        dupe = data["dupes"][0]
        self.assertEqual(dupe["orphan"], "loose-spec.md")
        self.assertEqual(dupe["bundle"], "2026-05-18-kaizen-md-abc")
        self.assertEqual(dupe["bundle_file"], "spec.md")

    def test_different_content_no_dupe(self):
        bundle = self.root / "2026-05-18-kaizen-md-abc"
        bundle.mkdir()
        (bundle / "spec.md").write_text("# A\n")
        (self.root / "loose.md").write_text("# B\n")
        r = self._run("scan", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(data["dupes"], [])


class TestDryRunIsDefault(_ScanBase):
    def test_dry_run_no_mutations(self):
        (self.root / "loose.md").write_text("# x\n")
        r = self._run("scan", "--json")
        self.assertEqual(r.returncode, 0)
        # Orphan file STILL at root after dry run
        self.assertTrue((self.root / "loose.md").is_file())


if __name__ == "__main__":
    unittest.main()
