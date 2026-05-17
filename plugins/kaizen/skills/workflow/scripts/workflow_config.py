#!/usr/bin/env python3
"""kaizen workflow_config — persist + read the per-repo / user-global
workflow-shape defaults (scope / run-mode / disciplines / threshold).

Sister to ``session_mode.py`` — that one captures the CURRENT session's
intake choice (in-process for one shell session); this one captures
the PERSISTENT defaults a project (or the user globally) wants future
sessions to start from.

Storage:

  project scope → ``<repo>/.kaizen/workflow.json``
  global scope  → ``${KAIZEN_DIR:-~/.claude/.kaizen}/workflow-global.json``

CLI (stdlib-only):

  workflow_config.py set [--scope project|global] \
      [--run-mode routine|loop|schema] [--routine NAME] [--schema NAME] \
      [--disciplines a,b,c] [--threshold 25|50|75|85|disabled] \
      [--loop-its N] [--loop-stop a,b]
  workflow_config.py get   [--scope project|global] [--json]
  workflow_config.py show  [--scope project|global]
  workflow_config.py path  [--scope project|global]
  workflow_config.py reset [--scope project|global] [--yes]

When ``--scope`` is omitted, **project** is the default for set/reset
(writes land near the code), **project-with-global-fallback** for get/show
(reads merge project on top of global).

Schema: ``skills/workflow/domain/schemas/workflow-config.schema.json``.
Override the project file via ``KAIZEN_WORKFLOW_CONFIG_PATH`` (test sandbox).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Any


_VALID_SCOPES = ("project", "global")
_VALID_RUN_MODES = ("routine", "loop", "schema")
_VALID_THRESHOLDS = (25, 50, 75, 85)
_VALID_DISCIPLINES = (
    # coding-style
    "kiss", "yagni", "dry", "solid", "soc", "lod",
    # structure
    "onion-ddd", "hexagonal", "clean-arch", "dip", "bounded-contexts",
    # process
    "tdd", "boy-scout", "convention", "karpathy",
)
_VALID_LOOP_STOP = ("promise", "ledger-empty", "iteration-cap", "manual-cancel")


# ─── Path resolution ─────────────────────────────────────────────────


def _project_path() -> Path:
    """Resolve <repo>/.kaizen/workflow.json (test override honored)."""
    override = os.environ.get("KAIZEN_WORKFLOW_CONFIG_PATH")
    if override:
        return Path(override)
    # cwd-anchored; find repo root by walking up to find .git/
    cur = Path.cwd().resolve()
    while cur != cur.parent:
        if (cur / ".git").exists():
            return cur / ".kaizen" / "workflow.json"
        cur = cur.parent
    return Path.cwd() / ".kaizen" / "workflow.json"


def _global_path() -> Path:
    """Resolve ~/.claude/.kaizen/workflow-global.json (KAIZEN_DIR honored)."""
    override = os.environ.get("KAIZEN_WORKFLOW_GLOBAL_CONFIG_PATH")
    if override:
        return Path(override)
    root = Path(os.environ.get("KAIZEN_DIR",
                                 Path.home() / ".claude" / ".kaizen"))
    return root / "workflow-global.json"


def _resolve(scope: str) -> Path:
    if scope == "project":
        return _project_path()
    if scope == "global":
        return _global_path()
    raise SystemExit(f"workflow_config: unknown scope: {scope!r}")


# ─── I/O ─────────────────────────────────────────────────────────────


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"workflow_config: cannot read {path}: {e}")


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def _merged() -> dict[str, Any]:
    """Project overrides global. Used by `get` / `show` default reads."""
    out = dict(_read(_global_path()))
    out.update(_read(_project_path()))
    return out


# ─── Validation ──────────────────────────────────────────────────────


def _validate_disciplines(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    picks = [d.strip().lower() for d in raw.split(",") if d.strip()]
    bad = [d for d in picks if d not in _VALID_DISCIPLINES]
    if bad:
        raise SystemExit(
            f"workflow_config: unknown discipline(s): {', '.join(bad)}\n"
            f"  valid: {', '.join(_VALID_DISCIPLINES)}"
        )
    return picks


def _validate_threshold(raw: str | None) -> int | None | str:
    if raw is None:
        return None  # field unchanged
    if raw == "disabled":
        return "disabled"
    try:
        v = int(raw)
    except ValueError:
        raise SystemExit(f"workflow_config: --threshold must be int or 'disabled', got {raw!r}")
    if v not in _VALID_THRESHOLDS:
        raise SystemExit(
            f"workflow_config: --threshold {v} not in {_VALID_THRESHOLDS}"
        )
    return v


def _validate_loop_stop(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    picks = [s.strip().lower() for s in raw.split(",") if s.strip()]
    bad = [s for s in picks if s not in _VALID_LOOP_STOP]
    if bad:
        raise SystemExit(
            f"workflow_config: unknown loop-stop condition(s): {', '.join(bad)}\n"
            f"  valid: {', '.join(_VALID_LOOP_STOP)}"
        )
    return picks


# ─── Subcommands ─────────────────────────────────────────────────────


def cmd_set(args: argparse.Namespace) -> int:
    scope = args.scope or "project"
    path = _resolve(scope)
    data = _read(path)
    data["version"] = 1
    data["scope"] = scope

    if args.run_mode is not None:
        if args.run_mode not in _VALID_RUN_MODES:
            raise SystemExit(
                f"workflow_config: --run-mode must be one of {_VALID_RUN_MODES}"
            )
        data["run_mode"] = args.run_mode
    if args.routine is not None:
        data["routine"] = args.routine
    if args.schema is not None:
        data["schema_name"] = args.schema

    disc = _validate_disciplines(args.disciplines)
    if disc is not None:
        data["disciplines"] = disc

    thr = _validate_threshold(args.threshold)
    if thr is not None:
        data["auto_handoff_threshold"] = (
            None if thr == "disabled" else thr
        )

    if args.loop_its is not None or args.loop_stop is not None:
        loop_block = dict(data.get("loop", {}))
        if args.loop_its is not None:
            if args.loop_its < 1:
                raise SystemExit("workflow_config: --loop-its must be >= 1")
            loop_block["max_iterations"] = args.loop_its
        stop = _validate_loop_stop(args.loop_stop)
        if stop is not None:
            loop_block["stop_conditions"] = stop
        data["loop"] = loop_block

    data["updated_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")

    _write(path, data)
    print(f"workflow_config: wrote {path} (scope={scope})")
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    if args.scope:
        data = _read(_resolve(args.scope))
    else:
        data = _merged()
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        if not data:
            print("workflow_config: (empty)")
            return 0
        for k in sorted(data):
            print(f"{k}: {data[k]}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    if args.scope:
        data = _read(_resolve(args.scope))
        label = args.scope
    else:
        data = _merged()
        label = "project ← global (merged)"
    print(f"=== workflow-config ({label}) ===")
    if not data:
        print("  (empty — run `kaizen-workflow-config set ...` to populate)")
        return 0
    for k in sorted(data):
        v = data[k]
        if isinstance(v, list):
            print(f"  {k}: [{', '.join(map(str, v))}]")
        elif isinstance(v, dict):
            print(f"  {k}:")
            for sk, sv in sorted(v.items()):
                print(f"    {sk}: {sv}")
        else:
            print(f"  {k}: {v}")
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    scope = args.scope or "project"
    print(_resolve(scope))
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    scope = args.scope or "project"
    path = _resolve(scope)
    if not path.exists():
        print(f"workflow_config: no file at {path} — nothing to reset")
        return 0
    if not args.yes:
        print(f"workflow_config: would delete {path} (re-run with --yes)")
        return 1
    path.unlink()
    print(f"workflow_config: deleted {path}")
    return 0


# ─── argparse wiring ─────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="workflow_config",
        description="Persist + read kaizen workflow-shape defaults "
                     "(scope / run-mode / disciplines / threshold).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("set", help="Write/update fields in the config")
    s.add_argument("--scope", choices=_VALID_SCOPES, default=None)
    s.add_argument("--run-mode", choices=_VALID_RUN_MODES, default=None)
    s.add_argument("--routine", default=None,
                    help="When run-mode=routine, which routine to default to.")
    s.add_argument("--schema", default=None,
                    help="When run-mode=schema, which schema to default to.")
    s.add_argument("--disciplines", default=None,
                    help="Comma-separated discipline tags (kiss,dry,solid,...).")
    s.add_argument("--threshold", default=None,
                    help="Auto-handoff threshold: 25 / 50 / 75 / 85 / disabled.")
    s.add_argument("--loop-its", type=int, default=None,
                    help="When run-mode=loop, default --its value.")
    s.add_argument("--loop-stop", default=None,
                    help="Comma-separated loop stop conditions "
                         "(promise,ledger-empty,iteration-cap,manual-cancel).")
    s.set_defaults(func=cmd_set)

    g = sub.add_parser("get", help="Print resolved config")
    g.add_argument("--scope", choices=_VALID_SCOPES, default=None)
    g.add_argument("--json", action="store_true")
    g.set_defaults(func=cmd_get)

    h = sub.add_parser("show", help="Human-readable view of the config")
    h.add_argument("--scope", choices=_VALID_SCOPES, default=None)
    h.set_defaults(func=cmd_show)

    ph = sub.add_parser("path", help="Print resolved file path")
    ph.add_argument("--scope", choices=_VALID_SCOPES, default=None)
    ph.set_defaults(func=cmd_path)

    r = sub.add_parser("reset", help="Delete the config file")
    r.add_argument("--scope", choices=_VALID_SCOPES, default=None)
    r.add_argument("--yes", action="store_true",
                    help="Confirm destructive op (default: dry-run).")
    r.set_defaults(func=cmd_reset)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
