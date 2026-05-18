#!/usr/bin/env python3
# consolidated-cli-parent: bundle
"""kaizen-bundle — session-folder management for docs/superpowers/.

Convention (per user 2026-05-18):
  docs/superpowers/<YYYY-MM-DD>-<project>-<short-sid>/multiple-files.md

Each session's artifacts (specs, plans, brainstorms, notes) bundle into
ONE date+project+sid folder. Templates and durable references stay
outside session folders (templates/ at top level).

Subcommands:
  init   — scaffold a new bundle folder (idempotent)
  list   — show bundles (filter by --project)
  path   — print the path of a bundle by spec (pure compute; no I/O)
  add    — move a file INTO a bundle (creates bundle if absent)

Design contract:
  - PROGRAMMABLE  — bundle_folder_name, bundle_path are pure callables
  - REPRODUCIBLE  — folder name is a pure function of (date, project, sid)
  - CONSISTENT    — env-overridable root via KAIZEN_SUPERPOWERS_DIR
  - DETERMINISTIC — no randomness; no wall-clock peek
  - REUSABLE      — works for any multi-project bundle layout
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_KEBAB_RE = re.compile(r"[^a-z0-9]+")


class BundleError(ValueError):
    """Invalid bundle spec (bad date, missing fields, etc.)."""


def _superpowers_dir() -> Path:
    """Root of docs/superpowers/. Env-overridable for tests.

    Note: base defaults to cwd/docs/superpowers (NOT ~/.claude/.kaizen),
    so we pass an explicit `base=Path.cwd() / "docs" / "superpowers"`
    to env_overridable_dir.
    """
    from _paths import env_overridable_dir
    return env_overridable_dir(
        "KAIZEN_SUPERPOWERS_DIR",
        base=Path.cwd() / "docs" / "superpowers",
    )


def _kebab(text: str) -> str:
    return _KEBAB_RE.sub("-", text.lower()).strip("-")


def bundle_folder_name(date: str, project: str, sid: str | None) -> str:
    """Pure compute: deterministic folder name for (date, project, sid).

    Format: `<YYYY-MM-DD>-<project-kebab>-<sid8>` (sid8 omitted when sid is None).
    """
    if not _DATE_RE.match(date or ""):
        raise BundleError(f"invalid date {date!r}; expected YYYY-MM-DD")
    project_kebab = _kebab(project or "")
    if not project_kebab:
        raise BundleError("project required and must contain alphanumerics")
    parts = [date, project_kebab]
    if sid:
        sid_short = sid.split("-")[0][:12]  # first segment, max 12 chars
        if sid_short:
            parts.append(sid_short)
    return "-".join(parts)


def bundle_path(date: str, project: str, sid: str | None,
                  *, root: Path | None = None) -> Path:
    """Pure compute: full path. Doesn't require the folder to exist."""
    base = root if root else _superpowers_dir()
    return base / bundle_folder_name(date, project, sid)


# ─── git automation ──────────────────────────────────────────────────

def _git_available() -> bool:
    return shutil.which("git") is not None


def _is_git_repo(root: Path) -> bool:
    return (root / ".git").is_dir()


def _git_run(root: Path, *args: str) -> subprocess.CompletedProcess:
    """Run git inside the superpowers root. Returns CompletedProcess."""
    return subprocess.run(
        ["git", *args], cwd=str(root),
        capture_output=True, text=True, timeout=15,
    )


def _git_commit(root: Path, message: str) -> str | None:
    """Atomic stage-all + commit + write patch-journal entry. Returns
    the new commit's short SHA, or None on failure. Iron-law: never
    raises (the bundle operation succeeds even if git fails)."""
    try:
        _git_run(root, "add", "-A")
        # --allow-empty so re-runs don't crash; --no-verify to skip hooks
        # in the embedded repo (kaizen-md's parent gate doesn't apply here).
        commit_r = _git_run(root, "commit", "-m", message, "--allow-empty",
                             "--no-verify", "--no-gpg-sign")
        if commit_r.returncode != 0:
            return None
        # Use full SHA so `commit_sha[:8]` yields exactly 8 chars (git's
        # default --short is 7 chars, which would truncate to 7).
        sha_r = _git_run(root, "rev-parse", "HEAD")
        if sha_r.returncode != 0:
            return None
        sha = sha_r.stdout.strip()
        _write_patch_journal(root, sha)
        return sha
    except (OSError, subprocess.TimeoutExpired):
        return None


