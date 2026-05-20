"""Crypto-hardening regression tests — backup tarball integrity.

brain_migrate.cmd_apply and path_migrate.cmd_apply write `.tar.gz`
backups before any data move. Without an integrity sidecar a
silently-corrupted or tampered backup at rollback time produces
broken state with no detection.

This test class:
  1. Confirms a `<tar>.sha256` sidecar is written next to each backup.
  2. Confirms rollback verifies the sidecar and REFUSES on mismatch.
  3. Confirms rollback REFUSES when the sidecar is missing entirely
     (an attacker could remove it; same protection).

Written test-first per TDD. Pre-fix these tests fail (no sidecar
exists; rollback happily extracts whatever bytes are there).
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ_DIR / "scripts/brain"))

def _seed_brain(root: Path) -> None:
    (root / "Notes").mkdir(parents=True)
    (root / "Persona.md").write_text("---\nname: Test\n---\nbody\n")
    (root / "Notes" / "n1.md").write_text("---\nname: N1\n---\nb\n")

def _seed_legacy_path_tree(root: Path) -> None:
    """Minimal pre-v1.39 layout for path_migrate to chew on."""
    (root / "trace").mkdir(parents=True)
    (root / "trace" / "events.jsonl").write_text('{"evt":"x"}\n')
    (root / "handoff.db").write_bytes(b"FAKEDB")

class _BrainBase(unittest.TestCase):
    """Sandbox for brain_migrate."""

    def setUp(self):
        self._outer = tempfile.TemporaryDirectory()
        self.outer = Path(self._outer.name)
        self.tmp = self.outer / "sandbox"
        self.tmp.mkdir()
        self.src = self.tmp / "src-brain"
        self.dst = self.tmp / "dst-brain"
        self.backup_dir = self.tmp / "backups"
        self.backup_dir.mkdir()
        self.settings = self.tmp / "settings.json"
        _seed_brain(self.src)
        # Reload to honor the sandboxed env
        for mod in ("_paths", "brain_migrate"):
            sys.modules.pop(mod, None)
        self._orig_env = dict(os.environ)
        # Brain default location uses _paths.BRAIN_DIR — we monkey-patch
        # bm._paths.BACKUP_DIR (and BRAIN_DIR via _BaseCase pattern from
        # test_brain_migrate). Simpler: just import + override.
        import _paths   # noqa: F401
        import brain_migrate as bm
        self.bm = bm
        self._orig_backup_dir = bm._paths.BACKUP_DIR
        self._orig_brain_dir = bm._paths.BRAIN_DIR
        bm._paths.BACKUP_DIR = self.backup_dir
        bm._paths.BRAIN_DIR = self.dst

    def tearDown(self):
        try:
            self.bm._paths.BACKUP_DIR = self._orig_backup_dir
            self.bm._paths.BRAIN_DIR = self._orig_brain_dir
        except Exception:
            pass
        for k in list(os.environ):
            if k.startswith("KAIZEN_") and k not in self._orig_env:
                os.environ.pop(k, None)
        os.environ.update(self._orig_env)
        for mod in ("_paths", "brain_migrate"):
            sys.modules.pop(mod, None)
        self._outer.cleanup()

    def _args(self, **kw):
        import argparse
        ns = argparse.Namespace(
            src=str(self.src), dst=str(self.dst),
            settings_file=str(self.settings), json=False,
            no_backup=False, no_settings=True, force_overwrite=False,
        )
        for k, v in kw.items():
            setattr(ns, k, v)
        return ns

class BrainBackupSidecar(_BrainBase):

    def test_apply_writes_sha256_sidecar_next_to_tarball(self):
        rc = self.bm.cmd_apply(self._args())
        self.assertEqual(rc, 0)
        backups = sorted(self.backup_dir.glob("brain-pre-migration-*.tar.gz"))
        self.assertEqual(len(backups), 1)
        sidecar = Path(str(backups[0]) + ".sha256")
        self.assertTrue(sidecar.is_file(),
                        f"missing integrity sidecar: {sidecar}")
        # Sidecar content is the hex-digest of the tarball
        expected = hashlib.sha256(backups[0].read_bytes()).hexdigest()
        self.assertEqual(sidecar.read_text().strip(), expected)

class BrainRollbackVerify(_BrainBase):
    """Rollback must verify the tarball matches its sha256 sidecar."""

    def setUp(self):
        super().setUp()
        # First apply to create a valid backup + sidecar
        self.bm.cmd_apply(self._args())
        # Locate the backup
        self.backup = sorted(self.backup_dir.glob(
            "brain-pre-migration-*.tar.gz"))[-1]
        self.sidecar = Path(str(self.backup) + ".sha256")

    def test_rollback_refuses_when_tarball_corrupted(self):
        # Corrupt the tarball after apply
        self.backup.write_bytes(b"GARBAGE-NOT-A-TARBALL")
        # Sidecar is now stale; rollback must refuse
        import argparse
        args = argparse.Namespace(
            src=str(self.src), dst=str(self.dst),
            settings_file=str(self.settings), json=False,
        )
        rc = self.bm.cmd_rollback(args)
        self.assertNotEqual(rc, 0,
                            "rollback must refuse corrupted tarball")
        # Original src dir should NOT be re-created (rollback aborted)
        self.assertFalse(self.src.exists())

    def test_rollback_refuses_when_sidecar_missing(self):
        # Attacker removes the sidecar to bypass verification
        self.sidecar.unlink()
        import argparse
        args = argparse.Namespace(
            src=str(self.src), dst=str(self.dst),
            settings_file=str(self.settings), json=False,
        )
        rc = self.bm.cmd_rollback(args)
        self.assertNotEqual(rc, 0,
                            "rollback must refuse when sidecar missing")

    def test_rollback_proceeds_when_sidecar_matches(self):
        import argparse
        args = argparse.Namespace(
            src=str(self.src), dst=str(self.dst),
            settings_file=str(self.settings), json=False,
        )
        rc = self.bm.cmd_rollback(args)
        self.assertEqual(rc, 0)
        self.assertTrue(self.src.exists())

class _PathBase(unittest.TestCase):
    """Sandbox for path_migrate."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.user_dir = self.tmp / ".kaizen"
        self.user_dir.mkdir()
        self.backup_dir = self.user_dir / "backups"
        self.backup_dir.mkdir()
        _seed_legacy_path_tree(self.user_dir)
        self._orig_env = dict(os.environ)
        os.environ["KAIZEN_DIR"] = str(self.user_dir)
        for mod in ("_paths", "path_migrate"):
            sys.modules.pop(mod, None)
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
        self._tmp.cleanup()

    def _args(self, **kw):
        import argparse
        ns = argparse.Namespace(json=False, no_backup=False,
                                  force_overwrite=False)
        for k, v in kw.items():
            setattr(ns, k, v)
        return ns

