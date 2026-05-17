"""Tests for brain_migrate.py — relocation of the Second Brain.

Sandbox-isolated: every test runs against tempdir src + dst + settings
files. No KAIZEN_BRAIN_DIR is set globally — each test passes --src/
--dst explicitly.

Covers:
  - status classification (needs-migration / already-migrated /
    both-have-data / neither)
  - dry-run prints actions, mutates nothing
  - apply: backup tarball created, rsync copies + verifies, src
    unlinked on success
  - apply: refuses on both-have-data unless --force-overwrite
  - apply: --no-backup / --no-settings flags honored
  - rollback restores src from latest backup, rescues dst
  - settings.json edit: legacy envs dropped, KAIZEN_BRAIN_DIR set only
    when non-default, atomic write, backup-first
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))

import brain_migrate as bm  # noqa: E402


def _seed_brain(root: Path, n_notes: int = 3) -> None:
    """Create a minimal brain tree."""
    (root / "Notes").mkdir(parents=True)
    (root / "Projects").mkdir()
    (root / "People").mkdir()
    (root / "Persona.md").write_text(
        "---\nname: Test User\n---\n\n# Persona\n\nTest profile.\n"
    )
    for i in range(n_notes):
        (root / "Notes" / f"note-{i}.md").write_text(
            f"---\nname: Note {i}\ntype: belief\n---\n\n# Note {i}\n\nbody\n"
        )


class _BaseCase(unittest.TestCase):
    """Per-test tempdir for src, dst, backup, settings."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.src = self.tmp / "src-brain"
        self.dst = self.tmp / "dst-brain"
        self.backup_dir = self.tmp / "backups"
        self.settings = self.tmp / "settings.json"
        # Redirect brain_migrate's backup writes into our tempdir
        self._orig_backup_dir = bm._paths.BACKUP_DIR
        bm._paths.BACKUP_DIR = self.backup_dir
        # Redirect BRAIN_DIR default so settings-mutation default-detection
        # uses dst (avoid touching ~/.claude/.kaizen/brain in tests)
        self._orig_brain_dir = bm._paths.BRAIN_DIR
        bm._paths.BRAIN_DIR = self.dst

    def tearDown(self):
        bm._paths.BACKUP_DIR = self._orig_backup_dir
        bm._paths.BRAIN_DIR = self._orig_brain_dir
        self._tmp.cleanup()

    def _args(self, **kw):
        """Build an argparse Namespace with the test paths defaulted in."""
        import argparse
        ns = argparse.Namespace(
            src=str(self.src), dst=str(self.dst),
            settings_file=str(self.settings), json=False,
            no_backup=False, no_settings=False, force_overwrite=False,
        )
        for k, v in kw.items():
            setattr(ns, k, v)
        return ns


# ─── State classification ────────────────────────────────────────────


class StateClassification(_BaseCase):

    def test_neither_when_nothing_exists(self):
        rc = bm.cmd_status(self._args())
        self.assertEqual(rc, 0)

    def test_needs_migration_when_only_src(self):
        _seed_brain(self.src)
        # capture stdout
        from io import StringIO
        from contextlib import redirect_stdout
        buf = StringIO()
        with redirect_stdout(buf):
            bm.cmd_status(self._args())
        self.assertIn("needs-migration", buf.getvalue())

    def test_already_migrated_when_only_dst(self):
        _seed_brain(self.dst)
        from io import StringIO
        from contextlib import redirect_stdout
        buf = StringIO()
        with redirect_stdout(buf):
            bm.cmd_status(self._args())
        self.assertIn("already-migrated", buf.getvalue())

    def test_both_have_data(self):
        _seed_brain(self.src)
        _seed_brain(self.dst, n_notes=1)
        from io import StringIO
        from contextlib import redirect_stdout
        buf = StringIO()
        with redirect_stdout(buf):
            bm.cmd_status(self._args())
        self.assertIn("both-have-data", buf.getvalue())


# ─── Apply flow ──────────────────────────────────────────────────────


