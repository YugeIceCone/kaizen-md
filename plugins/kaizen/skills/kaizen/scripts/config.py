#!/usr/bin/env python3
"""kaizen config — SSOT parser for `.kaizen.toml`.

Replaces the per-consumer `grep -E '^key' | sed` pattern that lived in
pre-commit.sh, statusline.sh, install.sh. Every consumer (bash + Python)
calls into this module so a new config key only changes one parse site.

## Layout

`.kaizen.toml` is a flat TOML file at repo root. Recognized keys:

    compile_check_cmd  = "cargo check --workspace"
    verify_cmd         = "cargo test --workspace --quiet"
    backlog_path       = ".workflow/backlog.md"
    architecture_log   = ".workflow/progress.md"

Unknown keys are preserved but not used by the gate. Missing keys fall
back to the `DEFAULTS` dict.

## CLI

    config.py                 # print all key=value pairs (newline-separated)
    config.py <key>           # print just that key's value (or empty string)
    config.py <key> --default <fallback>  # print value, defaulting if missing
    config.py --json          # full config as JSON

## Library

    from config import load_config
    cfg = load_config()       # auto-finds repo root from cwd
    cfg.get("backlog_path")   # → ".workflow/backlog.md"

## Repo detection

`repo_root()` walks up from cwd looking for `.git/` OR `.kaizen.toml`.
If neither found, returns None and `load_config()` returns DEFAULTS.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


DEFAULTS: dict = {
    "compile_check_cmd": "",
    "verify_cmd": "",
    "backlog_path": ".workflow/backlog.md",
    "architecture_log": ".workflow/progress.md",
}


def repo_root(start: Path | None = None) -> Path | None:
    """Walk up from `start` (default: cwd) looking for `.git/` or `.kaizen.toml`.
    Returns the directory containing either, or None if nothing found."""
    cur = (start or Path.cwd()).resolve()
    while True:
        if (cur / ".git").exists() or (cur / ".kaizen.toml").exists():
            return cur
        if cur.parent == cur:
            return None
        cur = cur.parent


def config_path(repo: Path | None = None) -> Path | None:
    r = repo if repo is not None else repo_root()
    return (r / ".kaizen.toml") if r is not None else None


def load_config(repo: Path | None = None) -> dict:
    """Load `.kaizen.toml` and merge over DEFAULTS. Returns DEFAULTS on any
    error (missing file, parse failure, no tomllib). Never raises."""
    p = config_path(repo)
    if p is None or not p.exists():
        return DEFAULTS.copy()
    if tomllib is None:
        # Python <3.11 — degraded grep-style fallback
        return _legacy_parse(p)
    try:
        data = tomllib.loads(p.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return DEFAULTS.copy()
    result = DEFAULTS.copy()
    if isinstance(data, dict):
        # Only stringify scalar values for bash-callable output;
        # nested tables stay as dicts in the Python-callable path.
        for k, v in data.items():
            result[k] = v
    return result


def _legacy_parse(p: Path) -> dict:
    """Fallback for Python <3.11 without tomllib. Handles only top-level
    `key = "value"` and `key = value` lines (no tables, no nested)."""
    result = DEFAULTS.copy()
    try:
        text = p.read_text()
    except OSError:
        return result
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        result[key] = val
    return result


def get(key: str, default: str = "", repo: Path | None = None) -> str:
    """Convenience: fetch one key as a string. Bash callers use this."""
    cfg = load_config(repo)
    v = cfg.get(key, default)
    return str(v) if v is not None else default


# ─── CLI ─────────────────────────────────────────────────────────────


KNOWN_KEYS = set(DEFAULTS.keys()) | {
    "plan_dir",
    "allow_deletion_env",
    "skip_tdd_check_env",
    "brain_path",
    "project_memory_path",
    # Trace-index knobs (v1.11.0+)
    "trace_embedding_model",
    "trace_index_path",
}


def validate(repo: Path | None = None) -> dict:
    """Validate the loaded config against KNOWN_KEYS + filesystem checks.

    Returns a dict with `ok` (bool), `errors` (list of str — block), and
    `warnings` (list of str — surface but not block). v1.12.0+."""
    out = {"ok": True, "errors": [], "warnings": [], "path": None}
    cp = config_path(repo)
    if cp is None:
        out["warnings"].append("no .kaizen.toml found in this repo (or any parent)")
        return out
    out["path"] = str(cp)

    cfg = load_config(repo)

    for key in cfg:
        if key not in KNOWN_KEYS:
            out["warnings"].append(f"unknown key {key!r} — typo? or future-version field?")

    # Filesystem checks for path-valued keys
    if cfg.get("backlog_path"):
        bp_abs = (repo or repo_root() or Path.cwd()) / cfg["backlog_path"]
        if not bp_abs.parent.exists():
            out["warnings"].append(
                f"backlog_path={cfg['backlog_path']!r} parent dir doesn't exist: {bp_abs.parent}")

    if cfg.get("compile_check_cmd"):
        first_word = cfg["compile_check_cmd"].split()[0] if cfg["compile_check_cmd"] else ""
        if first_word:
            import shutil as _sh
            if _sh.which(first_word) is None:
                out["warnings"].append(
                    f"compile_check_cmd starts with {first_word!r} but that's not on PATH")

    if cfg.get("brain_path"):
        bp = Path(str(cfg["brain_path"]).replace("~", str(Path.home())))
        if not bp.exists():
            out["warnings"].append(f"brain_path doesn't exist: {bp}")

    return out


def main():
    p = argparse.ArgumentParser(prog="config.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("key", nargs="?", default=None,
                   help="config key to look up (omit to list all)")
    p.add_argument("--default", default="",
                   help="fallback if key missing (default: empty string)")
    p.add_argument("--json", action="store_true",
                   help="print full config as JSON")
    p.add_argument("--path", action="store_true",
                   help="print the config file's absolute path (empty if not found)")
    p.add_argument("--validate", action="store_true",
                   help="check schema + filesystem; exit 1 on errors, 0 with warnings ok")
    args = p.parse_args()

    if args.validate:
        v = validate()
        print(json.dumps(v, indent=2, default=str))
        if v["errors"]:
            sys.exit(1)
        return

    if args.path:
        cp = config_path()
        print(cp if cp is not None else "")
        return

    if args.json:
        print(json.dumps(load_config(), indent=2, default=str))
        return

    if args.key is None:
        # List all key=value pairs
        cfg = load_config()
        for k in sorted(cfg.keys()):
            v = cfg[k]
            if isinstance(v, (dict, list)):
                continue  # skip nested for bash-callable shape
            print(f"{k}={v}")
        return

    print(get(args.key, args.default))


if __name__ == "__main__":
    main()
