"""Tests for path_migrate.py — v1.38 → v1.39 layout restructure.

Written test-first (TDD). The migrator handles 10 concurrent moves:
4 search dirs into indexes/, 1 multi-file daemon dir + 4 singletons
into data/, snapshot dir hoist, _legacy → archive rename.

Sandbox-isolated: every test uses a tempdir as the fake user-global
root. No KAIZEN_DIR is set globally — each _BaseCase sets it for the
duration of the test, plus monkey-patches `_paths.KAIZEN_USER_DIR` +
the derived constants so the migrator sees the sandbox.
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
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
sys.path.insert(0, str(_SCRIPTS))


def _seed_legacy_tree(root: Path) -> None:
    """Populate the v1.38 sibling layout under `root` (acting as
    ~/.claude/.kaizen/)."""
    # 4 search dirs
    for name in ("trace", "knowledge", "scrape", "claude-docs"):
        d = root / name
        d.mkdir(parents=True)
        (d / "index.db").write_bytes(b"FAKEDB" + name.encode())
    (root / "trace" / "events.jsonl").write_text('{"evt":"test"}\n')
    (root / "claude-docs" / "src").mkdir()
    (root / "claude-docs" / "src" / "doc.md").write_text("# doc\n")
    # daemon (multi-file)
    d = root / "daemon"
    d.mkdir()
    (d / "state.json").write_text('{"running":false}')
    (d / "log").write_text("log line\n")
    (d / "watcher.pid").write_text("12345\n")
    # singletons
    (root / "handoff.db").write_bytes(b"FAKEHANDOFF")
    (root / "manifest.json").write_text('{"plugins":[]}')
    (root / "manifest.lock").write_text("")
    (root / "profile.env").write_text("FOO=bar\n")
    # observe snapshots (nested)
    sn = root / "observe" / "snapshots"
    sn.mkdir(parents=True)
    (sn / "snap1.json").write_text('{"snap":"1"}')
    # _legacy
    leg = root / "_legacy"
    leg.mkdir()
    (leg / "old.txt").write_text("legacy")


class _BaseCase(unittest.TestCase):
    """Per-test sandbox. Sets KAIZEN_DIR to a tempdir, reloads
    _paths.py so all the derived constants point at the sandbox, and
    restores on tearDown."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.user_dir = self.tmp / ".kaizen"
        self.user_dir.mkdir()
        self.backup_dir = self.user_dir / "backups"
        self.backup_dir.mkdir()
        # Override env BEFORE reloading _paths so its module-level
        # constants pick up the new KAIZEN_DIR
        self._orig_env = dict(os.environ)
        os.environ.pop("KAIZEN_DIR", None)
        os.environ["KAIZEN_DIR"] = str(self.user_dir)
        # Drop ALL feature-level overrides so umbrellas resolve
        for k in list(os.environ):
            if k.startswith("KAIZEN_") and k.endswith(("_DIR", "_DB",
                                                         "_JSON", "_LOCK",
                                                         "_ENV", "_FILE",
                                                         "_PATH")):
                if k != "KAIZEN_DIR":
                    os.environ.pop(k, None)
        # Force reload of _paths + path_migrate so the new env wins
        for mod in ("_paths", "path_migrate"):
            sys.modules.pop(mod, None)
        import _paths  # noqa: F401
        import path_migrate as pm  # noqa: F401
        self.pm = pm
        self._paths = _paths

    def tearDown(self):
        # Restore env
        for k in list(os.environ):
            if k.startswith("KAIZEN_") and k not in self._orig_env:
                os.environ.pop(k, None)
        os.environ.update(self._orig_env)
        # Drop the reloaded modules so the next test's reload is clean
        for mod in ("_paths", "path_migrate"):
            sys.modules.pop(mod, None)
        self._tmp.cleanup()

    def _args(self, **kw):
        import argparse
        ns = argparse.Namespace(
            json=False, no_backup=False, force_overwrite=False,
        )
        for k, v in kw.items():
            setattr(ns, k, v)
        return ns


