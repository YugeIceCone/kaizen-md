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


def cmd_get_key(args: argparse.Namespace) -> int:
    """Print a single scalar field from the merged config. Lists print
    as comma-separated. Missing keys print nothing and exit 0 so bash
    consumers can `VAL=$(... get-key X)` + `[ -z "$VAL" ]`."""
    data = _merged()
    cur: Any = data
    for part in args.dotted_key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return 0
        cur = cur[part]
    if isinstance(cur, list):
        print(",".join(str(x) for x in cur))
    elif cur is None or isinstance(cur, bool):
        print("" if cur is None else ("true" if cur else "false"))
    else:
        print(cur)
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


# ─── dry-run (classify task → bucket → stage list, no execution) ─────


def _resolve_schema_dir(name: str) -> Path | None:
    """Locate <schema_name>/ — env override, project CWD walk, user, built-in.

    Mirrors workflow_runner.resolve_schema() ordering but adds the
    KAIZEN_PROJECT_ROOT_OVERRIDE env hook for tests + arbitrary CWD.
    """
    # 1. Test-time override
    override = os.environ.get("KAIZEN_PROJECT_ROOT_OVERRIDE")
    if override:
        candidate = Path(override) / ".kaizen" / "workflow" / "schemas" / name
        if (candidate / "schema.yaml").exists():
            return candidate
    # 2. project (CWD walk to .git)
    cur = Path.cwd().resolve()
    while cur != cur.parent:
        if (cur / ".git").exists():
            candidate = cur / ".kaizen" / "workflow" / "schemas" / name
            if (candidate / "schema.yaml").exists():
                return candidate
            break
        cur = cur.parent
    # 3. user
    user_schemas = Path(
        os.environ.get("KAIZEN_DIR", Path.home() / ".claude" / ".kaizen")
    ) / "schemas"
    candidate = user_schemas / name
    if (candidate / "schema.yaml").exists():
        return candidate
    # 4. built-in
    builtin = Path(__file__).resolve().parent.parent.parent / "schemas"
    candidate = builtin / name
    if (candidate / "schema.yaml").exists():
        return candidate
    return None


def _parse_bucket_stage_skips(rubric_text: str) -> dict[str, dict[str, list[str]]]:
    """Extract the `bucket_stage_skips:` section from rubric.yaml.

    Lightweight stdlib parser — the section is project-specific and not
    handled by schema_cli.BucketWalker.from_yaml. Returns
    {bucket_name: {'keep': [...], 'skip': [...]}}.
    """
    out: dict[str, dict[str, list[str]]] = {}
    lines = rubric_text.splitlines()
    in_section = False
    current_bucket: str | None = None
    current_field: str | None = None
    for line in lines:
        stripped = line.split("#", 1)[0].rstrip()
        if not stripped:
            continue
        # Section start
        if stripped.startswith("bucket_stage_skips:"):
            in_section = True
            continue
        if not in_section:
            continue
        # New top-level key ends the section
        if not line.startswith((" ", "\t")) and ":" in stripped:
            break
        # Bucket name (2-space indent)
        if line.startswith("  ") and not line.startswith("    "):
            name = stripped.strip().rstrip(":")
            if name and ":" in stripped:
                current_bucket = name
                out.setdefault(current_bucket, {"keep": [], "skip": []})
                current_field = None
            continue
        # Field name (4-space indent) — `keep:` / `skip:`
        if line.startswith("    ") and not line.startswith("      "):
            content = stripped.strip()
            if content.startswith("keep:") or content.startswith("skip:"):
                field, _, rest = content.partition(":")
                current_field = field.strip()
                rest = rest.strip()
                if rest.startswith("[") and rest.endswith("]") and current_bucket:
                    items = [s.strip().strip("\"'") for s in rest[1:-1].split(",") if s.strip()]
                    out[current_bucket][current_field] = items
    return out