class ApplyFlow(_BaseCase):

    def test_apply_migrates_when_only_src(self):
        _seed_brain(self.src, n_notes=5)
        src_count = sum(1 for _ in self.src.rglob("*") if _.is_file())
        rc = bm.cmd_apply(self._args())
        self.assertEqual(rc, 0)
        self.assertFalse(self.src.exists())
        dst_count = sum(1 for _ in self.dst.rglob("*") if _.is_file())
        self.assertEqual(dst_count, src_count)
        # Backup tarball exists
        backups = list(self.backup_dir.glob("brain-pre-migration-*.tar.gz"))
        self.assertEqual(len(backups), 1)

    def test_apply_noop_when_only_dst(self):
        _seed_brain(self.dst)
        rc = bm.cmd_apply(self._args())
        self.assertEqual(rc, 0)  # no-op

    def test_apply_refuses_both_have_data_without_force(self):
        _seed_brain(self.src)
        _seed_brain(self.dst, n_notes=1)
        rc = bm.cmd_apply(self._args())
        self.assertEqual(rc, 1)
        # Both untouched
        self.assertTrue(self.src.exists())
        self.assertTrue(self.dst.exists())

    def test_apply_merges_with_force_overwrite(self):
        _seed_brain(self.src, n_notes=3)
        # dst has one unique file not in src
        self.dst.mkdir()
        (self.dst / "Projects").mkdir()
        (self.dst / "Projects" / "dst-only.md").write_text("dst unique\n")
        rc = bm.cmd_apply(self._args(force_overwrite=True))
        self.assertEqual(rc, 0)
        # Src gone
        self.assertFalse(self.src.exists())
        # dst-only file survived
        self.assertTrue((self.dst / "Projects" / "dst-only.md").is_file())
        # src content present
        self.assertTrue((self.dst / "Notes" / "note-0.md").is_file())

    def test_apply_with_no_backup(self):
        _seed_brain(self.src)
        rc = bm.cmd_apply(self._args(no_backup=True))
        self.assertEqual(rc, 0)
        backups = list(self.backup_dir.glob("brain-pre-migration-*.tar.gz"))
        self.assertEqual(len(backups), 0)

    def test_apply_noop_when_neither(self):
        rc = bm.cmd_apply(self._args())
        self.assertEqual(rc, 0)  # no-op, exit 0


# ─── Rollback ────────────────────────────────────────────────────────


class RollbackFlow(_BaseCase):

    def test_rollback_restores_src_from_backup(self):
        _seed_brain(self.src, n_notes=4)
        bm.cmd_apply(self._args(no_settings=True))
        self.assertFalse(self.src.exists())
        # Now rollback
        rc = bm.cmd_rollback(self._args())
        self.assertEqual(rc, 0)
        self.assertTrue(self.src.exists())
        self.assertTrue((self.src / "Persona.md").is_file())

    def test_rollback_fails_with_no_backup(self):
        rc = bm.cmd_rollback(self._args())
        self.assertEqual(rc, 1)


# ─── Settings.json mutation ──────────────────────────────────────────


