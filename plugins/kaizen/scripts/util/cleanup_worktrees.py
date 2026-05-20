"""kaizen-cleanup-worktrees — find + remove merged git worktrees.

Phase 5.A of the symbol-search arc. Useful for any worktree-driven
workflow (kaizen-implementer subagent runs, /loop, parallel-branches
kit) — not parallel-branches-specific.

Algorithm:
  1. `git worktree list --porcelain` → list of worktrees + their HEAD
     branches.
  2. For each non-default worktree, check if its branch is fully merged
     into the default branch (`git branch --merged <default>`).
  3. Default behavior: print the candidates (dry-run).
  4. With `--apply`: `git worktree remove <path>` for each merged.

Pure subprocess wrapper; no external deps. Never deletes a worktree
without explicit `--apply` (per kaizen no-deletions-without-auth
discipline).

## Subcommands

    kaizen-cleanup-worktrees           # default — dry-run list
    kaizen-cleanup-worktrees --apply   # actually remove
    kaizen-cleanup-worktrees --json    # structured output

## Env

    KAIZEN_DEFAULT_BRANCH    override default branch detection
                              (else: `git symbolic-ref refs/remotes/origin/HEAD`
                              then fallback to "main" / "master")
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

def _git(*args: str, cwd: Path | None = None) -> tuple[int, str]:
    """Run git, return (rc, stdout). stderr discarded."""
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True, text=True, timeout=10, check=False,
        )
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""

def detect_default_branch(cwd: Path | None = None) -> str:
    """Best-effort default-branch detection."""
    env = os.environ.get("KAIZEN_DEFAULT_BRANCH")
    if env:
        return env
    rc, out = _git("symbolic-ref", "--short", "refs/remotes/origin/HEAD",
                    cwd=cwd)
    if rc == 0 and out.strip():
        # e.g. "origin/master" → "master"
        return out.strip().rsplit("/", 1)[-1]
    # Fallback: probe local branches in conventional order.
    for cand in ("main", "master"):
        rc, _ = _git("rev-parse", "--verify", cand, cwd=cwd)
        if rc == 0:
            return cand
    return "main"

def list_worktrees(cwd: Path | None = None) -> list[dict]:
    """Parse `git worktree list --porcelain`. Returns list of dicts
    with {path, branch, head, locked, prunable}."""
    rc, out = _git("worktree", "list", "--porcelain", cwd=cwd)
    if rc != 0:
        return []
    worktrees: list[dict] = []
    current: dict = {}
    for line in out.splitlines():
        if not line:
            if current:
                worktrees.append(current)
                current = {}
            continue
        if " " in line:
            key, _, val = line.partition(" ")
        else:
            key, val = line, ""
        if key == "worktree":
            current = {"path": val, "branch": "", "head": "",
                       "locked": False, "prunable": False}
        elif key == "HEAD":
            current["head"] = val
        elif key == "branch":
            # `refs/heads/foo` → `foo`
            current["branch"] = val.rsplit("/", 1)[-1]
        elif key == "locked":
            current["locked"] = True
        elif key == "prunable":
            current["prunable"] = True
    if current:
        worktrees.append(current)
    return worktrees

def merged_branches(default_branch: str, cwd: Path | None = None) -> set[str]:
    """Branches fully merged into default_branch."""
    rc, out = _git("branch", "--merged", default_branch, cwd=cwd)
    if rc != 0:
        return set()
    merged = set()
    for line in out.splitlines():
        # `* main` / `  feature-foo` / `+ worktree-bar`
        name = line.strip().lstrip("*+ ").strip()
        if name:
            merged.add(name)
    return merged

def find_removable(cwd: Path | None = None) -> list[dict]:
    """List worktrees whose branch is merged + not the default + not locked.

    Default-branch worktree itself is always excluded. Locked + prunable
    worktrees are excluded (user has explicit reason; prune is its own op).
    """
    default = detect_default_branch(cwd)
    worktrees = list_worktrees(cwd)
    merged = merged_branches(default, cwd)
    out: list[dict] = []
    for wt in worktrees:
        if wt.get("locked") or wt.get("prunable"):
            continue
        branch = wt.get("branch", "")
        if not branch or branch == default:
            continue
        if branch in merged:
            out.append(wt)
    return out

def remove_worktree(path: str, cwd: Path | None = None) -> tuple[bool, str]:
    """`git worktree remove <path>`. Returns (ok, msg)."""
    rc, out = _git("worktree", "remove", path, cwd=cwd)
    return (rc == 0,
            (out.strip() or f"removed {path}") if rc == 0
            else f"failed (rc={rc}): {out.strip()[:200]}")

def _cmd_list(args) -> int:
    candidates = find_removable()
    if args.json:
        print(json.dumps({"data": {"removable": candidates,
                                    "count": len(candidates)}}))
    else:
        if not candidates:
            print("kaizen-cleanup-worktrees: no merged worktrees to remove.")
            return 0
        print(f"kaizen-cleanup-worktrees: {len(candidates)} merged worktree(s) "
              "removable:")
        for c in candidates:
            print(f"  - {c['path']}  (branch={c['branch']})")
        print("\nRun with --apply to remove.")
    return 0

def _cmd_apply(args) -> int:
    candidates = find_removable()
    if not candidates:
        print("kaizen-cleanup-worktrees: no merged worktrees to remove.")
        return 0
    results = []
    for c in candidates:
        ok, msg = remove_worktree(c["path"])
        results.append({"path": c["path"], "branch": c["branch"],
                         "ok": ok, "msg": msg})
        if not args.json:
            tag = "✓" if ok else "✗"
            print(f"{tag} {c['path']}  ({msg})")
    if args.json:
        print(json.dumps({"data": {"results": results,
                                    "removed": sum(1 for r in results if r["ok"])}}))
    return 0 if all(r["ok"] for r in results) else 1

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-cleanup-worktrees",
        description="Find + remove git worktrees whose branch is merged.",
    )
    p.add_argument("--apply", action="store_true",
                   help="Actually remove (default: dry-run list)")
    p.add_argument("--json", action="store_true",
                   help="Machine-readable output envelope")
    args = p.parse_args(argv)
    return _cmd_apply(args) if args.apply else _cmd_list(args)

if __name__ == "__main__":
    sys.exit(main())