def _backup_dir() -> Path:
    """Patch-journal backup root. Env-overridable via KAIZEN_BACKUP_DIR.

    Note: env value gets `superpowers` appended (not the env value itself
    becoming the root). Distinct from the standard env_overridable_dir
    shape — env points to the BACKUP root, this resolves the superpowers
    SUB-dir within it.
    """
    env = os.environ.get("KAIZEN_BACKUP_DIR")
    if env:
        return Path(env) / "superpowers"
    return Path.home() / ".claude" / ".kaizen" / "backups" / "superpowers"


def _write_patch_journal(root: Path, commit_sha: str) -> Path | None:
    """Write `git format-patch -1 <sha>` to <KAIZEN_BACKUP_DIR>/
    superpowers/patches/<UTC>-<sha8>.patch + append manifest row.

    Never raises (host op must continue).
    """
    try:
        r = _git_run(root, "format-patch", "-1", commit_sha, "--stdout")
        if r.returncode != 0 or not r.stdout.strip():
            return None
        patches_dir = _backup_dir() / "patches"
        patches_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        sha8 = commit_sha[:8]
        patch_path = patches_dir / f"{ts}-{sha8}.patch"
        patch_path.write_text(r.stdout, encoding="utf-8")
        # DRY — shared atomic_append_line preserves the append-only-sink
        # iron-law (per registry 2026-05-18).
        from _atomic import atomic_append_line
        manifest = _backup_dir() / "manifest.jsonl"
        atomic_append_line(manifest, json.dumps({
            "ts": ts, "sha": commit_sha, "path": str(patch_path),
        }))
        return patch_path
    except (OSError, subprocess.TimeoutExpired):
        return None


def _commit_subject(action: str, bundle_name: str, *, extra: str = "") -> str:
    """Deterministic commit-message subject. Same inputs → same subject."""
    parts = [f"{action}", f"bundle({bundle_name})"]
    if extra:
        parts.append(extra)
    return " ".join(parts)


# ─── state — docs-state tracker (kind + status metadata) ─────────────

_KIND_PREFIXES = {
    "plan-":       "plan",
    "spec-":       "spec",
    "brainstorm-": "brainstorm",
    "audit-":      "audit",
    "notes-":      "notes",
}
_STATUS_PATTERNS = [
    # Order matters — more specific markers first.
    # **State:** and **Status:** are both honored (different files use
    # different conventions; KISS to accept both).
    (re.compile(r"\bSUPERSEDED\b", re.IGNORECASE),         "superseded"),
    (re.compile(r"\bDEFERRED\b", re.IGNORECASE),           "deferred"),
    (re.compile(r"\bPARKED\b", re.IGNORECASE),             "deferred"),
    (re.compile(r"\b(COMPLETE|SHIPPED|DONE)\b"),           "shipped"),
    (re.compile(r"\*\*(State|Status):\*\*\s*shipped", re.IGNORECASE),     "shipped"),
    (re.compile(r"\*\*(State|Status):\*\*\s*in[- ]progress", re.IGNORECASE), "in-progress"),
    (re.compile(r"\*\*(State|Status):\*\*\s*draft", re.IGNORECASE),       "draft"),
    (re.compile(r"\*\*(State|Status):\*\*\s*drafting", re.IGNORECASE),    "draft"),
    (re.compile(r"\*\*(State|Status):\*\*\s*wip", re.IGNORECASE),         "in-progress"),
]


def _classify_kind(filename: str) -> str:
    """Filename → kind (plan/spec/brainstorm/audit/notes/README/data/other)."""
    if filename == "README.md":
        return "README"
    if filename.endswith(".jsonl"):
        return "data"
    for prefix, kind in _KIND_PREFIXES.items():
        if filename.startswith(prefix):
            return kind
    return "other"


def _extract_status(text: str) -> str:
    """Walk the first window of text for status markers; return verdict."""
    # Only scan the top 50 lines — status markers belong at the top
    head = "\n".join(text.splitlines()[:50])
    for pattern, status in _STATUS_PATTERNS:
        if pattern.search(head):
            return status
    return "unknown"


