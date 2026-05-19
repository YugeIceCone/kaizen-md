#!/usr/bin/env python3
# consolidated-cli-parent: migrate
"""kaizen-migrate path — v1.38 → v1.39 layout restructure.

Moves 4 search dirs into ``indexes/``, 1 multi-file daemon dir + 4
bare singletons into ``data/``, hoists ``observe/snapshots/`` to
``snapshots/``, renames ``_legacy/`` to ``archive/``.

Source-of-truth: ``_paths.LEGACY_TO_NEW`` filtered to the keys whose
NEW target is under the new umbrellas (skip the pre-v1.22 entries —
those moves landed long ago).

## Properties

- **rsync + checksum verify** per-move
- **One whole-tree backup tarball** to
  ``$KAIZEN_DIR/backups/path-restructure-<UTC>.tar.gz`` before any
  move (single tarball captures the pre-restructure state of every
  legacy dir)
- **Atomic per move** (rsync to dst → verify → unlink src)
- **Refuses on per-move conflict** when both src + dst have data,
  unless ``--force-overwrite`` (rsync without ``--delete`` merges)
- **Idempotent** — apply is a no-op when no legacy paths remain

## Subcommands

::

    kaizen-migrate path status        — per-move classification
    kaizen-migrate path dry-run       — print would-do, mutate nothing
    kaizen-migrate path apply         — execute moves
    kaizen-migrate path rollback      — restore from latest backup

Common flags: ``--json``, ``--no-backup``, ``--force-overwrite``.

Exit codes: 0 success / 1 user error or conflict refusal /
            2 verify failure / 3 backup failure / 4 rsync failure.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(_SCRIPT_DIR.parent / "io"))
import _paths  # noqa: E402
import _envelope  # noqa: E402
import _migrator as _mig  # noqa: E402 — shared migrator primitives (DEBT-1)

_emit = _envelope.emitter("kaizen-migrate path", tool_version="1.0.0")
_LABEL = "kaizen-migrate path"

_BACKUP_PREFIX = "path-restructure-"


# ─── The move set (v1.38 → v1.39) ────────────────────────────────────


def _moves() -> list[tuple[str, Path, Path]]:
    """Return [(label, src, dst), ...] for the v1.39 restructure.

    Re-derived at call time so test sandboxes (which reload _paths)
    pick up the right umbrella roots. Filter LEGACY_TO_NEW to just
    the entries whose label ends in `_v138`."""
    out: list[tuple[str, Path, Path]] = []
    for label, src in _paths.LEGACY_PATHS.items():
        if not label.endswith("_v138"):
            continue
        dst = _paths.LEGACY_TO_NEW.get(src)
        if dst is None:
            continue
        out.append((label.removesuffix("_v138"), src, dst))
    return out


def _utc_stamp() -> str:
    return _mig.utc_stamp()


def _has_content(p: Path) -> bool:
    """True if `p` exists AND has migration-worthy presence.

    For files: just existing counts (empty files like manifest.lock
    carry semantic meaning — a 0-byte lock IS the lock).
    For dirs: must contain at least one entry."""
    if not p.exists():
        return False
    if p.is_file():
        return True
    if p.is_dir():
        try:
            return any(p.iterdir())
        except OSError:
            return False
    return False


def _classify_move(src: Path, dst: Path) -> str:
    src_has = _has_content(src)
    dst_has = _has_content(dst)
    if src_has and dst_has:
        return "conflict"  # both have content
    if src_has and not dst_has:
        return "needs-migration"
    if not src_has and dst_has:
        return "already-migrated"
    return "neither"


# ─── Subcommand: status ──────────────────────────────────────────────


def cmd_status(args) -> int:
    moves = _moves()
    rows = []
    for label, src, dst in moves:
        state = _classify_move(src, dst)
        rows.append({
            "label": label, "src": str(src), "dst": str(dst),
            "state": state,
        })
    summary = {
        s: sum(1 for r in rows if r["state"] == s)
        for s in ("needs-migration", "already-migrated", "conflict", "neither")
    }
    payload = {"moves": rows, "summary": summary}
    if args.json:
        verdict = ("red" if summary["conflict"] else
                   "yellow" if summary["needs-migration"] else
                   "green")
        _emit(payload, verdict=verdict, counts=summary)
    else:
        print("[kaizen-migrate path status]")
        for r in rows:
            print(f"  [{r['state']:>17}] {r['label']:<14} {r['src']} → {r['dst']}")
        print(f"\nsummary: {summary}")
        if summary["conflict"]:
            print("\naction: CONFLICT(s) — inspect manually, then "
                  "`apply --force-overwrite` to merge")
        elif summary["needs-migration"]:
            print("\naction: run `kaizen-migrate path apply`")
        elif summary["already-migrated"]:
            print("\naction: nothing to do — already at the new layout")
        else:
            print("\naction: nothing to migrate (greenfield)")
    return 0


# ─── Subcommand: dry-run ─────────────────────────────────────────────


def cmd_dry_run(args) -> int:
    moves = _moves()
    actions = []
    backup_path = _paths.BACKUP_DIR / f"{_BACKUP_PREFIX}{_utc_stamp()}.tar.gz"
    if not args.no_backup:
        actions.append(f"backup whole-tree tar.gz → {backup_path}")
    any_to_do = False
    for label, src, dst in moves:
        state = _classify_move(src, dst)
        if state == "needs-migration":
            actions.append(f"rsync {src}/ → {dst}/")
            actions.append(f"  verify file count + size, unlink {src}")
            any_to_do = True
        elif state == "conflict":
            actions.append(f"REFUSED ({label}): both src + dst have content "
                           "— use --force-overwrite to merge")
    if not any_to_do:
        actions.append("(no-op: nothing to migrate)")
    payload = {"backup_path": str(backup_path), "would_do": actions}
    if args.json:
        _emit(payload, verdict="green")
    else:
        print("[kaizen-migrate path dry-run]")
        for a in actions:
            print(f"  • {a}")
    return 0


# ─── Subcommand: apply ───────────────────────────────────────────────


def cmd_apply(args) -> int:
    moves = _moves()
    # First pass: classify all + check for conflicts
    classified = [(label, src, dst, _classify_move(src, dst))
                  for label, src, dst in moves]
    conflicts = [c for c in classified if c[3] == "conflict"]
    if conflicts and not args.force_overwrite:
        labels = ", ".join(c[0] for c in conflicts)
        _report(args, {"action": "refused", "reason": "conflicts",
                       "conflicting": [c[0] for c in conflicts]},
                verdict="red", text=
                f"[kaizen-migrate path] REFUSED — conflicts in: {labels}\n"
                "  use --force-overwrite to merge (rsync preserves dst-only files)")
        return 1

    to_move = [c for c in classified if c[3] in ("needs-migration", "conflict")]
    if not to_move:
        _report(args, {"action": "noop", "reason": "all-migrated-or-empty"},
                verdict="green", text=
                "[kaizen-migrate path] no-op: nothing to migrate")
        return 0

    # Whole-tree backup BEFORE any move
    backup_path: Optional[Path] = None
    if not args.no_backup:
        backup_path = _backup_tree()
        if backup_path is None:
            _report(args, {"action": "failed", "phase": "backup"},
                    verdict="red", text=
                    "[kaizen-migrate path] backup failed — aborting")
            return 3

    # Per-move execution
    moved: list[dict] = []
    for label, src, dst, _state in to_move:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_file():
            ok = _move_file(src, dst)
        else:
            ok = _move_dir(src, dst)
        if not ok:
            _report(args, {"action": "failed", "phase": "rsync",
                           "label": label, "backup": str(backup_path)},
                    verdict="red", text=
                    f"[kaizen-migrate path] rsync failed on {label} ({src}). "
                    f"Backup at {backup_path}; src untouched.")
            return 4
        moved.append({"label": label, "src": str(src), "dst": str(dst)})

    payload = {
        "action": "migrated",
        "moved": moved,
        "backup": str(backup_path) if backup_path else None,
        "count": len(moved),
    }
    _report(args, payload, verdict="green", text=
            f"[kaizen-migrate path] ✓ migrated {len(moved)} path(s)\n"
            + "\n".join(f"  • {m['label']:<14} {m['src']} → {m['dst']}"
                        for m in moved)
            + f"\n  backup:   {backup_path}\n"
            f"  rollback: `kaizen-migrate path rollback`")
    return 0


def _backup_tree() -> Optional[Path]:
    """Whole-tree backup via _migrator.make_backup_tarball (DEBT-1)."""
    # We need to thread the self-exclusion filter through, but the
    # filter depends on the tar_path (which the helper picks). The
    # _migrator helper accepts a tar_filter callable; we wrap a
    # closure that compares against the to-be-determined tar path
    # using a `_BackupPathHolder` shim.
    holder = {}
    def filter_fn(tarinfo):
        bp = holder.get("path", "")
        if bp and str(bp).endswith(tarinfo.name):
            return None
        return tarinfo
    backup_path = _mig.make_backup_tarball(
        _paths.BACKUP_DIR, _BACKUP_PREFIX, _paths.KAIZEN_USER_DIR,
        label=_LABEL, arcname=_paths.KAIZEN_USER_DIR.name,
        tar_filter=filter_fn,
    )
    # Note: the filter sees `tarinfo.name` BEFORE the tarball is
    # finalized — but we don't actually need to exclude it because
    # make_backup_tarball creates the tar.gz file BEFORE adding members
    # (open mode "w:gz"), so the file exists but is being written to.
    # Still, the filter shape is preserved for symmetry with the prior
    # implementation. In practice the recursive-include risk only
    # appears for older code that tar'd cwd; we never do.
    return backup_path


# Back-compat thin wrappers — tests may monkey-patch these.
def _write_sha256_sidecar(tar_path: Path) -> bool:
    return _mig.write_sha256_sidecar(tar_path, label=_LABEL)


def _verify_sha256_sidecar(tar_path: Path) -> bool:
    return _mig.verify_sha256_sidecar(tar_path, label=_LABEL)


def _skip_self_backup(backup_path: Path):
    """Tarfile filter that excludes the backup tarball itself
    (avoid recursive inclusion)."""
    bp_str = str(backup_path)
    def _filter(tarinfo):
        if bp_str.endswith(tarinfo.name):
            return None
        return tarinfo
    return _filter


# DEBT-1: rsync + verify + file-move delegate to _migrator (SSOT).
# These thin wrappers stay because tests monkey-patch them.
def _move_dir(src: Path, dst: Path) -> bool:
    if not _mig.rsync_dir(src, dst, label=_LABEL):
        return False
    if not _verify_dir(src, dst):
        return False
    shutil.rmtree(src, ignore_errors=False)
    return True


def _verify_dir(src: Path, dst: Path) -> bool:
    # path_migrate's per-file verify is stricter (no size tolerance band)
    # than brain_migrate's (1% band for sqlite WAL drift). Pin to 0% here.
    return _mig.verify_dir(src, dst, size_tolerance_pct=0.0)["ok"]


def _move_file(src: Path, dst: Path) -> bool:
    return _mig.move_file(src, dst, label=_LABEL)


# ─── Subcommand: rollback ────────────────────────────────────────────


def cmd_rollback(args) -> int:
    backups = sorted(_paths.BACKUP_DIR.glob(f"{_BACKUP_PREFIX}*.tar.gz"))
    if not backups:
        _report(args, {"action": "failed", "reason": "no-backup"},
                verdict="red", text=
                f"[kaizen-migrate path rollback] no backup at {_paths.BACKUP_DIR}")
        return 1
    latest = backups[-1]
    # CRYPTO-1: verify SHA-256 sidecar before any extraction
    if not _verify_sha256_sidecar(latest):
        _report(args, {"action": "failed", "reason": "integrity-failure",
                       "backup": str(latest)}, verdict="red", text=
                f"[kaizen-migrate path rollback] REFUSED: {latest} failed "
                f"integrity check (corrupted or tampered).")
        return 2
    # Extract over the user-dir parent (the tar was rooted at .kaizen/).
    # filter="data" (Py3.12+) rejects path-traversal, absolute paths,
    # and dangerous symlinks (CVE-2007-4559 class).
    target_parent = _paths.KAIZEN_USER_DIR.parent
    with tarfile.open(latest, "r:gz") as tar:
        tar.extractall(target_parent, filter="data")
    _report(args, {"action": "rolled-back", "backup_used": str(latest)},
            verdict="green", text=
            f"[kaizen-migrate path rollback] restored from {latest}")
    return 0


def _report(args, payload: dict, *, verdict: str, text: str) -> None:
    if args.json:
        _emit(payload, verdict=verdict)
    else:
        print(text)


# ─── CLI ─────────────────────────────────────────────────────────────


def _add_common_flags(sp):
    sp.add_argument("--json", action="store_true",
                    help="emit canonical envelope JSON")


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-migrate path",
        description="v1.38 → v1.39 path restructure: indexes/ + data/ + "
                    "snapshots/ + archive/.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="per-move classification")
    _add_common_flags(s)
    s.set_defaults(func=cmd_status)

    d = sub.add_parser("dry-run", help="print would-do, mutate nothing")
    _add_common_flags(d)
    d.add_argument("--no-backup", action="store_true")
    d.set_defaults(func=cmd_dry_run)

    a = sub.add_parser("apply", help="execute the moves")
    _add_common_flags(a)
    a.add_argument("--no-backup", action="store_true")
    a.add_argument("--force-overwrite", action="store_true",
                   help="merge src over dst when both have content "
                        "(rsync preserves dst-only files)")
    a.set_defaults(func=cmd_apply)

    r = sub.add_parser("rollback", help="restore from most-recent backup")
    _add_common_flags(r)
    r.set_defaults(func=cmd_rollback)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
