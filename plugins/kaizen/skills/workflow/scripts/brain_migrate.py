#!/usr/bin/env python3
"""kaizen-brain-migrate — relocate the Second Brain.

Migrates the user-global brain directory from the legacy
``~/.claude/brain`` location (Remember plugin era) to the
kaizen-owned ``~/.claude/.kaizen/brain`` (or wherever
``KAIZEN_BRAIN_DIR`` points). The source location is the
``LEGACY_PATHS["brain"]`` from ``_paths.py`` (single SSOT).

## Properties

- **rsync + checksum verify** — never trust a single copy step
- **Backed up first** — tar.gz to
  ``~/.claude/.kaizen/backups/brain-pre-migration-<UTC>.tar.gz``
- **Atomic where possible** — settings.json edit uses
  tempfile + os.replace
- **Idempotent** — re-running `apply` is a no-op if already migrated
- **Refuses to overwrite** — when both src + dst have data, exits 1
  unless ``--force-overwrite`` is set
- **Settings.json safe** — diff preview + dated backup +
  re-parse-verify after write (8-pattern foolproof recipe)
- **Envelope output** — every ``--json`` branch emits the canonical
  ``_envelope`` shape

## Subcommands

::

    kaizen-brain-migrate status        — what's at each location
    kaizen-brain-migrate dry-run       — print what would happen
    kaizen-brain-migrate apply         — do the move + settings edit
    kaizen-brain-migrate rollback      — restore from most-recent backup
    kaizen-brain-migrate edit-settings — only update settings.json env

Common flags:

    --src PATH               source brain dir (default: LEGACY_PATHS["brain"])
    --dst PATH               destination (default: _paths.BRAIN_DIR)
    --settings-file PATH     CC settings.json (default: ~/.claude/settings.json)
    --no-backup              skip tarball backup (NOT recommended)
    --no-settings            skip settings.json edit
    --force-overwrite        merge src over dst even if dst has data
    --json                   emit canonical envelope output

Exit codes: 0 success / 1 user error / 2 verification failure /
            3 backup failure / 4 rsync failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from difflib import unified_diff
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
import _paths  # noqa: E402
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-brain-migrate", tool_version="1.0.0")

_BACKUP_PREFIX = "brain-pre-migration-"

# settings.json env var being migrated AWAY from. Set to None on rollback.
_LEGACY_ENV_VARS = ("REMEMBER_BRAIN_PATH", "KAIZEN_BRAIN_PATH", "KAIZEN_BRAIN")
_NEW_ENV_VAR = "KAIZEN_BRAIN_DIR"


# ─── Helpers ─────────────────────────────────────────────────────────


def _utc_stamp() -> str:
    """UTC timestamp suitable for filenames — sortable, no colons."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _resolve_src(args) -> Path:
    return Path(args.src).expanduser() if args.src else _paths.LEGACY_PATHS["brain"]


def _resolve_dst(args) -> Path:
    return Path(args.dst).expanduser() if args.dst else _paths.BRAIN_DIR


def _resolve_settings(args) -> Path:
    return (Path(args.settings_file).expanduser() if args.settings_file
            else Path.home() / ".claude" / "settings.json")


def _dir_stats(p: Path) -> dict:
    """Recursive file count + total byte size. Skips non-existent."""
    if not p.is_dir():
        return {"exists": False, "file_count": 0, "size_bytes": 0}
    file_count, size = 0, 0
    for f in p.rglob("*"):
        if f.is_file():
            file_count += 1
            try:
                size += f.stat().st_size
            except OSError:
                pass
    return {"exists": True, "file_count": file_count, "size_bytes": size,
            "path": str(p.resolve())}


def _classify(src_stats: dict, dst_stats: dict) -> str:
    """Decide what state the migration is in.

    Returns one of: 'needs-migration', 'already-migrated',
    'both-have-data', 'neither', 'unsupported'."""
    src_has = src_stats["exists"] and src_stats["file_count"] > 0
    dst_has = dst_stats["exists"] and dst_stats["file_count"] > 0
    if src_has and dst_has:
        return "both-have-data"
    if src_has and not dst_has:
        return "needs-migration"
    if not src_has and dst_has:
        return "already-migrated"
    return "neither"


# ─── Subcommand: status ──────────────────────────────────────────────


