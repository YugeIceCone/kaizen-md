#!/usr/bin/env python3
"""kaizen hygiene — auto-applicable cleanups + drift checks.

Stdlib-only. Each check returns a structured finding the daemon (or a
human via `kaizen hygiene`) can act on. `fix` applies SAFE cleanups
only — destructive ops are gated by explicit subcommands.

## Checks

    cache          versions on disk > KAIZEN_KEEP_VERSIONS (default 2)
    backups        kaizen backups > KAIZEN_KEEP_BACKUPS  (default 10)
    inbox          drained inbox entries > KAIZEN_INBOX_TTL_DAYS (default 7)
    rules          brain rules schema validation
    backlog        backlog.md drifted from backlog.json

## Subcommands

    check          run all checks, report findings (exit 0/1)
    fix            run all checks + apply safe cleanups
    check-<name>   run a single check
    fix-<name>     fix a single check
    json           full report as JSON (machine-readable)

## Safe fixes

Only the following are applied automatically:

    cache.prune    rm -rf old cache version dirs (keep newest N)
    backups.prune  rm -f old kaizen backup tarballs (keep newest N)
    inbox.purge    rm drained inbox entries older than TTL
    backlog.render re-render backlog.md from .json if drifted

Anything that touches source code or user-owned files in unfamiliar
ways is NEVER auto-applied. Run check-mode + decide manually.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
CACHE_BASE = HOME / ".claude" / "plugins" / "cache" / "kaizen-md" / "kaizen"

# v1.22.0+ unified layout — sourced from _paths (SSOT). Falls back to the
# legacy hardcoded locations if _paths is unavailable (very old install).
try:
    _HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(_HERE))
    sys.path.insert(0, str(_HERE.parent / "io"))
    import _paths as _p  # type: ignore
    BACKUP_BASE = _p.BACKUP_DIR
    INBOX_DIR = _p.INBOX_DIR
except ImportError:
    BACKUP_BASE = HOME / ".claude" / ".kaizen" / "backups"
    INBOX_DIR = Path(os.environ.get("KAIZEN_INBOX_DIR", HOME / ".claude" / ".kaizen" / "inbox"))


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name, "")
    return int(v) if v.isdigit() else default


KEEP_VERSIONS = lambda: _env_int("KAIZEN_KEEP_VERSIONS", 2)
KEEP_BACKUPS = lambda: _env_int("KAIZEN_KEEP_BACKUPS", 10)
INBOX_TTL_DAYS = lambda: _env_int("KAIZEN_INBOX_TTL_DAYS", 7)


from _time import utc_now  # M5 dedup
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-hygiene", tool_version="1.0.0")


def now() -> dt.datetime:
    return utc_now()


# ─── Individual checks ───────────────────────────────────────────────


def check_cache() -> dict:
    if not CACHE_BASE.exists():
        return {"name": "cache", "ok": True, "note": "no cache dir"}
    versions = sorted([p.name for p in CACHE_BASE.iterdir() if p.is_dir()], key=lambda v: [int(x) if x.isdigit() else 0 for x in v.split(".")])
    keep = KEEP_VERSIONS()
    if len(versions) <= keep:
        return {"name": "cache", "ok": True, "total": len(versions), "keep": keep}
    candidates = versions[:-keep]
    return {
        "name": "cache",
        "ok": False,
        "total": len(versions),
        "keep": keep,
        "prune_candidates": candidates,
        "bytes_freeable": sum(_dir_size(CACHE_BASE / v) for v in candidates),
    }


def fix_cache(finding: dict) -> dict:
    if finding.get("ok"):
        return {"name": "cache", "applied": False, "reason": "already ok"}
    removed = []
    for v in finding.get("prune_candidates", []):
        target = CACHE_BASE / v
        if target.exists():
            _rmtree(target)
            removed.append(v)
    return {"name": "cache", "applied": True, "removed": removed, "count": len(removed)}


def check_backups() -> dict:
    if not BACKUP_BASE.exists():
        return {"name": "backups", "ok": True, "note": "no backup dir"}
    findings = []
    for repo_slug_dir in BACKUP_BASE.iterdir():
        if not repo_slug_dir.is_dir():
            continue
        tarballs = sorted(repo_slug_dir.glob("*.tar.gz"), key=lambda p: p.stat().st_mtime)
        keep = KEEP_BACKUPS()
        if len(tarballs) <= keep:
            continue
        candidates = tarballs[:-keep]
        findings.append({
            "repo": repo_slug_dir.name,
            "total": len(tarballs),
            "keep": keep,
            "prune": [p.name for p in candidates],
            "bytes_freeable": sum(p.stat().st_size for p in candidates),
        })
    return {"name": "backups", "ok": len(findings) == 0, "repos": findings}


def fix_backups(finding: dict) -> dict:
    if finding.get("ok"):
        return {"name": "backups", "applied": False, "reason": "already ok"}
    removed = []
    for repo in finding.get("repos", []):
        for name in repo.get("prune", []):
            tarball = BACKUP_BASE / repo["repo"] / name
            if tarball.exists():
                tarball.unlink()
                removed.append(f"{repo['repo']}/{name}")
    return {"name": "backups", "applied": True, "removed": removed, "count": len(removed)}


def check_inbox() -> dict:
    if not INBOX_DIR.exists():
        return {"name": "inbox", "ok": True, "note": "no inbox dir"}
    ttl_seconds = INBOX_TTL_DAYS() * 86400
    cutoff = now().timestamp() - ttl_seconds
    stale = []
    for f in INBOX_DIR.glob("*.json"):
        try:
            m = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not m.get("drained"):
            continue
        if f.stat().st_mtime < cutoff:
            stale.append(f.name)
    return {
        "name": "inbox",
        "ok": len(stale) == 0,
        "ttl_days": INBOX_TTL_DAYS(),
        "stale": stale,
    }


def fix_inbox(finding: dict) -> dict:
    if finding.get("ok"):
        return {"name": "inbox", "applied": False, "reason": "already ok"}
    removed = []
    for name in finding.get("stale", []):
        f = INBOX_DIR / name
        if f.exists():
            f.unlink()
            removed.append(name)
    return {"name": "inbox", "applied": True, "removed": removed, "count": len(removed)}


def check_rules() -> dict:
    rules_py = _scripts_dir() / "rules.py"
    if not rules_py.exists():
        return {"name": "rules", "ok": True, "note": "rules.py not found"}
    try:
        r = subprocess.run(["python3", str(rules_py), "validate"], capture_output=True, text=True, timeout=10)
        return {
            "name": "rules",
            "ok": r.returncode == 0,
            "output": r.stdout.strip() + (("\nstderr: " + r.stderr.strip()) if r.stderr.strip() else ""),
        }
    except Exception as e:
        return {"name": "rules", "ok": False, "error": str(e)}


def fix_rules(finding: dict) -> dict:
    # Rules schema errors require human attention — no auto-fix.
    return {"name": "rules", "applied": False, "reason": "manual edit required (see check output)"}


def check_backlog() -> dict:
    """Walk known kaizen-installed repos and check backlog drift via backlog.py verify."""
    backlog_py = _scripts_dir() / "backlog.py"
    if not backlog_py.exists():
        return {"name": "backlog", "ok": True, "note": "backlog.py not found"}
    issues = []
    # Discover repos via the cache install symlinks. Falls back to known cwd.
    candidates = _discover_kaizen_repos()
    for repo in candidates:
        config = repo / ".kaizen.toml"
        if not config.exists():
            continue
        try:
            r = subprocess.run(
                ["python3", str(backlog_py), "verify"],
                capture_output=True, text=True, timeout=10, cwd=repo,
            )
            if r.returncode != 0:
                issues.append({"repo": str(repo), "output": r.stdout.strip() + r.stderr.strip()})
        except Exception as e:
            issues.append({"repo": str(repo), "error": str(e)})
    return {"name": "backlog", "ok": len(issues) == 0, "issues": issues, "checked": len(candidates)}


def fix_backlog(finding: dict) -> dict:
    backlog_py = _scripts_dir() / "backlog.py"
    if finding.get("ok"):
        return {"name": "backlog", "applied": False, "reason": "already ok"}
    rendered = []
    for issue in finding.get("issues", []):
        repo = issue.get("repo")
        if not repo:
            continue
        try:
            subprocess.run(["python3", str(backlog_py), "render"], cwd=repo, timeout=10, check=True)
            rendered.append(repo)
        except Exception:
            pass
    return {"name": "backlog", "applied": True, "rendered": rendered, "count": len(rendered)}


# ─── Helpers ─────────────────────────────────────────────────────────


def _scripts_dir() -> Path:
    return Path(__file__).resolve().parent


def _dir_size(p: Path) -> int:
    total = 0
    if not p.exists():
        return 0
    for f in p.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def _rmtree(p: Path) -> None:
    import shutil
    shutil.rmtree(p, ignore_errors=True)


def _discover_kaizen_repos() -> list[Path]:
    """Find repos with .kaizen.toml. Reads ~/.kaizen-installs.txt if present
    (daemon writes this on each kaizen:setup)."""
    registry = HOME / ".kaizen-installs.txt"
    if registry.exists():
        out = []
        for line in registry.read_text().splitlines():
            line = line.strip()
            if line and Path(line).exists():
                out.append(Path(line))
        return out
    # Fallback: check cwd
    cwd = Path.cwd()
    if (cwd / ".kaizen.toml").exists():
        return [cwd]
    return []


# ─── Orchestration ───────────────────────────────────────────────────


CHECKS = {
    "cache": (check_cache, fix_cache),
    "backups": (check_backups, fix_backups),
    "inbox": (check_inbox, fix_inbox),
    "rules": (check_rules, fix_rules),
    "backlog": (check_backlog, fix_backlog),
}


def run_all_checks() -> dict:
    return {name: c() for name, (c, _) in CHECKS.items()}


def run_all_fixes() -> dict:
    out = {}
    for name, (check, fix) in CHECKS.items():
        finding = check()
        out[name] = {"finding": finding, "fix": fix(finding)}
    return out


def summary(results: dict, mode: str = "check") -> str:
    lines = [f"kaizen hygiene ({mode}) — {now().isoformat(timespec='seconds')}"]
    for name, result in results.items():
        if mode == "check":
            ok = result.get("ok")
            symbol = "✓" if ok else "✗"
            note = result.get("note", "")
            if not ok:
                # Brief detail
                if name == "cache":
                    note = f"{len(result.get('prune_candidates', []))} versions to prune"
                elif name == "backups":
                    note = f"{sum(len(r.get('prune', [])) for r in result.get('repos', []))} backups to prune"
                elif name == "inbox":
                    note = f"{len(result.get('stale', []))} drained entries > {result.get('ttl_days', 7)}d"
                elif name == "rules":
                    note = "validation failed (see --verbose)"
                elif name == "backlog":
                    note = f"{len(result.get('issues', []))} repos drifted"
            lines.append(f"  {symbol} {name:8} {note}")
        else:  # fix
            f = result.get("fix", {})
            applied = f.get("applied")
            symbol = "✓" if applied else "∘"
            n = f.get("count", "")
            if applied:
                lines.append(f"  {symbol} {name:8} applied ({n})")
            else:
                lines.append(f"  {symbol} {name:8} {f.get('reason', '')}")
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser(prog="hygiene.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", default="check",
                   help="check | fix | check-<name> | fix-<name> | json | langs")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--root", help="repo root for `langs` (default: cwd)")
    p.add_argument("--json", action="store_true",
                   help="JSON output (works with `langs`)")
    args = p.parse_args()

    cmd = args.cmd

    # X5: per-language composite hygiene (cargo audit / pip-audit /
    # npm audit / govulncheck / tsc --noEmit). Detects languages via
    # manifest files at --root and runs each probe; missing tools are
    # skipped (not hard failures) so CI envs without every audit tool
    # installed still pass.
    if cmd == "langs":
        from pathlib import Path as _Path
        sys.path.insert(0, str(_Path(__file__).resolve().parent))
        import _hygiene_lang as kz_hlang
        root = (
            _Path(args.root).expanduser().resolve()
            if args.root else _Path.cwd()
        )
        result = kz_hlang.run_composite(root)
        print(kz_hlang.format_report(result, json_mode=args.json))
        sys.exit(0 if result.ok else 1)

    if cmd == "json":
        results = run_all_checks()
        any_bad = any(not r.get("ok") for r in results.values())
        _emit(results, verdict="red" if any_bad else "green",
              counts={"checks": len(results),
                      "failed": sum(1 for r in results.values() if not r.get("ok"))})
        sys.exit(1 if any_bad else 0)

    if cmd == "check":
        results = run_all_checks()
        print(summary(results, "check"))
        if args.verbose:
            print("")
            _emit(results)
        sys.exit(1 if any(not r.get("ok") for r in results.values()) else 0)

    if cmd == "fix":
        results = run_all_fixes()
        print(summary(results, "fix"))
        if args.verbose:
            print("")
            _emit(results)
        sys.exit(0)

    if cmd.startswith("check-") and cmd[6:] in CHECKS:
        name = cmd[6:]
        result = CHECKS[name][0]()
        print(json.dumps(result, indent=2, default=str))
        sys.exit(1 if not result.get("ok") else 0)

    if cmd.startswith("fix-") and cmd[4:] in CHECKS:
        name = cmd[4:]
        finding = CHECKS[name][0]()
        result = CHECKS[name][1](finding)
        print(json.dumps({"finding": finding, "fix": result}, indent=2, default=str))
        sys.exit(0)

    sys.exit(f"unknown: {cmd}\ntry: check | fix | check-<name> | fix-<name> | json")


if __name__ == "__main__":
    main()