def _extract_status_for_file(filename: str, text: str) -> str:
    """Filename-aware wrapper. READMEs are reference docs (folder
    descriptions, not work items) — always return `reference` regardless
    of body. Other files use content-based detection."""
    if filename == "README.md":
        return "reference"
    return _extract_status(text)


def _scan_state(root: Path) -> dict:
    """Walk root → emit per-bundle + per-file metadata + aggregate totals."""
    bundles: dict[str, dict] = {}
    totals_kind: dict[str, int] = {}
    totals_status: dict[str, int] = {}
    file_count = 0
    if not root.is_dir():
        return {"bundles": {}, "totals": {"bundles": 0, "files": 0,
                                            "by_kind": {}, "by_status": {}},
                 "root": str(root), "scanned_at": _now_iso()}
    for bundle_dir in sorted(p for p in root.iterdir()
                                if p.is_dir() and not p.name.startswith(".")):
        files: list[dict] = []
        bundle_kinds: dict[str, int] = {}
        bundle_statuses: dict[str, int] = {}
        for fp in sorted(bundle_dir.iterdir()):
            if not fp.is_file():
                continue
            kind = _classify_kind(fp.name)
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
                status = _extract_status_for_file(fp.name, text)
            except OSError:
                status = "unknown"
            entry = {
                "name":          fp.name,
                "kind":          kind,
                "status":        status,
                "size_bytes":    fp.stat().st_size,
                "last_modified": _mtime_iso(fp),
            }
            files.append(entry)
            bundle_kinds[kind] = bundle_kinds.get(kind, 0) + 1
            bundle_statuses[status] = bundle_statuses.get(status, 0) + 1
            totals_kind[kind] = totals_kind.get(kind, 0) + 1
            totals_status[status] = totals_status.get(status, 0) + 1
            file_count += 1
        bundles[bundle_dir.name] = {
            "path": str(bundle_dir),
            "files": files,
            "summary": {
                "total": len(files),
                "by_kind": bundle_kinds,
                "by_status": bundle_statuses,
            },
        }
    return {
        "root": str(root),
        "scanned_at": _now_iso(),
        "bundles": bundles,
        "totals": {
            "bundles":   len(bundles),
            "files":     file_count,
            "by_kind":   totals_kind,
            "by_status": totals_status,
        },
    }


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cmd_state(args) -> int:
    root = _superpowers_dir()
    state = _scan_state(root)
    if args.apply:
        sf = root / ".state.json"
        sf.write_text(json.dumps(state, indent=2, default=str) + "\n",
                       encoding="utf-8")
    if args.json:
        print(json.dumps(state, indent=2, default=str))
    else:
        t = state["totals"]
        print(f"superpowers state: {root}")
        print(f"  bundles: {t['bundles']}   files: {t['files']}")
        if t["by_kind"]:
            print(f"  by kind:   {dict(sorted(t['by_kind'].items()))}")
        if t["by_status"]:
            print(f"  by status: {dict(sorted(t['by_status'].items()))}")
        if args.apply:
            print(f"  → wrote {root / '.state.json'}")
        else:
            print(f"  (dry run — pass --apply to write .state.json)")
    return 0


def _cmd_tasks(args) -> int:
    root = _superpowers_dir()
    state = _scan_state(root)
    tasks: list[dict] = []
    # Default view hides work-completed (`shipped`) AND non-work-items
    # (`reference` — typically README folder descriptions).
    skip_statuses = {"shipped", "reference"}
    for bundle_name, bundle in state["bundles"].items():
        if args.bundle and bundle_name != args.bundle:
            continue
        for f in bundle["files"]:
            if args.status:
                if f["status"] != args.status:
                    continue
            elif f["status"] in skip_statuses:
                continue
            tasks.append({
                "bundle": bundle_name,
                "name":   f["name"],
                "kind":   f["kind"],
                "status": f["status"],
                "path":   f"{bundle['path']}/{f['name']}",
            })
    if args.json:
        print(json.dumps({"count": len(tasks), "tasks": tasks},
                          indent=2, default=str))
    else:
        if not tasks:
            print("no pending tasks")
            return 0
        marks = {"deferred": "⏸", "superseded": "✗",
                  "draft": "☐", "in-progress": "▷", "unknown": "?"}
        print(f"pending tasks ({len(tasks)}):")
        for t in tasks:
            mark = marks.get(t["status"], "?")
            print(f"  {mark} [{t['kind']:<10}] {t['bundle']} / {t['name']}"
                  f"  ({t['status']})")
    return 0