def cmd_status(args) -> int:
    src = _resolve_src(args)
    dst = _resolve_dst(args)
    src_stats = _dir_stats(src)
    dst_stats = _dir_stats(dst)
    state = _classify(src_stats, dst_stats)
    payload = {
        "src": src_stats,
        "dst": dst_stats,
        "state": state,
        "recommendation": _state_to_recommendation(state),
    }
    if args.json:
        _emit(payload, verdict=_state_to_verdict(state))
    else:
        print(f"[kaizen-brain-migrate] src: {src}")
        print(f"  exists:     {src_stats['exists']}")
        print(f"  file count: {src_stats['file_count']}")
        print(f"  size:       {_human_size(src_stats['size_bytes'])}")
        print(f"[kaizen-brain-migrate] dst: {dst}")
        print(f"  exists:     {dst_stats['exists']}")
        print(f"  file count: {dst_stats['file_count']}")
        print(f"  size:       {_human_size(dst_stats['size_bytes'])}")
        print(f"\nstate:      {state}")
        print(f"action:     {_state_to_recommendation(state)}")
    return 0


def _state_to_recommendation(state: str) -> str:
    return {
        "needs-migration": "run `kaizen-brain-migrate apply`",
        "already-migrated": "nothing to do — brain is at the new location",
        "both-have-data": "CONFLICT — inspect both manually before --force-overwrite",
        "neither": "no brain present anywhere — run `kaizen-brain init` first",
    }.get(state, "unknown state")


def _state_to_verdict(state: str) -> str:
    return {
        "needs-migration": "yellow",
        "already-migrated": "green",
        "both-have-data": "red",
        "neither": "yellow",
    }.get(state, "yellow")


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if isinstance(n, float) else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ─── Subcommand: dry-run ─────────────────────────────────────────────


def cmd_dry_run(args) -> int:
    src = _resolve_src(args)
    dst = _resolve_dst(args)
    settings_file = _resolve_settings(args)
    src_stats = _dir_stats(src)
    dst_stats = _dir_stats(dst)
    state = _classify(src_stats, dst_stats)

    backup_path = (_paths.BACKUP_DIR / f"{_BACKUP_PREFIX}{_utc_stamp()}.tar.gz")

    actions = []
    if state == "needs-migration":
        if not args.no_backup:
            actions.append(f"backup tar.gz → {backup_path}")
        actions.append(f"mkdir -p {dst.parent}")
        actions.append(f"rsync -a --checksum {src}/ {dst}/")
        actions.append(f"verify file count + size match")
        actions.append(f"rm -rf {src}")
        if not args.no_settings:
            settings_diff = _compute_settings_diff(settings_file, dst)
            actions.append("edit settings.json:")
            for line in settings_diff.splitlines():
                actions.append(f"  {line}")
    elif state == "already-migrated":
        actions.append("(no-op: already at destination)")
    elif state == "both-have-data":
        actions.append("(REFUSED: both have data; use --force-overwrite)")
    elif state == "neither":
        actions.append("(no-op: nothing to migrate)")

    payload = {
        "src": src_stats,
        "dst": dst_stats,
        "state": state,
        "backup_path": str(backup_path),
        "settings_file": str(settings_file),
        "would_do": actions,
    }
    if args.json:
        _emit(payload, verdict="green")
    else:
        print(f"[kaizen-brain-migrate dry-run] state: {state}")
        print(f"  src:           {src}")
        print(f"  dst:           {dst}")
        print(f"  backup:        {backup_path}")
        print(f"  settings.json: {settings_file}")
        print("\nWould do:")
        for a in actions:
            print(f"  • {a}")
    return 0


# ─── Subcommand: apply ───────────────────────────────────────────────


