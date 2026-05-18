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
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_KEBAB_RE = re.compile(r"[^a-z0-9]+")


class BundleError(ValueError):
    """Invalid bundle spec (bad date, missing fields, etc.)."""


def _superpowers_dir() -> Path:
    """Root of docs/superpowers/. Env-overridable for tests."""
    env = os.environ.get("KAIZEN_SUPERPOWERS_DIR")
    if env:
        return Path(env)
    return Path.cwd() / "docs" / "superpowers"


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


def _git_commit(root: Path, message: str) -> None:
    """Atomic stage-all + commit. Iron-law: never raises (the bundle
    operation succeeds even if git fails)."""
    try:
        _git_run(root, "add", "-A")
        # --allow-empty so re-runs don't crash; --no-verify to skip hooks
        # in the embedded repo (kaizen-md's parent gate doesn't apply here).
        _git_run(root, "commit", "-m", message, "--allow-empty",
                  "--no-verify", "--no-gpg-sign")
    except (OSError, subprocess.TimeoutExpired):
        pass


def _commit_subject(action: str, bundle_name: str, *, extra: str = "") -> str:
    """Deterministic commit-message subject. Same inputs → same subject."""
    parts = [f"{action}", f"bundle({bundle_name})"]
    if extra:
        parts.append(extra)
    return " ".join(parts)


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
    if getattr(args, "commit", False) and _git_available():
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
    src.rename(target)
    if getattr(args, "commit", False) and _git_available():
        root = _superpowers_dir()
        if _is_git_repo(root):
            _git_commit(root, _commit_subject(
                "add", folder.name, extra=f"file({src.name})"
            ))
    print(str(target))
    return 0


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

    pi = sub.add_parser("init", help="scaffold a bundle folder")
    add_spec_args(pi)
    pi.add_argument("--commit", action="store_true",
                     help="auto-commit the new bundle in the local superpowers git repo")
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

    pa = sub.add_parser("add", help="move a file INTO a bundle")
    pa.add_argument("--file", required=True)
    add_spec_args(pa)
    pa.add_argument("--commit", action="store_true",
                     help="auto-commit the moved file in the local superpowers git repo")
    pa.set_defaults(fn=_cmd_add)

    args = p.parse_args(argv)
    if not getattr(args, "fn", None):
        p.print_help()
        return 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