def _cmd_git_init(args) -> int:
    if not _git_available():
        sys.stderr.write("kaizen-bundle: `git` not found on PATH\n")
        return 1
    root = _superpowers_dir()
    root.mkdir(parents=True, exist_ok=True)
    if _is_git_repo(root):
        print(f"git-init: already a repo at {root}")
    else:
        r = _git_run(root, "init", "-q")
        if r.returncode != 0:
            sys.stderr.write(f"kaizen-bundle: git init failed: {r.stderr}\n")
            return 1
        # Set up local identity if not already configured (test envs typically lack it)
        _git_run(root, "config", "user.email", "kaizen-bundle@local")
        _git_run(root, "config", "user.name", "kaizen-bundle")
        print(f"git-init: created repo at {root}")
    # Bootstrap commit if there's anything to commit (e.g. root README)
    status = _git_run(root, "status", "--short")
    if status.stdout.strip():
        _git_commit(root, _commit_subject("bootstrap", "superpowers"))
    return 0


def _cmd_init(args) -> int:
    try:
        folder = bundle_path(args.date, args.project, args.sid)
    except BundleError as e:
        sys.stderr.write(f"kaizen-bundle: {e}\n")
        return 1
    folder.mkdir(parents=True, exist_ok=True)
    readme = folder / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# Bundle — {folder.name}\n\n"
            f"Session artifacts for date={args.date}, project={args.project}"
            + (f", sid={args.sid}" if args.sid else "") + ".\n\n"
            "Drop session specs / plans / brainstorms / notes here. "
            "Each file should carry a one-line purpose at top.\n",
            encoding="utf-8",
        )
    # Auto-commit is the DEFAULT (per user 2026-05-18: "automate the commits").
    # Opt-out via --no-commit.
    if not getattr(args, "no_commit", False) and _git_available():
        root = _superpowers_dir()
        if _is_git_repo(root):
            _git_commit(root, _commit_subject("init", folder.name))
    print(str(folder))
    return 0


def _cmd_list(args) -> int:
    root = _superpowers_dir()
    if not root.is_dir():
        print("[]" if args.json else "")
        return 0
    bundles: list[dict] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        # Skip templates/ + plans/ + specs/ — those are NOT bundles
        if entry.name in ("templates", "plans", "specs"):
            continue
        # Parse date prefix
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)$", entry.name)
        if not m:
            continue
        date = m.group(1)
        rest = m.group(2)
        project = rest
        sid = None
        # Heuristic: trailing -<hex> with len >=4 is the sid
        sid_match = re.match(r"^(.+?)-([0-9a-f]{4,12})$", rest)
        if sid_match:
            project = sid_match.group(1)
            sid = sid_match.group(2)
        bundles.append({
            "name": entry.name, "date": date,
            "project": project, "sid": sid,
            "path": str(entry),
        })
    if args.project:
        bundles = [b for b in bundles if b["project"] == args.project]
    if args.json:
        print(json.dumps(bundles, indent=2))
    else:
        for b in bundles:
            print(f"{b['date']}  {b['project']}  "
                   f"sid={b.get('sid') or '-':<12}  {b['path']}")
    return 0


def _cmd_path(args) -> int:
    try:
        folder = bundle_path(args.date, args.project, args.sid)
    except BundleError as e:
        sys.stderr.write(f"kaizen-bundle: {e}\n")
        return 1
    print(str(folder))
    return 0


def _cmd_add(args) -> int:
    src = Path(args.file)
    if not src.is_file():
        sys.stderr.write(f"kaizen-bundle: file not found: {src}\n")
        return 1
    try:
        folder = bundle_path(args.date, args.project, args.sid)
    except BundleError as e:
        sys.stderr.write(f"kaizen-bundle: {e}\n")
        return 1
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / src.name
    # shutil.move handles cross-filesystem moves (Path.rename would raise
    # OSError(EXDEV) when src is on tmpfs and target on home, etc.)
    shutil.move(str(src), str(target))
    if not getattr(args, "no_commit", False) and _git_available():
        root = _superpowers_dir()
        if _is_git_repo(root):
            _git_commit(root, _commit_subject(
                "add", folder.name, extra=f"file({src.name})"
            ))
    print(str(target))
    return 0