class SettingsMutation(_BaseCase):

    def _write_settings(self, payload: dict):
        self.settings.write_text(json.dumps(payload, indent=2) + "\n")

    def test_drops_legacy_envs_and_sets_kaizen_brain_dir(self):
        self._write_settings({
            "env": {
                "REMEMBER_BRAIN_PATH": "/legacy/brain",
                "KAIZEN_BRAIN_PATH": "/intermediate/brain",
                "KAIZEN_BRAIN": "/short/brain",
                "OTHER_KEY": "stays",
            },
            "permissions": {"allow": ["Bash(*)"]},
        })
        # dst != default so KAIZEN_BRAIN_DIR should be set
        result = bm._edit_settings(self.settings, self.dst, self._args())
        self.assertTrue(result["edited"])
        loaded = json.loads(self.settings.read_text())
        self.assertEqual(loaded["env"]["KAIZEN_BRAIN_DIR"], str(self.dst))
        self.assertNotIn("REMEMBER_BRAIN_PATH", loaded["env"])
        self.assertNotIn("KAIZEN_BRAIN_PATH", loaded["env"])
        self.assertNotIn("KAIZEN_BRAIN", loaded["env"])
        self.assertEqual(loaded["env"]["OTHER_KEY"], "stays")
        self.assertEqual(loaded["permissions"], {"allow": ["Bash(*)"]})

    def test_omits_kaizen_brain_dir_when_dst_is_default(self):
        self._write_settings({
            "env": {"REMEMBER_BRAIN_PATH": "/legacy/brain"},
        })
        # default location → no env var needed
        default_dst = Path.home() / ".claude" / ".kaizen" / "brain"
        result = bm._edit_settings(self.settings, default_dst, self._args())
        self.assertTrue(result["edited"])
        loaded = json.loads(self.settings.read_text())
        # env should be empty / removed
        self.assertNotIn("KAIZEN_BRAIN_DIR", loaded.get("env", {}))
        self.assertNotIn("REMEMBER_BRAIN_PATH", loaded.get("env", {}))

    def test_backup_created_before_write(self):
        self._write_settings({"env": {"REMEMBER_BRAIN_PATH": "/x"}})
        bm._edit_settings(self.settings, self.dst, self._args())
        # Count only .json backups (not the .sha256 sidecars added by CRYPTO-2)
        bks = [p for p in self.settings.parent.glob(self.settings.name + ".bak-*")
               if not p.name.endswith(".sha256")]
        self.assertEqual(len(bks), 1)

    def test_no_change_skips_write_and_backup(self):
        # Settings already in target state — no rewrite needed
        self._write_settings({"env": {"KAIZEN_BRAIN_DIR": str(self.dst)}})
        result = bm._edit_settings(self.settings, self.dst, self._args())
        self.assertFalse(result["edited"])
        self.assertTrue(result["skipped"])
        # Neither the .json backup nor its .sha256 sidecar should remain
        bks = list(self.settings.parent.glob(self.settings.name + ".bak-*"))
        self.assertEqual(len(bks), 0)

    def test_missing_settings_file_skipped(self):
        # No settings file at all
        result = bm._edit_settings(self.settings, self.dst, self._args())
        self.assertFalse(result["edited"])
        self.assertTrue(result["skipped"])


# ─── CLI smoke ───────────────────────────────────────────────────────


class CliSmoke(_BaseCase):

    def _run(self, *argv):
        script = _KZ_DIR / "skills/workflow/scripts/brain_migrate.py"
        return subprocess.run(
            ["python3", str(script), *argv,
             "--src", str(self.src), "--dst", str(self.dst),
             "--settings-file", str(self.settings)],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "KAIZEN_DIR": str(self.tmp / "kaizen-dir")},
        )

    def test_status_json_envelope(self):
        _seed_brain(self.src)
        r = self._run("status", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["kaizen"]["tool"], "kaizen-brain-migrate")
        self.assertEqual(out["data"]["state"], "needs-migration")
        self.assertEqual(out["verdict"], "yellow")

    def test_dry_run_does_not_mutate(self):
        _seed_brain(self.src)
        r = self._run("dry-run")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(self.src.exists())
        self.assertFalse(self.dst.exists())


# ─── TDD discipline pass — RED-first tests for edge cases ────────────
#
# Phase 4 was initially built test+impl in parallel, not strict TDD.
# This class catches up: each test was authored as a behavioral
# contract first. Some failed against the initial impl → impl
# tightened; others passed (the impl had already covered them).