class PathBackupSidecar(_PathBase):

    def test_apply_writes_sha256_sidecar(self):
        rc = self.pm.cmd_apply(self._args())
        self.assertEqual(rc, 0)
        backups = sorted(self.backup_dir.glob("path-restructure-*.tar.gz"))
        self.assertEqual(len(backups), 1)
        sidecar = Path(str(backups[0]) + ".sha256")
        self.assertTrue(sidecar.is_file(),
                        f"missing integrity sidecar: {sidecar}")
        expected = hashlib.sha256(backups[0].read_bytes()).hexdigest()
        self.assertEqual(sidecar.read_text().strip(), expected)

class PathRollbackVerify(_PathBase):

    def setUp(self):
        super().setUp()
        self.pm.cmd_apply(self._args())
        self.backup = sorted(self.backup_dir.glob(
            "path-restructure-*.tar.gz"))[-1]
        self.sidecar = Path(str(self.backup) + ".sha256")

    def test_rollback_refuses_when_tarball_corrupted(self):
        self.backup.write_bytes(b"GARBAGE-NOT-A-TARBALL")
        rc = self.pm.cmd_rollback(self._args())
        self.assertNotEqual(rc, 0,
                            "path-migrate rollback must refuse corrupted tarball")

    def test_rollback_refuses_when_sidecar_missing(self):
        self.sidecar.unlink()
        rc = self.pm.cmd_rollback(self._args())
        self.assertNotEqual(rc, 0,
                            "path-migrate rollback must refuse when sidecar missing")

class SettingsBackupSidecar(_BrainBase):
    """CRYPTO-2: brain_migrate._edit_settings writes a `<bak>.sha256`
    sidecar so future rollbacks (manual or automated) can detect
    tampering between backup-write and restore."""

    def test_edit_settings_writes_sha256_sidecar(self):
        # Seed a settings.json with a legacy env var so _edit_settings
        # has something to mutate (otherwise it's a no-op skip)
        self.settings.write_text(
            '{"env": {"REMEMBER_BRAIN_PATH": "/legacy/brain"}}\n'
        )
        result = self.bm._edit_settings(self.settings, self.dst, self._args())
        self.assertTrue(result["edited"])
        bak = Path(result["backup"])
        self.assertTrue(bak.is_file())
        sidecar = Path(str(bak) + ".sha256")
        self.assertTrue(sidecar.is_file(),
                        f"missing integrity sidecar: {sidecar}")
        expected = hashlib.sha256(bak.read_bytes()).hexdigest()
        self.assertEqual(sidecar.read_text().strip(), expected)

    def test_edit_settings_sidecar_matches_original_pre_mutation_bytes(self):
        """The sidecar must hash the BACKUP (original pre-mutation
        bytes), not the post-mutation settings.json — otherwise a
        rollback would refuse against its own re-mutated content."""
        original = '{"env": {"REMEMBER_BRAIN_PATH": "/legacy"}}\n'
        self.settings.write_text(original)
        original_bytes = self.settings.read_bytes()
        result = self.bm._edit_settings(self.settings, self.dst, self._args())
        bak = Path(result["backup"])
        # Sidecar should validate against the backup's ORIGINAL bytes
        self.assertEqual(bak.read_bytes(), original_bytes)
        sidecar = Path(str(bak) + ".sha256")
        self.assertEqual(sidecar.read_text().strip(),
                         hashlib.sha256(original_bytes).hexdigest())

if __name__ == "__main__":
    unittest.main()