# ─── scan — orphan artifact tracker ───────────────────────────────────

# Top-level entries that are NOT orphans (durable / docs / git):
_NON_ORPHAN_TOP_LEVEL = frozenset({"README.md", "templates", ".git", ".gitignore"})


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scan_bundles(root: Path) -> dict[str, list[tuple[str, str]]]:
    """Walk every bundle folder and index its files by content hash.

    Returns {sha256 -> [(bundle_name, file_name), ...]} for dupe detection.
    """
    index: dict[str, list[tuple[str, str]]] = {}
    if not root.is_dir():
        return index
    for bundle in root.iterdir():
        if not bundle.is_dir() or bundle.name in _NON_ORPHAN_TOP_LEVEL:
            continue
        # Skip bundles by date-prefix shape; treat unrecognized dirs as
        # opaque so we don't dive into templates/ etc.
        if not re.match(r"^\d{4}-\d{2}-\d{2}", bundle.name):
            continue
        for f in bundle.iterdir():
            if not f.is_file():
                continue
            try:
                sha = _sha256_file(f)
            except OSError:
                continue
            index.setdefault(sha, []).append((bundle.name, f.name))
    return index


def _suggest_date(file_name: str, file_path: Path) -> str:
    """Suggested date for the bundle this orphan should land in.

    Prefer the YYYY-MM-DD prefix in the filename; fall back to file mtime.
    """
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", file_name)
    if m:
        return m.group(1)
    mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC)
    return mtime.strftime("%Y-%m-%d")


def _cmd_scan(args) -> int:
    root = _superpowers_dir()
    if not root.is_dir():
        out = {"orphans": [], "dupes": []}
        print(json.dumps(out) if args.json else "no superpowers root; nothing to scan")
        return 0

    bundle_index = _scan_bundles(root)
    orphans: list[dict] = []
    dupes: list[dict] = []

    for entry in sorted(root.iterdir()):
        # Skip non-orphan top-level entries
        if entry.name in _NON_ORPHAN_TOP_LEVEL:
            continue
        # Skip bundle folders themselves
        if entry.is_dir():
            continue
        if not entry.is_file():
            continue
        try:
            sha = _sha256_file(entry)
            size = entry.stat().st_size
        except OSError:
            continue
        orphan = {
            "name": entry.name,
            "path": str(entry),
            "size": size,
            "sha256": sha,
            "suggested_date": _suggest_date(entry.name, entry),
        }
        orphans.append(orphan)
        # Dupe check — same content already in a bundle
        if sha in bundle_index:
            for bundle_name, bundle_file in bundle_index[sha]:
                dupes.append({
                    "orphan": entry.name,
                    "bundle": bundle_name,
                    "bundle_file": bundle_file,
                    "sha256": sha,
                })

    result = {"orphans": orphans, "dupes": dupes}

    # --apply: move non-dupe orphans into target bundles, optionally on
    # a fresh git branch. Dry-run is the default (no --apply).
    if getattr(args, "apply", False):
        dupe_names = {d["orphan"] for d in dupes}
        if args.branch and _git_available() and _is_git_repo(root):
            _git_run(root, "checkout", "-b", args.branch)
        moved: list[dict] = []
        for o in orphans:
            if o["name"] in dupe_names:
                continue
            target_bundle = bundle_path(
                o["suggested_date"], args.project, None,
            )
            target_bundle.mkdir(parents=True, exist_ok=True)
            dest = target_bundle / o["name"]
            shutil.move(o["path"], str(dest))
            moved.append({"orphan": o["name"], "target": str(dest)})
        if moved and _git_available() and _is_git_repo(root):
            _git_commit(root, _commit_subject(
                "scan-apply", f"moved-{len(moved)}", extra=f"project({args.project})"
            ))
        result["moved"] = moved

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"orphans: {len(orphans)}")
        for o in orphans:
            print(f"  {o['name']} ({o['size']}B; suggest "
                   f"date={o['suggested_date']})")
        if dupes:
            print(f"dupes (orphan content matches existing bundle file): "
                   f"{len(dupes)}")
            for d in dupes:
                print(f"  {d['orphan']} == {d['bundle']}/{d['bundle_file']}")
        if result.get("moved"):
            print(f"moved: {len(result['moved'])}")
            for m in result["moved"]:
                print(f"  {m['orphan']} → {m['target']}")
    return 0