class Phase4EdgeCases(_BaseCase):
    """Edge cases that should hold but weren't covered in the
    happy-path apply/rollback/settings tests above."""

    # --- rsync / verify failure paths ----------------------------------

    def test_apply_rsync_failure_leaves_src_intact_and_returns_4(self):
        """If rsync fails, apply must NOT unlink src (data loss risk).
        Exit code is documented as 4 in the module docstring."""
        _seed_brain(self.src)
        original = bm._rsync_dir
        bm._rsync_dir = lambda src, dst, args: False  # force failure
        try:
            rc = bm.cmd_apply(self._args(no_settings=True))
        finally:
            bm._rsync_dir = original
        self.assertEqual(rc, 4)
        self.assertTrue(self.src.exists(),
                        "src must not be unlinked when rsync fails")

    def test_apply_verify_failure_leaves_src_intact_and_returns_2(self):
        """If post-copy verify mismatches, apply must NOT unlink src.
        Exit code is documented as 2."""
        _seed_brain(self.src)
        # Real rsync runs, but we force verify to report failure
        original = bm._verify_dirs
        bm._verify_dirs = lambda src, dst: {
            "ok": False, "reason": "synthetic failure",
            "dst_files": 0, "dst_size": 0,
        }
        try:
            rc = bm.cmd_apply(self._args(no_settings=True))
        finally:
            bm._verify_dirs = original
        self.assertEqual(rc, 2)
        self.assertTrue(self.src.exists(),
                        "src must survive verify failure")

    def test_apply_backup_failure_returns_3(self):
        """If tarball backup fails (e.g. unwritable dir), apply must
        not proceed. Exit code 3 per the docstring."""
        _seed_brain(self.src)
        original = bm._backup_src
        bm._backup_src = lambda src, args: None  # force failure
        try:
            rc = bm.cmd_apply(self._args())
        finally:
            bm._backup_src = original
        self.assertEqual(rc, 3)
        self.assertTrue(self.src.exists())
        self.assertFalse(self.dst.exists())

    # --- _verify_dirs unit tests --------------------------------------

    def test_verify_dirs_passes_on_exact_match(self):
        _seed_brain(self.src)
        _seed_brain(self.dst, n_notes=3)  # _seed_brain default = 3
        result = bm._verify_dirs(self.src, self.dst)
        self.assertTrue(result["ok"], result.get("reason"))

    def test_verify_dirs_fails_on_count_mismatch(self):
        _seed_brain(self.src, n_notes=5)
        _seed_brain(self.dst, n_notes=2)
        result = bm._verify_dirs(self.src, self.dst)
        self.assertFalse(result["ok"])
        # _migrator.verify_dir reports per-file misses ("missing at dst:
        # ...") rather than a count summary — more actionable.
        self.assertTrue(
            "missing at dst" in result["reason"]
            or "file count" in result["reason"],
            f"unexpected reason: {result['reason']!r}",
        )

    def test_verify_dirs_fails_on_size_loss_over_1pct(self):
        # Synthesize size mismatch: src has 1 large file, dst has 1 tiny
        self.src.mkdir()
        self.dst.mkdir()
        (self.src / "big.bin").write_bytes(b"x" * 10000)
        (self.dst / "big.bin").write_bytes(b"x" * 100)  # 99% loss
        result = bm._verify_dirs(self.src, self.dst)
        self.assertFalse(result["ok"])
        self.assertIn("size mismatch", result["reason"])

    # --- Settings.json malformed/edge cases ---------------------------

    def test_settings_unparseable_json_does_not_corrupt(self):
        """If settings.json is unparseable, edit_settings must return
        an error result AND not modify the file. The backup must still
        be created (so the user has a copy of the bad file)."""
        self.settings.write_text("{ this is not valid json }")
        original = self.settings.read_text()
        result = bm._edit_settings(self.settings, self.dst, self._args())
        self.assertFalse(result["edited"])
        self.assertIn("error", result)
        self.assertEqual(self.settings.read_text(), original,
                         "file must be untouched on parse failure")
        # Backup was made before parse attempted (one .json + sidecar)
        bks = [p for p in self.settings.parent.glob(self.settings.name + ".bak-*")
               if not p.name.endswith(".sha256")]
        self.assertEqual(len(bks), 1)

    def test_settings_with_no_env_block_adds_one_when_dst_non_default(self):
        """If settings.json has no env block and dst is non-default,
        an env block should be created with KAIZEN_BRAIN_DIR set."""
        self.settings.write_text(json.dumps({"permissions": {"allow": []}},
                                              indent=2) + "\n")
        result = bm._edit_settings(self.settings, self.dst, self._args())
        self.assertTrue(result["edited"])
        loaded = json.loads(self.settings.read_text())
        self.assertEqual(loaded["env"]["KAIZEN_BRAIN_DIR"], str(self.dst))

    def test_settings_only_env_was_legacy_drops_env_entirely(self):
        """If env had ONLY legacy keys and dst is default, after edit
        the env key should be removed (no empty dict left behind)."""
        self.settings.write_text(json.dumps(
            {"env": {"REMEMBER_BRAIN_PATH": "/x"}}, indent=2) + "\n")
        default_dst = Path.home() / ".claude" / ".kaizen" / "brain"
        result = bm._edit_settings(self.settings, default_dst, self._args())
        self.assertTrue(result["edited"])
        loaded = json.loads(self.settings.read_text())
        self.assertNotIn("env", loaded,
                         "empty env block should be removed, not left as {}")

    # --- Subcommand smoke (CLI argparse paths) ------------------------

    def test_cmd_edit_settings_removed_in_v1_39(self):
        """cmd_edit_settings was deleted (DEBT-1 YAGNI). cmd_apply is
        idempotent on already-migrated state, so a "settings only"
        flow just re-runs apply."""
        self.assertFalse(hasattr(bm, "cmd_edit_settings"),
                          "cmd_edit_settings should be removed")


