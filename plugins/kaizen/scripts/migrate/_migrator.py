"""kaizen — shared primitives for the migrator family.

Two migrators (`brain_migrate.py`, `path_migrate.py`) shared
nearly-identical code for utc-stamps, rsync moves, file verification,
backup-tarballs, and sha256 sidecars. This module is the SSOT for
those primitives so future migrators (v1.40+) don't fork another copy.

## Public surface

  utc_stamp() -> str
      "20260517T122359Z"-style timestamp (sortable, no colons).

  rsync_dir(src, dst, *, label) -> bool
      `rsync -a --checksum src/ dst/` with subprocess+timeout
      handling. Returns True on success.

  move_file(src, dst) -> bool
      shutil.copy2 + size verify + unlink. Returns True on success.

  verify_dir(src, dst) -> dict
      Confirms every src file is present at dst with same size.
      Returns {ok, reason?, dst_files, dst_size}.

  write_sha256_sidecar(target) -> bool
      Computes SHA-256 of `target`, writes `<target>.sha256` next to it.

  verify_sha256_sidecar(target) -> bool
      Reads `<target>.sha256`, recomputes target's hash, returns True
      iff they match AND sidecar exists.

  make_backup_tarball(backup_dir, prefix, source) -> Optional[Path]
      Tars+gzips `source` into `backup_dir/<prefix><utc>.tar.gz`,
      writes sidecar, returns the tar path (None on any failure).

All helpers are stdlib-only. None of them emit envelope output —
that's the caller's concern (so each migrator keeps its own
`_envelope.emitter(tool=...)` identity).
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

def utc_stamp() -> str:
    """Sortable filename-safe UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

# ─── rsync + verify ──────────────────────────────────────────────────

def rsync_dir(src: Path, dst: Path, *, label: str = "kaizen-migrator",
               timeout_sec: float = 300.0) -> bool:
    """`rsync -a --checksum src/ dst/` — merge if dst exists, preserve
    dst-only files (no `--delete`). Returns True on success."""
    cmd = ["rsync", "-a", "--checksum", f"{src}/", f"{dst}/"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                            timeout=timeout_sec)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"[{label}] rsync invocation error: {e}", file=sys.stderr)
        return False
    if r.returncode != 0:
        print(f"[{label}] rsync exit {r.returncode}: {r.stderr[:300]}",
              file=sys.stderr)
        return False
    return True

def move_file(src: Path, dst: Path, *, label: str = "kaizen-migrator") -> bool:
    """Single-file move via shutil.copy2 + size-match verify + unlink."""
    try:
        shutil.copy2(src, dst)
    except (OSError, shutil.SameFileError) as e:
        print(f"[{label}] copy {src} → {dst} failed: {e}", file=sys.stderr)
        return False
    if src.stat().st_size != dst.stat().st_size:
        print(f"[{label}] size mismatch on {src.name}", file=sys.stderr)
        return False
    src.unlink()
    return True

def verify_dir(src: Path, dst: Path, *,
                size_tolerance_pct: float = 1.0) -> dict:
    """Confirm dst received every src file with matching content size.

    `size_tolerance_pct` allows for slight rewrites (sqlite WAL / journal
    drift) — set to 0.0 for strict byte-for-byte match. Returns:
        {ok: bool, reason?: str, dst_files: int, dst_size: int}
    """
    src_files = sorted(p.relative_to(src)
                        for p in src.rglob("*") if p.is_file())
    dst_size = 0
    src_size = 0
    for rel in src_files:
        d = dst / rel
        if not d.is_file():
            return {"ok": False, "reason": f"missing at dst: {rel}",
                    "dst_files": 0, "dst_size": 0}
        try:
            sd = (src / rel).stat().st_size
            dd = d.stat().st_size
        except OSError:
            return {"ok": False, "reason": f"stat failed: {rel}",
                    "dst_files": 0, "dst_size": 0}
        src_size += sd
        dst_size += dd
    # File-count quick check (catches anything extra at dst not relevant;
    # we only require src ⊆ dst).
    dst_count = sum(1 for p in dst.rglob("*") if p.is_file())
    if dst_count < len(src_files):
        return {"ok": False,
                "reason": f"file count: src={len(src_files)} dst={dst_count}",
                "dst_files": dst_count, "dst_size": dst_size}
    # Total size tolerance band
    if src_size > 0 and size_tolerance_pct > 0:
        threshold = int(src_size * (1 - size_tolerance_pct / 100))
        if dst_size < threshold:
            return {"ok": False,
                    "reason": (f"size mismatch — src={src_size} dst={dst_size} "
                                f"(>{size_tolerance_pct}% loss)"),
                    "dst_files": dst_count, "dst_size": dst_size}
    return {"ok": True, "dst_files": dst_count, "dst_size": dst_size}