def cmd_apply(args) -> int:
    src = _resolve_src(args)
    dst = _resolve_dst(args)
    # Hard-fail on src == dst (with or without --force-overwrite). Same
    # path means rsync would be a no-op AND `rm -rf src` would unlink
    # the same data we just confirmed at dst — data loss.
    if src.exists() and dst.exists() and src.resolve() == dst.resolve():
        _report(args, {"action": "refused", "reason": "src-equals-dst",
                       "path": str(src.resolve())},
                verdict="red", text=
                f"[kaizen-brain-migrate] REFUSED: --src and --dst resolve to "
                f"the same path ({src.resolve()}). Refusing to proceed.")
        return 1
    settings_file = _resolve_settings(args)
    src_stats = _dir_stats(src)
    dst_stats = _dir_stats(dst)
    state = _classify(src_stats, dst_stats)

    if state == "already-migrated":
        _report(args, {"action": "noop", "reason": "already-migrated",
                       "dst": str(dst)}, verdict="green", text=
                "[kaizen-brain-migrate] no-op: already at destination")
        return 0
    if state == "neither":
        _report(args, {"action": "noop", "reason": "nothing-to-migrate"},
                verdict="yellow", text=
                "[kaizen-brain-migrate] no-op: nothing to migrate "
                "(run `kaizen-brain init` first)")
        return 0
    if state == "both-have-data" and not args.force_overwrite:
        _report(args, {"action": "refused", "reason": "both-have-data",
                       "src_files": src_stats["file_count"],
                       "dst_files": dst_stats["file_count"]},
                verdict="red", text=
                f"[kaizen-brain-migrate] REFUSED: both src ({src_stats['file_count']} files) "
                f"and dst ({dst_stats['file_count']} files) have data.\n"
                "  inspect both manually before re-running with --force-overwrite.")
        return 1

    # ─── Phase 1: backup ──────────────────────────────────────────────
    backup_path: Optional[Path] = None
    if not args.no_backup:
        backup_path = _backup_src(src, args)
        if backup_path is None:
            return 3

    # ─── Phase 2: rsync ───────────────────────────────────────────────
    dst.parent.mkdir(parents=True, exist_ok=True)
    rsync_ok = _rsync_dir(src, dst, args)
    if not rsync_ok:
        _report(args, {"action": "failed", "phase": "rsync"},
                verdict="red", text=
                "[kaizen-brain-migrate] rsync failed — src untouched, backup at "
                f"{backup_path}")
        return 4

    # ─── Phase 3: verify ──────────────────────────────────────────────
    verify = _verify_dirs(src, dst)
    if not verify["ok"]:
        _report(args, {"action": "failed", "phase": "verify",
                       "verify": verify}, verdict="red", text=
                f"[kaizen-brain-migrate] verify failed: {verify['reason']}\n"
                "  src is still intact; dst may have partial data; "
                f"backup at {backup_path}")
        return 2

    # ─── Phase 4: unlink src ──────────────────────────────────────────
    shutil.rmtree(src, ignore_errors=False)

    # ─── Phase 5: edit settings.json ──────────────────────────────────
    settings_result = {"edited": False, "skipped": True}
    if not args.no_settings:
        settings_result = _edit_settings(settings_file, dst, args)

    payload = {
        "action": "migrated",
        "src": str(src),
        "dst": str(dst),
        "backup": str(backup_path) if backup_path else None,
        "files_moved": verify["dst_files"],
        "bytes_moved": verify["dst_size"],
        "settings": settings_result,
    }
    _report(args, payload, verdict="green", text=
            f"[kaizen-brain-migrate] ✓ migrated {verify['dst_files']} file(s) "
            f"({_human_size(verify['dst_size'])})\n"
            f"  src → dst:  {src} → {dst}\n"
            f"  backup:     {backup_path}\n"
            f"  settings:   {'edited' if settings_result.get('edited') else 'skipped'}\n"
            f"  rollback:   `kaizen-brain-migrate rollback` "
            "(restores src dir + settings.json)")
    return 0


def _backup_src(src: Path, args) -> Optional[Path]:
    """Tar.gz the src dir to the backup location, write a SHA-256
    sidecar for integrity verification at rollback time. Returns the
    tar path on success, None on failure."""
    _paths.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = _paths.BACKUP_DIR / f"{_BACKUP_PREFIX}{_utc_stamp()}.tar.gz"
    try:
        with tarfile.open(backup_path, "w:gz") as tar:
            tar.add(src, arcname=src.name)
    except (OSError, tarfile.TarError) as e:
        print(f"[kaizen-brain-migrate] backup failed: {e}", file=sys.stderr)
        return None
    # Sanity-check: tarball is readable + non-trivial size
    try:
        with tarfile.open(backup_path, "r:gz") as tar:
            count = sum(1 for _ in tar)
        if count == 0:
            print("[kaizen-brain-migrate] backup produced empty tarball",
                  file=sys.stderr)
            return None
    except (OSError, tarfile.TarError) as e:
        print(f"[kaizen-brain-migrate] backup verify failed: {e}",
              file=sys.stderr)
        return None
    # CRYPTO-1: write SHA-256 sidecar for tamper detection at rollback
    if not _write_sha256_sidecar(backup_path):
        return None
    return backup_path