def cmd_dry_run(args) -> int:
    """Classify a task without executing it: signals → bucket → stages."""
    import importlib.util  # noqa: I001
    # Lazy import to avoid cost on hot path of other subcommands.
    # schema_cli canonical at scripts/rules/; legacy shim at scripts/.
    _here = Path(__file__).resolve().parent
    _plugin_root = _here.parent.parent
    for _p in (_here, _plugin_root / "scripts" / "rules",
               _plugin_root / "skills" / "workflow" / "scripts"):
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
    import schema_cli as _sc  # noqa: E402

    # Schema name: --schema arg, else persisted schema_name in merged config
    schema_name = getattr(args, "schema", None)
    if not schema_name:
        cfg = _merged()
        schema_name = cfg.get("schema_name")
    if not schema_name:
        print("workflow_config dry-run: no --schema given and none persisted",
              file=sys.stderr)
        return 2

    schema_dir = _resolve_schema_dir(schema_name)
    if schema_dir is None:
        print(f"workflow_config dry-run: schema {schema_name!r} not found",
              file=sys.stderr)
        return 1

    schema_path = schema_dir / "schema.yaml"
    sigs_path = schema_dir / "_signals.py"
    rubric_path = schema_dir / "rubric.yaml"

    if not sigs_path.exists():
        print(f"workflow_config dry-run: missing {sigs_path}", file=sys.stderr)
        return 1
    if not rubric_path.exists():
        print(f"workflow_config dry-run: missing {rubric_path}", file=sys.stderr)
        return 1

    # Load _signals.py from the schema dir
    spec = importlib.util.spec_from_file_location("_per_rubric_signals", sigs_path)
    sigs_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sigs_mod)

    # Compute signals
    paths = [p.strip() for p in (args.paths or "").split(",") if p.strip()]
    dirs = [d.strip() for d in (args.dirs or "").split(",") if d.strip()]
    signals = sigs_mod.compute_signals(args.prompt or "", paths, dirs)

    # Walk rubric
    walker = _sc.BucketWalker.from_yaml(rubric_path)
    result = walker.evaluate(signals)

    # bucket_stage_skips (project-specific extension)
    skips_map = _parse_bucket_stage_skips(rubric_path.read_text(encoding="utf-8"))
    bucket_skips = skips_map.get(result.bucket, {"keep": [], "skip": []})

    payload = {
        "schema":       schema_name,
        "schema_path":  str(schema_path),
        "bucket":       result.bucket,
        "method":       result.method,
        "confidence":   result.confidence,
        "rationale":    result.rationale,
        "signals":      signals,
        "keep_stages":  bucket_skips.get("keep", []),
        "skip_stages":  bucket_skips.get("skip", []),
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"[workflow_config dry-run] schema={schema_name}")
        print(f"  bucket:      {result.bucket}")
        print(f"  method:      {result.method}  (confidence {result.confidence:.2f})")
        print(f"  rationale:   {result.rationale}")
        if bucket_skips.get("keep"):
            print(f"  keep stages: {', '.join(bucket_skips['keep'])}")
        if bucket_skips.get("skip"):
            print(f"  skip stages: {', '.join(bucket_skips['skip'])}")
    return 0


def cmd_run(args) -> int:
    """Start a schema run — `kaizen-workflow-config run [--schema X] [--force]`.

    Thin wrapper that resolves schema_name (from --schema or persisted
    config) and delegates to workflow_runner.cmd_start. Phase 4 of
    /kaizen:workflow full-automation pipeline.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import workflow_runner as _wr  # noqa: E402

    schema_name = getattr(args, "schema", None)
    if not schema_name:
        cfg = _merged()
        schema_name = cfg.get("schema_name")
    if not schema_name:
        print("workflow_config run: no --schema given and none persisted "
              "(set via `workflow_config set --schema X`)", file=sys.stderr)
        return 1
    return _wr.cmd_start(schema_name, force=bool(getattr(args, "force", False)))


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

    gk = sub.add_parser("get-key", help="Print a single scalar value from "
                                          "the merged config (shell-friendly).")
    gk.add_argument("dotted_key", help="Dotted path, e.g. loop.max_iterations")
    gk.set_defaults(func=cmd_get_key)

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

    dr = sub.add_parser(
        "dry-run",
        help="Classify a task (rubric walk) without executing — emits "
              "bucket + stage skip/keep list. Reads schema_name from "
              "persisted config unless --schema given.",
    )
    dr.add_argument("--prompt", default="",
                     help="Task description (free text). Default: empty.")
    dr.add_argument("--paths", default="",
                     help="Comma-separated touched-file paths.")
    dr.add_argument("--dirs", default="",
                     help="Comma-separated newly-created dirs.")
    dr.add_argument("--schema", default=None,
                     help="Override the persisted schema_name.")
    dr.add_argument("--json", action="store_true",
                     help="Emit envelope JSON instead of prose.")
    dr.set_defaults(func=cmd_dry_run)

    rn = sub.add_parser(
        "run",
        help="Start a schema run — initializes state.json. Reads "
              "schema_name from persisted config unless --schema given. "
              "Thin wrapper over `workflow_runner start`.",
    )
    rn.add_argument("--schema", default=None,
                     help="Override the persisted schema_name.")
    rn.add_argument("--force", action="store_true",
                     help="Overwrite existing state.json if present.")
    rn.set_defaults(func=cmd_run)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