# ─── sha256 sidecars (CRYPTO-1, CRYPTO-2) ────────────────────────────

def write_sha256_sidecar(target: Path, *,
                          label: str = "kaizen-migrator") -> bool:
    """Compute SHA-256 of `target`, write `<target>.sha256` next to it."""
    try:
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        sidecar = Path(str(target) + ".sha256")
        sidecar.write_text(digest + "\n")
        return True
    except OSError as e:
        print(f"[{label}] sidecar write failed: {e}", file=sys.stderr)
        return False

def verify_sha256_sidecar(target: Path, *,
                           label: str = "kaizen-migrator") -> bool:
    """Verify `target` against `<target>.sha256`. Returns False when
    sidecar is missing OR digest doesn't match."""
    sidecar = Path(str(target) + ".sha256")
    if not sidecar.is_file():
        print(f"[{label}] integrity sidecar missing: {sidecar}",
              file=sys.stderr)
        return False
    try:
        expected = sidecar.read_text().strip()
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError as e:
        print(f"[{label}] sidecar read failed: {e}", file=sys.stderr)
        return False
    if expected != actual:
        print(f"[{label}] INTEGRITY FAILURE: {target}\n"
              f"  expected: {expected}\n"
              f"  actual:   {actual}\n"
              f"  refusing to extract a tampered/corrupted tarball",
              file=sys.stderr)
        return False
    return True

# ─── Backup tarball helper ───────────────────────────────────────────

def make_backup_tarball(backup_dir: Path, prefix: str, source: Path,
                         *, label: str = "kaizen-migrator",
                         arcname: Optional[str] = None,
                         tar_filter=None) -> Optional[Path]:
    """Tar+gzip `source` into `backup_dir/<prefix><utc>.tar.gz`, write
    sha256 sidecar, return tar path. None on any failure.

    arcname  — passed to `tar.add(...)`. Defaults to `source.name`.
    tar_filter — tarfile filter callable (e.g. to exclude the backup
                 file from itself when archiving its parent).
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    tar_path = backup_dir / f"{prefix}{utc_stamp()}.tar.gz"
    name = arcname if arcname is not None else source.name
    try:
        with tarfile.open(tar_path, "w:gz") as tar:
            if tar_filter is not None:
                tar.add(source, arcname=name, filter=tar_filter)
            else:
                tar.add(source, arcname=name)
    except (OSError, tarfile.TarError) as e:
        print(f"[{label}] backup failed: {e}", file=sys.stderr)
        return None
    # Sanity-check readback
    try:
        with tarfile.open(tar_path, "r:gz") as tar:
            count = sum(1 for _ in tar)
        if count == 0:
            print(f"[{label}] backup produced empty tarball", file=sys.stderr)
            return None
    except (OSError, tarfile.TarError) as e:
        print(f"[{label}] backup readback failed: {e}", file=sys.stderr)
        return None
    if not write_sha256_sidecar(tar_path, label=label):
        return None
    return tar_path