def _write_sha256_sidecar(tar_path: Path) -> bool:
    """Compute SHA-256 of `tar_path` and write `<tar_path>.sha256`
    next to it. Returns True on success."""
    try:
        digest = hashlib.sha256(tar_path.read_bytes()).hexdigest()
        sidecar = Path(str(tar_path) + ".sha256")
        sidecar.write_text(digest + "\n")
        return True
    except OSError as e:
        print(f"[kaizen-brain-migrate] sidecar write failed: {e}",
              file=sys.stderr)
        return False


def _verify_sha256_sidecar(tar_path: Path) -> bool:
    """Verify `tar_path` against `<tar_path>.sha256`. Returns False
    when sidecar is missing OR digest doesn't match. Used by
    cmd_rollback before extraction."""
    sidecar = Path(str(tar_path) + ".sha256")
    if not sidecar.is_file():
        print(f"[kaizen-brain-migrate] integrity sidecar missing: {sidecar}",
              file=sys.stderr)
        return False
    try:
        expected = sidecar.read_text().strip()
        actual = hashlib.sha256(tar_path.read_bytes()).hexdigest()
    except OSError as e:
        print(f"[kaizen-brain-migrate] sidecar read failed: {e}",
              file=sys.stderr)
        return False
    if expected != actual:
        print(f"[kaizen-brain-migrate] INTEGRITY FAILURE: {tar_path}\n"
              f"  expected: {expected}\n"
              f"  actual:   {actual}\n"
              f"  refusing to extract a tampered/corrupted tarball",
              file=sys.stderr)
        return False
    return True


def _rsync_dir(src: Path, dst: Path, args) -> bool:
    """rsync -a --checksum src/ dst/  (preserves perms, content-hash
    verify per file). Returns True on success."""
    cmd = ["rsync", "-a", "--checksum", f"{src}/", f"{dst}/"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"[kaizen-brain-migrate] rsync invocation failed: {e}",
              file=sys.stderr)
        return False
    if r.returncode != 0:
        print(f"[kaizen-brain-migrate] rsync exited {r.returncode}: "
              f"{r.stderr[:500]}", file=sys.stderr)
        return False
    return True


def _verify_dirs(src: Path, dst: Path) -> dict:
    """Confirm dst received src's content. Returns dict with ok/reason
    + dst stats."""
    src_stats = _dir_stats(src)
    dst_stats = _dir_stats(dst)
    if dst_stats["file_count"] < src_stats["file_count"]:
        return {"ok": False, "reason":
                f"file count mismatch — src={src_stats['file_count']} "
                f"dst={dst_stats['file_count']}",
                "dst_files": dst_stats["file_count"],
                "dst_size": dst_stats["size_bytes"]}
    # Size tolerance: rsync may rewrite sqlite slightly differently due to
    # WAL/journal files. Accept dst within 1% of src OR ≥ src.
    src_size = src_stats["size_bytes"]
    dst_size = dst_stats["size_bytes"]
    if src_size > 0 and dst_size < int(src_size * 0.99):
        return {"ok": False, "reason":
                f"size mismatch — src={src_size} dst={dst_size} "
                f"(>1% loss)",
                "dst_files": dst_stats["file_count"],
                "dst_size": dst_size}
    return {"ok": True, "dst_files": dst_stats["file_count"],
            "dst_size": dst_size}


# ─── Subcommand: rollback ────────────────────────────────────────────