# ─── Status classification ───────────────────────────────────────────


class StatusFlow(_BaseCase):

    def test_status_neither_when_empty(self):
        rc = self.pm.cmd_status(self._args())
        self.assertEqual(rc, 0)

    def test_status_needs_migration_when_legacy_present(self):
        _seed_legacy_tree(self.user_dir)
        from io import StringIO
        from contextlib import redirect_stdout
        buf = StringIO()
        with redirect_stdout(buf):
            self.pm.cmd_status(self._args())
        out = buf.getvalue()
        # At least one move should be classified as needing migration
        self.assertIn("needs-migration", out)

    def test_status_already_migrated_when_targets_exist(self):
        # Seed targets at NEW locations only (no legacy)
        (self.user_dir / "indexes" / "trace").mkdir(parents=True)
        (self.user_dir / "indexes" / "trace" / "index.db").write_bytes(b"x")
        (self.user_dir / "data").mkdir()
        (self.user_dir / "data" / "handoff.db").write_bytes(b"x")
        rc = self.pm.cmd_status(self._args(json=True))
        self.assertEqual(rc, 0)
        # JSON envelope output: assert per-move row, not substring search
        # (the summary dict includes 'needs-migration' as a KEY even when 0)
        from io import StringIO
        import json as _json
        from contextlib import redirect_stdout
        buf = StringIO()
        with redirect_stdout(buf):
            self.pm.cmd_status(self._args(json=True))
        out = _json.loads(buf.getvalue())
        self.assertEqual(out["data"]["summary"]["needs-migration"], 0,
                         "no moves should need migration")


# ─── Apply flow ──────────────────────────────────────────────────────


