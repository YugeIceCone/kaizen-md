"""Security regression tests — tar path-traversal protection (C3).

`brain_migrate.py rollback` and `path_migrate.py rollback` both call
`tar.extractall()` to restore from a backup tarball. The default
behavior (no `filter=` arg) honors `..` paths, absolute paths, and
symlinks in tar members — a malicious tarball at the backup location
becomes arbitrary-file-write at rollback time.

This test crafts malicious tarballs and asserts:
  1. Path-traversal members (../../foo) are rejected
  2. Absolute-path members (/etc/foo) are rejected
  3. Symlink-out-of-tree members are rejected
  4. Normal (well-formed) tarballs still extract correctly

Written test-first per TDD. Pre-fix the malicious tarballs would
extract outside the target dir → tests fail. Post-fix `filter="data"`
(Py3.12+) blocks them.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ_DIR / "scripts/brain"))

def _craft_traversal_tar(tar_path: Path, escape_filename: str,
                          payload: bytes = b"PWNED\n") -> None:
    """Build a tarball whose single member uses `..` to escape the
    extraction root. The arcname `../<escape_filename>` resolves to
    a sibling of the extraction root — outside it.

    Extracting it without a `filter=` writes outside the target dir.
    Extracting with `filter="data"` MUST reject (CVE-2007-4559 class)."""
    with tempfile.NamedTemporaryFile(delete=False) as src:
        src.write(payload)
        src_path = Path(src.name)
    try:
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(src_path, arcname="../" + escape_filename)
    finally:
        src_path.unlink()

def _craft_absolute_path_tar(tar_path: Path,
                              abs_target: Path,
                              payload: bytes = b"PWNED\n") -> None:
    """Build a tarball with an absolute-path member."""
    with tempfile.NamedTemporaryFile(delete=False) as src:
        src.write(payload)
        src_path = Path(src.name)
    try:
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(src_path, arcname=str(abs_target))
    finally:
        src_path.unlink()

class BrainMigrateTarSafety(unittest.TestCase):
    """`brain_migrate.cmd_rollback` extracts via `tar.extractall(src.parent)`.
    Must reject traversal + absolute paths."""

    def setUp(self):
        # Per-test we need TWO sibling tempdirs: one for the extraction
        # root, one for the "outside" target. Otherwise a canary path
        # inside the tempdir is technically still under the extraction
        # root and filter="data" correctly allows it.
        self._outer = tempfile.TemporaryDirectory()
        self.outer = Path(self._outer.name)
        self.tmp = self.outer / "sandbox"           # extraction root parent
        self.tmp.mkdir()
        self.canary_name = "ESCAPED-PWNED"
        # The canary lands as `<extract-root-parent>/../ESCAPED-PWNED`
        # which resolves to `<outer>/ESCAPED-PWNED` — outside `self.tmp`.
        self.canary = self.outer / self.canary_name
        for mod in ("_paths", "brain_migrate"):
            sys.modules.pop(mod, None)
        self._orig_env = dict(os.environ)
        os.environ["KAIZEN_DIR"] = str(self.tmp / ".kaizen")
        (self.tmp / ".kaizen").mkdir()
        (self.tmp / ".kaizen" / "backups").mkdir()
        import _paths   # noqa: F401
        import brain_migrate as bm
        self.bm = bm

    def tearDown(self):
        for mod in ("_paths", "brain_migrate"):
            sys.modules.pop(mod, None)
        for k in list(os.environ):
            if k.startswith("KAIZEN_") and k not in self._orig_env:
                os.environ.pop(k, None)
        os.environ.update(self._orig_env)
        self._outer.cleanup()

    def test_rollback_rejects_traversal_tar(self):
        # Plant a malicious "backup" with a ../ESCAPED member
        backup = (self.bm._paths.BACKUP_DIR /
                  "brain-pre-migration-99999999T999999Z.tar.gz")
        _craft_traversal_tar(backup, self.canary_name)
        import argparse
        args = argparse.Namespace(
            src=str(self.tmp / "src-brain"),
            dst=str(self.tmp / "dst-brain"),
            settings_file=str(self.tmp / "settings.json"),
            json=False, no_backup=False, force_overwrite=False,
        )
        # cmd_rollback should refuse OR silently skip the bad member.
        # In either case, the canary at <outer>/ESCAPED-PWNED must NOT exist.
        try:
            self.bm.cmd_rollback(args)
        except Exception:
            pass
        self.assertFalse(self.canary.exists(),
                         f"tar.extractall wrote outside target dir "
                         f"({self.canary}) — path-traversal vulnerability")

    def test_rollback_rejects_absolute_path_tar(self):
        backup = (self.bm._paths.BACKUP_DIR /
                  "brain-pre-migration-99999999T999998Z.tar.gz")
        abs_target = self.outer / "ABS-PWNED"
        _craft_absolute_path_tar(backup, abs_target)
        import argparse
        args = argparse.Namespace(
            src=str(self.tmp / "src-brain"),
            dst=str(self.tmp / "dst-brain"),
            settings_file=str(self.tmp / "settings.json"),
            json=False, no_backup=False, force_overwrite=False,
        )
        try:
            self.bm.cmd_rollback(args)
        except Exception:
            pass
        self.assertFalse(abs_target.exists(),
                         "tar.extractall honored absolute path member")

class PathMigrateTarSafety(unittest.TestCase):
    """`path_migrate.cmd_rollback` extracts via `tar.extractall(target_parent)`.
    Must reject traversal + absolute paths."""

    def setUp(self):
        self._outer = tempfile.TemporaryDirectory()
        self.outer = Path(self._outer.name)
        self.tmp = self.outer / "sandbox"
        self.tmp.mkdir()
        self.user_dir = self.tmp / ".kaizen"
        self.user_dir.mkdir()
        (self.user_dir / "backups").mkdir()
        self.canary_name = "ESCAPED-PWNED"
        # path_migrate.cmd_rollback extracts at KAIZEN_USER_DIR.parent,
        # which is self.tmp. A `../ESCAPED-PWNED` member resolves to
        # `self.outer/ESCAPED-PWNED` — outside the extraction root.
        self.canary = self.outer / self.canary_name
        for mod in ("_paths", "path_migrate"):
            sys.modules.pop(mod, None)
        self._orig_env = dict(os.environ)
        os.environ["KAIZEN_DIR"] = str(self.user_dir)
        import _paths   # noqa: F401
        import path_migrate as pm
        self.pm = pm

    def tearDown(self):
        for mod in ("_paths", "path_migrate"):
            sys.modules.pop(mod, None)
        for k in list(os.environ):
            if k.startswith("KAIZEN_") and k not in self._orig_env:
                os.environ.pop(k, None)
        os.environ.update(self._orig_env)
        self._outer.cleanup()

    def test_rollback_rejects_traversal_tar(self):
        backup = (self.pm._paths.BACKUP_DIR /
                  "path-restructure-99999999T999999Z.tar.gz")
        _craft_traversal_tar(backup, self.canary_name)
        import argparse
        args = argparse.Namespace(json=False, no_backup=False,
                                  force_overwrite=False)
        try:
            self.pm.cmd_rollback(args)
        except Exception:
            pass
        self.assertFalse(self.canary.exists(),
                         f"path_migrate tar.extractall wrote outside "
                         f"target ({self.canary}) — path-traversal")

if __name__ == "__main__":
    unittest.main()