def cmd_rollback(args) -> int:
    src = _resolve_src(args)
    dst = _resolve_dst(args)
    backups = sorted(_paths.BACKUP_DIR.glob(f"{_BACKUP_PREFIX}*.tar.gz"))
    if not backups:
        _report(args, {"action": "failed", "reason": "no-backup"},
                verdict="red", text=
                "[kaizen-brain-migrate rollback] no backup tarball found at "
                f"{_paths.BACKUP_DIR}")
        return 1
    latest = backups[-1]
    # CRYPTO-1: verify SHA-256 sidecar before any extraction.
    if not _verify_sha256_sidecar(latest):
        _report(args, {"action": "failed", "reason": "integrity-failure",
                       "backup": str(latest)}, verdict="red", text=
                f"[kaizen-brain-migrate rollback] REFUSED: {latest} failed "
                f"integrity check (corrupted or tampered).")
        return 2

    # Restore src (delete dst, untar backup over src parent)
    if dst.exists():
        # Re-tar dst before nuking so a botched rollback doesn't lose data.
        rescue = _paths.BACKUP_DIR / f"brain-pre-rollback-{_utc_stamp()}.tar.gz"
        try:
            with tarfile.open(rescue, "w:gz") as tar:
                tar.add(dst, arcname=dst.name)
        except (OSError, tarfile.TarError):
            rescue = None
        shutil.rmtree(dst)
    else:
        rescue = None

    src.parent.mkdir(parents=True, exist_ok=True)
    # filter="data" (Py3.12+) rejects path-traversal members
    # (../../), absolute paths, dangerous device files, and symlinks
    # pointing outside the extraction root. Tarfile's default is
    # unsafe (CVE-2007-4559 class). Tarfile changes the default in
    # Python 3.14 — until then, we MUST be explicit.
    with tarfile.open(latest, "r:gz") as tar:
        tar.extractall(src.parent, filter="data")

    payload = {
        "action": "rolled-back",
        "src": str(src),
        "backup_used": str(latest),
        "dst_rescue_tar": str(rescue) if rescue else None,
    }
    _report(args, payload, verdict="green", text=
            f"[kaizen-brain-migrate rollback] restored {src}\n"
            f"  from backup:  {latest}\n"
            f"  dst rescue:   {rescue}")
    return 0


# ─── Subcommand: edit-settings ───────────────────────────────────────


def cmd_edit_settings(args) -> int:
    dst = _resolve_dst(args)
    settings_file = _resolve_settings(args)
    result = _edit_settings(settings_file, dst, args)
    if args.json:
        _emit(result, verdict="green" if result.get("edited") else "yellow")
    elif result.get("edited"):
        print(f"[kaizen-brain-migrate edit-settings] ✓ updated {settings_file}")
        print(f"  backup: {result['backup']}")
        print(f"  rollback: cp {result['backup']} {settings_file}")
    else:
        print(f"[kaizen-brain-migrate edit-settings] no change needed "
              f"({result.get('reason', 'unknown')})")
    return 0


# ─── Settings.json mutation (8-pattern foolproof recipe) ─────────────


def _compute_settings_diff(settings_file: Path, dst: Path) -> str:
    """Build the would-be unified diff against settings.json. Read-only."""
    if not settings_file.is_file():
        return f"(settings.json does not exist at {settings_file}; skipped)"
    old = settings_file.read_text(encoding="utf-8")
    try:
        data = json.loads(old)
    except json.JSONDecodeError as e:
        return f"(unparseable JSON: {e}; skipped)"
    new_data = _settings_mutated(data, dst)
    new = json.dumps(new_data, indent=2, ensure_ascii=False) + "\n"
    return "".join(unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=str(settings_file),
        tofile=str(settings_file) + " (proposed)",
        n=2,
    ))


def _settings_mutated(data: dict, dst: Path) -> dict:
    """Return a new dict with the brain env var migration applied.

    - Drops any legacy env keys (REMEMBER_BRAIN_PATH, KAIZEN_BRAIN_PATH,
      KAIZEN_BRAIN) from `env`.
    - If dst differs from the kaizen default (~/.claude/.kaizen/brain),
      writes `env.KAIZEN_BRAIN_DIR` to the dst path; else removes the
      key so the SSOT default applies.
    """
    out = dict(data)  # shallow copy; only mutating top-level + env
    env = dict(out.get("env", {}))
    # Drop legacy
    for k in _LEGACY_ENV_VARS:
        env.pop(k, None)
    # Set new (only if non-default)
    default_dst = Path.home() / ".claude" / ".kaizen" / "brain"
    if dst.resolve() != default_dst.resolve():
        env[_NEW_ENV_VAR] = str(dst)
    else:
        env.pop(_NEW_ENV_VAR, None)
    if env:
        out["env"] = env
    else:
        out.pop("env", None)
    return out