class ApplyFlow(_BaseCase):

    def test_apply_moves_all_legacy_into_umbrellas(self):
        _seed_legacy_tree(self.user_dir)
        rc = self.pm.cmd_apply(self._args())
        self.assertEqual(rc, 0)
        # Search dirs gone from root, present under indexes/
        for name in ("trace", "knowledge", "scrape", "claude-docs"):
            self.assertFalse((self.user_dir / name).exists(),
                             f"legacy {name} should be gone from root")
            self.assertTrue((self.user_dir / "indexes" / name).is_dir(),
                            f"new indexes/{name} should exist")
        # Daemon moved to data/daemon
        self.assertFalse((self.user_dir / "daemon").exists())
        self.assertTrue((self.user_dir / "data" / "daemon").is_dir())
        # Singletons moved to data/
        for fname in ("handoff.db", "manifest.json",
                      "manifest.lock", "profile.env"):
            self.assertFalse((self.user_dir / fname).exists(),
                             f"legacy {fname} should be gone")
            self.assertTrue((self.user_dir / "data" / fname).is_file(),
                            f"data/{fname} should exist")
        # Snapshots hoisted
        self.assertFalse((self.user_dir / "observe").exists())
        self.assertTrue((self.user_dir / "snapshots").is_dir())
        # _legacy renamed to archive
        self.assertFalse((self.user_dir / "_legacy").exists())
        self.assertTrue((self.user_dir / "archive").is_dir())

    def test_apply_preserves_file_content(self):
        _seed_legacy_tree(self.user_dir)
        self.pm.cmd_apply(self._args())
        # Spot-check content survived rsync
        self.assertEqual(
            (self.user_dir / "data" / "manifest.json").read_text(),
            '{"plugins":[]}')
        self.assertEqual(
            (self.user_dir / "data" / "profile.env").read_text(),
            "FOO=bar\n")
        self.assertEqual(
            (self.user_dir / "indexes" / "trace" / "events.jsonl")
                .read_text(),
            '{"evt":"test"}\n')

    def test_apply_creates_full_tree_backup(self):
        _seed_legacy_tree(self.user_dir)
        self.pm.cmd_apply(self._args())
        backups = list(self.backup_dir.glob("path-restructure-*.tar.gz"))
        self.assertEqual(len(backups), 1)
        # Sanity: tarball is non-empty
        self.assertGreater(backups[0].stat().st_size, 100)

    def test_apply_no_backup_flag_skips_tar(self):
        _seed_legacy_tree(self.user_dir)
        self.pm.cmd_apply(self._args(no_backup=True))
        backups = list(self.backup_dir.glob("path-restructure-*.tar.gz"))
        self.assertEqual(len(backups), 0)

    def test_apply_refuses_per_move_conflict_without_force(self):
        """If both src AND dst have data for a single move,
        refuse the whole apply unless --force-overwrite."""
        _seed_legacy_tree(self.user_dir)
        # Pre-populate dst for one of the moves (indexes/trace/)
        (self.user_dir / "indexes" / "trace").mkdir(parents=True)
        (self.user_dir / "indexes" / "trace" / "conflict.db").write_bytes(b"X")
        rc = self.pm.cmd_apply(self._args())
        self.assertEqual(rc, 1)
        # Nothing should have moved
        self.assertTrue((self.user_dir / "trace").exists())
        self.assertTrue((self.user_dir / "indexes" / "trace" / "conflict.db")
                        .is_file())

    def test_apply_force_overwrite_merges_per_move(self):
        _seed_legacy_tree(self.user_dir)
        (self.user_dir / "indexes" / "trace").mkdir(parents=True)
        (self.user_dir / "indexes" / "trace" / "dst-only.db").write_bytes(b"X")
        rc = self.pm.cmd_apply(self._args(force_overwrite=True))
        self.assertEqual(rc, 0)
        # Both src content + dst-only survive
        self.assertTrue((self.user_dir / "indexes" / "trace" / "index.db").is_file())
        self.assertTrue((self.user_dir / "indexes" / "trace" / "dst-only.db").is_file())

    def test_apply_idempotent_when_no_legacy(self):
        # First apply
        _seed_legacy_tree(self.user_dir)
        self.pm.cmd_apply(self._args())
        # Second apply: no-op
        rc = self.pm.cmd_apply(self._args())
        self.assertEqual(rc, 0)

    def test_apply_noop_when_neither_src_nor_dst(self):
        # Empty user_dir entirely
        rc = self.pm.cmd_apply(self._args())
        self.assertEqual(rc, 0)


# ─── Rollback ────────────────────────────────────────────────────────


class RollbackFlow(_BaseCase):

    def test_rollback_restores_from_backup_tar(self):
        _seed_legacy_tree(self.user_dir)
        self.pm.cmd_apply(self._args())
        # Confirm migration happened
        self.assertTrue((self.user_dir / "indexes" / "trace").is_dir())
        self.assertFalse((self.user_dir / "trace").exists())
        # Rollback
        rc = self.pm.cmd_rollback(self._args())
        self.assertEqual(rc, 0)
        # Legacy locations should be back
        self.assertTrue((self.user_dir / "trace" / "index.db").is_file())
        self.assertTrue((self.user_dir / "handoff.db").is_file())

    def test_rollback_fails_with_no_backup(self):
        rc = self.pm.cmd_rollback(self._args())
        self.assertEqual(rc, 1)


# ─── JSON envelope output ────────────────────────────────────────────


class EnvelopeOutput(_BaseCase):

    def _run(self, *argv):
        script = _SCRIPTS / "path_migrate.py"
        return subprocess.run(
            ["python3", str(script), *argv],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "KAIZEN_DIR": str(self.user_dir)},
        )

    def test_status_json_envelope(self):
        _seed_legacy_tree(self.user_dir)
        r = self._run("status", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["kaizen"]["tool"], "kaizen-migrate path")
        self.assertIn("data", out)
        self.assertIn("moves", out["data"])

    def test_apply_json_envelope(self):
        _seed_legacy_tree(self.user_dir)
        r = self._run("apply", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["verdict"], "green")
        self.assertIn("moved", out["data"])


if __name__ == "__main__":
    unittest.main()