class Phase4JsonEnvelope(_BaseCase):
    """Every subcommand with --json must produce the canonical envelope
    (kaizen.tool / kaizen.schema_version / data / verdict). Caught one
    gap: apply emitted text-only even with --json=True before this
    test forced the implementation to use _report() consistently."""

    def _run(self, *argv):
        script = _KZ_DIR / "skills/workflow/scripts/brain_migrate.py"
        return subprocess.run(
            ["python3", str(script), *argv,
             "--src", str(self.src), "--dst", str(self.dst),
             "--settings-file", str(self.settings)],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "KAIZEN_DIR": str(self.tmp / "kaizen-dir")},
        )

    def test_dry_run_json_has_envelope(self):
        _seed_brain(self.src)
        r = self._run("dry-run", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["kaizen"]["tool"], "kaizen-brain-migrate")
        self.assertEqual(out["kaizen"]["schema_version"], 1)
        self.assertIn("would_do", out["data"])

    def test_apply_json_has_envelope(self):
        _seed_brain(self.src)
        r = self._run("apply", "--json", "--no-settings")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["kaizen"]["tool"], "kaizen-brain-migrate")
        self.assertEqual(out["verdict"], "green")
        self.assertEqual(out["data"]["action"], "migrated")

    def test_apply_refused_json_has_red_verdict(self):
        _seed_brain(self.src)
        _seed_brain(self.dst, n_notes=1)
        r = self._run("apply", "--json")
        self.assertEqual(r.returncode, 1)
        out = json.loads(r.stdout)
        self.assertEqual(out["verdict"], "red")
        self.assertEqual(out["data"]["action"], "refused")

    def test_src_and_dst_pointing_at_same_dir_is_rejected(self):
        """RED first: a user passing --src and --dst to the same path
        would cause data-loss. Even with --force-overwrite, we must
        refuse (the both-have-data check passes incidentally without
        --force; the danger is with --force on)."""
        _seed_brain(self.src)
        rc = bm.cmd_apply(self._args(dst=str(self.src), force_overwrite=True))
        self.assertEqual(rc, 1,
                         "apply must refuse when src == dst even with "
                         "--force-overwrite (data-loss risk)")
        self.assertTrue(self.src.exists(),
                        "src must NOT be unlinked when src == dst")

    def test_rollback_json_has_envelope(self):
        _seed_brain(self.src)
        # First apply to create a backup
        self._run("apply", "--no-settings")
        r = self._run("rollback", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["kaizen"]["tool"], "kaizen-brain-migrate")
        self.assertEqual(out["data"]["action"], "rolled-back")


if __name__ == "__main__":
    unittest.main()