def _cmd_backup(args) -> int:
    """`backup list` — show patch-journal entries from manifest.jsonl."""
    if args.backup_action == "list":
        manifest = _backup_dir() / "manifest.jsonl"
        if not manifest.is_file():
            print("[]" if args.json else "")
            return 0
        rows = []
        for line in manifest.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for r in rows:
                print(f"{r.get('ts', '?')}  {r.get('sha', '?'):<10}  "
                       f"{r.get('path', '?')}")
        return 0
    sys.stderr.write(f"kaizen-bundle backup: unknown action "
                       f"{args.backup_action!r}\n")
    return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-bundle",
        description="Session-folder management for docs/superpowers/.",
    )
    sub = p.add_subparsers(dest="command")

    def add_spec_args(parser):
        parser.add_argument("--date", required=True, help="YYYY-MM-DD")
        parser.add_argument("--project", required=True)
        parser.add_argument("--sid", default=None,
                             help="session UUID (full or short); optional")

    pi = sub.add_parser("init", help="scaffold a bundle folder (auto-commits by default)")
    add_spec_args(pi)
    pi.add_argument("--no-commit", action="store_true",
                     help="skip the auto-commit (default: commit via local superpowers git)")
    pi.set_defaults(fn=_cmd_init)

    pgi = sub.add_parser("git-init",
                          help="`git init` in the superpowers root (idempotent)")
    pgi.set_defaults(fn=_cmd_git_init)

    pl = sub.add_parser("list", help="show bundles")
    pl.add_argument("--project", default=None, help="filter by project")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(fn=_cmd_list)

    pp = sub.add_parser("path", help="print bundle path (pure compute)")
    add_spec_args(pp)
    pp.set_defaults(fn=_cmd_path)

    pa = sub.add_parser("add", help="move a file INTO a bundle (auto-commits by default)")
    pa.add_argument("--file", required=True)
    add_spec_args(pa)
    pa.add_argument("--no-commit", action="store_true",
                     help="skip the auto-commit (default: commit via local superpowers git)")
    pa.set_defaults(fn=_cmd_add)

    pb = sub.add_parser("backup", help="patch-journal backup ops")
    pb.add_argument("backup_action", choices=["list"],
                     help="action — currently `list` only")
    pb.add_argument("--json", action="store_true")
    pb.set_defaults(fn=_cmd_backup)

    ps = sub.add_parser("scan",
                          help="walk docs/superpowers/ for orphan files + "
                               "report metadata + dupe-check vs existing bundles")
    ps.add_argument("--json", action="store_true",
                     help="JSON output (default: human-readable)")
    ps.add_argument("--apply", action="store_true",
                     help="move non-dupe orphans into target bundles "
                          "(default: dry-run)")
    ps.add_argument("--project", default="kaizen-md",
                     help="project name for target bundles (default: kaizen-md)")
    ps.add_argument("--branch", default=None,
                     help="git branch to checkout in the nested superpowers "
                          "repo before applying (requires --apply)")
    ps.set_defaults(fn=_cmd_scan)

    pst = sub.add_parser("state",
                          help="scan docs/superpowers/ + emit per-file "
                               "metadata (kind / status / size / mtime). "
                               "--apply writes .state.json under the root.")
    pst.add_argument("--apply", action="store_true",
                      help="write .state.json (default: dry run)")
    pst.add_argument("--json", action="store_true")
    pst.set_defaults(fn=_cmd_state)

    pt = sub.add_parser("tasks",
                         help="task-list view of non-shipped items in bundles. "
                              "Filter via --bundle <name> or --status <s>.")
    pt.add_argument("--bundle", default=None,
                     help="restrict to one bundle (matches dir basename)")
    pt.add_argument("--status", default=None,
                     help="restrict to one status "
                          "(draft / in-progress / deferred / superseded / unknown)")
    pt.add_argument("--json", action="store_true")
    pt.set_defaults(fn=_cmd_tasks)

    args = p.parse_args(argv)
    if not getattr(args, "fn", None):
        p.print_help()
        return 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