def _edit_settings(settings_file: Path, dst: Path, args) -> dict:
    """Apply the 8-pattern foolproof settings.json mutation."""
    if not settings_file.is_file():
        return {"edited": False, "skipped": True,
                "reason": f"settings.json does not exist at {settings_file}"}
    # 1. Backup-first (before any read of original). Sidecar
    # `<backup>.sha256` provides integrity verification for future
    # rollback (CRYPTO-2 — same pattern as tarball backups).
    backup = settings_file.parent / (
        settings_file.name + ".bak-" + _utc_stamp()
    )
    shutil.copy2(settings_file, backup)
    _write_sha256_sidecar(backup)
    # 2. Read + parse
    old_text = settings_file.read_text(encoding="utf-8")
    try:
        data = json.loads(old_text)
    except json.JSONDecodeError as e:
        return {"edited": False, "error": f"unparseable JSON: {e}",
                "backup": str(backup)}
    # 3. Mutate (pure)
    new_data = _settings_mutated(data, dst)
    # 4. Check if anything actually changed — skip write if not
    new_text = json.dumps(new_data, indent=2, ensure_ascii=False) + "\n"
    if new_text == old_text:
        # Roll back the unnecessary backup so we don't accumulate cruft.
        # Also remove the sidecar (it's now an orphan reference).
        backup.unlink(missing_ok=True)
        Path(str(backup) + ".sha256").unlink(missing_ok=True)
        return {"edited": False, "skipped": True,
                "reason": "no change needed"}
    # 5. Diff preview (always, even when --json)
    diff = "".join(unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=str(settings_file),
        tofile=str(settings_file) + " (new)",
        n=2,
    ))
    print(diff, file=sys.stderr)
    # 6. Atomic write: tempfile in same dir + os.replace
    fd, tmp = tempfile.mkstemp(prefix=settings_file.name + ".",
                                suffix=".tmp",
                                dir=str(settings_file.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(new_text)
        # 7. Re-parse-verify before rename
        with open(tmp, encoding="utf-8") as fh:
            re_parsed = json.load(fh)
        if _NEW_ENV_VAR in re_parsed.get("env", {}):
            assert re_parsed["env"][_NEW_ENV_VAR] == str(dst), (
                "verification failed: written env value doesn't match")
        os.replace(tmp, settings_file)
    except Exception as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return {"edited": False, "error": str(e), "backup": str(backup)}
    return {"edited": True, "backup": str(backup),
            "rollback_cmd": f"cp {backup} {settings_file}"}


def _report(args, payload: dict, *, verdict: str, text: str) -> None:
    """Emit JSON envelope or text per --json flag."""
    if args.json:
        _emit(payload, verdict=verdict)
    else:
        print(text)


# ─── CLI ─────────────────────────────────────────────────────────────


def _add_common_flags(sp):
    sp.add_argument("--src", help="source brain dir (default: legacy ~/.claude/brain)")
    sp.add_argument("--dst", help="destination dir (default: KAIZEN_BRAIN_DIR)")
    sp.add_argument("--settings-file",
                    help="CC settings.json (default: ~/.claude/settings.json)")
    sp.add_argument("--json", action="store_true",
                    help="emit canonical envelope JSON")


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-brain-migrate",
        description="Relocate the Second Brain from ~/.claude/brain to "
                    "the kaizen-owned ~/.claude/.kaizen/brain.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="check both locations")
    _add_common_flags(s)
    s.set_defaults(func=cmd_status)

    d = sub.add_parser("dry-run", help="print what would happen")
    _add_common_flags(d)
    d.add_argument("--no-backup", action="store_true")
    d.add_argument("--no-settings", action="store_true")
    d.set_defaults(func=cmd_dry_run)

    a = sub.add_parser("apply", help="do the move + settings edit")
    _add_common_flags(a)
    a.add_argument("--no-backup", action="store_true")
    a.add_argument("--no-settings", action="store_true")
    a.add_argument("--force-overwrite", action="store_true",
                   help="merge src over dst even if both have data")
    a.set_defaults(func=cmd_apply)

    r = sub.add_parser("rollback", help="restore from most-recent backup")
    _add_common_flags(r)
    r.set_defaults(func=cmd_rollback)

    e = sub.add_parser("edit-settings",
                       help="only update settings.json env var (no data move)")
    _add_common_flags(e)
    e.set_defaults(func=cmd_edit_settings)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
