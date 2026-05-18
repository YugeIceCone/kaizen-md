#!/usr/bin/env python3
"""kaizen workflow_runner — load + validate + topo-order schema-driven workflows.

OpenSpec-inspired declarative workflow schemas. A schema is a yaml file
declaring artifacts (DAG nodes) with `requires:` edges + an `apply:` block
gating implementation. The runner resolves the schema by name, parses it
(stdlib-only), validates the DAG, and emits stage order for workflow.sh.

Resolution order (first hit wins):
    1. <repo>/.kaizen/workflow/schemas/<name>/schema.yaml   (project; v1.22+ canonical)
    2. ~/.claude/.kaizen/schemas/<name>/schema.yaml   (user; v1.22+ canonical)
    3. <plugin>/schemas/<name>/schema.yaml           (built-in, this dir)

Subcommands:
    list                      List schemas across all 3 paths (one per line: <name> <path>)
    show <name>               Print parsed schema as JSON
    validate <name>           Structural + DAG validation; exit 1 on any error
    stages <name>             Print topo-ordered stage ids, one per line (workflow.sh consumes this)
    artifact <name> <id>      Print one artifact dict as JSON (so the agent sees its description)
    branches <name> <id>      Print branch_high/medium/low alternative-path stage lists for an
                              artifact as JSON. Advisory in v1.15.0 — the agent reads this after
                              completing the artifact (e.g. design.md) and decides which path to
                              walk based on its Confidence Score. workflow.sh state machine is
                              not modified; the agent uses /kaizen:schema branches output to plan.

Schema format (minimal subset, stdlib-parseable):

    name: <string>
    version: <int>
    description: |
      Multi-line OK.

    artifacts:
      - id: <kebab-id>
        generates: <output-path>
        template: <relative-path|null>
        requires: [<id>, ...]   # may be empty list
        description: |
          Multi-line OK.

    apply:
      gate: <artifact-id>
      progress: <file-path>
      description: |
        Multi-line OK.

Env:
    KAIZEN_PLUGIN_SCHEMAS     Override built-in schemas dir (default: ../schemas relative to this script)
    KAIZEN_USER_SCHEMAS       Override user schemas dir (default: ~/.claude/kaizen-schemas)
"""

from __future__ import annotations

import json
import os
import sys
from collections import deque
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent.parent.parent  # skills/workflow-routing/scripts → plugin root

# v1.22.0+: pull path defaults from the kaizen plugin's _paths SSOT.
# v1.30.0+: renamed from skills/kaizen/scripts → skills/workflow/scripts.
_KAIZEN_SCRIPTS = PLUGIN_ROOT / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(_KAIZEN_SCRIPTS))
import _paths as _p  # noqa: E402

BUILTIN_DIR = Path(
    os.environ.get("KAIZEN_PLUGIN_SCHEMAS", PLUGIN_ROOT / "schemas")
)
USER_DIR = _p.USER_SCHEMAS  # ~/.claude/.kaizen/schemas/ (was ~/.claude/kaizen-schemas/)
PROJECT_DIR = _p.project_schemas_dir()  # <repo>/.kaizen/workflow/schemas/ (was .workflow/schemas/)


# ─── Parser ───────────────────────────────────────────────────────────
#
# Stdlib-only YAML subset parser. Covers exactly what our schemas use:
# top-level scalars, nested mappings (2-space indent), a list of mappings
# under `artifacts:`, inline lists `[a, b]`, and `|` multi-line scalars.
# Not a general YAML parser — strict layout match required.


def _strip_comment(line: str) -> str:
    """Remove # comment from end of line, respecting quotes."""
    in_quote = None
    out = []
    for ch in line:
        if in_quote:
            out.append(ch)
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ('"', "'"):
            in_quote = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out).rstrip()


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        return v[1:-1]
    return v


def _parse_inline_list(s: str) -> list[str]:
    """Parse `[a, b, "c"]` → ['a', 'b', 'c']. Brackets stripped already."""
    s = s.strip()
    if not s:
        return []
    return [_unquote(x.strip()) for x in s.split(",") if x.strip()]


def _scalar(value: str) -> object:
    v = value.strip()
    if v == "" or v == "~" or v.lower() == "null":
        return None
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    if v.startswith("[") and v.endswith("]"):
        return _parse_inline_list(v[1:-1])
    return _unquote(v)


def parse_schema_yaml(text: str) -> dict:
    """Parse our schema subset. Returns dict; raises ValueError on layout mismatch."""
    lines = text.split("\n")
    out: dict = {"artifacts": [], "apply": {}}
    i = 0
    n = len(lines)

    def is_blank(s: str) -> bool:
        return not _strip_comment(s).strip()

    def indent_of(s: str) -> int:
        return len(s) - len(s.lstrip(" "))

    while i < n:
        raw = lines[i]
        line = _strip_comment(raw)
        if is_blank(raw) or not line.strip():
            i += 1
            continue
        # Top-level scalar or block start
        if indent_of(raw) != 0:
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest == "|":
            # Multi-line literal block — collect indented lines
            i += 1
            block_lines = []
            block_indent = None
            while i < n:
                if not lines[i].strip():
                    block_lines.append("")
                    i += 1
                    continue
                ind = indent_of(lines[i])
                if ind == 0:
                    break
                if block_indent is None:
                    block_indent = ind
                block_lines.append(lines[i][block_indent:])
                i += 1
            out[key] = "\n".join(block_lines).rstrip()
            continue
        if rest:
            out[key] = _scalar(rest)
            i += 1
            continue
        # Empty value — either list of mappings (artifacts) or nested map (apply)
        if key == "artifacts":
            i += 1
            artifacts: list[dict] = []
            cur: dict | None = None
            while i < n:
                raw_i = lines[i]
                if not raw_i.strip():
                    i += 1
                    continue
                ind = indent_of(raw_i)
                if ind == 0:
                    break
                stripped = _strip_comment(raw_i).strip()
                if stripped.startswith("- "):
                    if cur is not None:
                        artifacts.append(cur)
                    cur = {}
                    item = stripped[2:]
                    if ":" in item:
                        ik, _, iv = item.partition(":")
                        cur[ik.strip()] = _scalar(iv) if iv.strip() else None
                    i += 1
                    continue
                if cur is None:
                    i += 1
                    continue
                if ":" in stripped:
                    ik, _, iv = stripped.partition(":")
                    ik = ik.strip()
                    iv = iv.strip()
                    if iv == "|":
                        i += 1
                        block_lines = []
                        block_indent = None
                        while i < n:
                            if not lines[i].strip():
                                block_lines.append("")
                                i += 1
                                continue
                            sub_ind = indent_of(lines[i])
                            if sub_ind <= ind:
                                break
                            if block_indent is None:
                                block_indent = sub_ind
                            block_lines.append(lines[i][block_indent:])
                            i += 1
                        cur[ik] = "\n".join(block_lines).rstrip()
                        continue
                    cur[ik] = _scalar(iv) if iv else None
                i += 1
            if cur is not None:
                artifacts.append(cur)
            out["artifacts"] = artifacts
            continue
        if key == "apply":
            i += 1
            apply_block: dict = {}
            while i < n:
                raw_i = lines[i]
                if not raw_i.strip():
                    i += 1
                    continue
                ind = indent_of(raw_i)
                if ind == 0:
                    break
                stripped = _strip_comment(raw_i).strip()
                if ":" in stripped:
                    ik, _, iv = stripped.partition(":")
                    ik = ik.strip()
                    iv = iv.strip()
                    if iv == "|":
                        i += 1
                        block_lines = []
                        block_indent = None
                        while i < n:
                            if not lines[i].strip():
                                block_lines.append("")
                                i += 1
                                continue
                            sub_ind = indent_of(lines[i])
                            if sub_ind <= ind:
                                break
                            if block_indent is None:
                                block_indent = sub_ind
                            block_lines.append(lines[i][block_indent:])
                            i += 1
                        apply_block[ik] = "\n".join(block_lines).rstrip()
                        continue
                    apply_block[ik] = _scalar(iv) if iv else None
                i += 1
            out["apply"] = apply_block
            continue
        i += 1
    return out


# ─── Resolution ───────────────────────────────────────────────────────


# v1.30.0+: schemas can ship as .yaml, .yml, or .json — extension dispatch.
# JSON is preferred for LLM-generated schemas (LLMs emit valid JSON more
# reliably than indent-sensitive YAML); YAML is preferred for human-authored
# (comments + multiline). Both parse to the same in-memory dict shape.
_SCHEMA_EXTS = (".yaml", ".yml", ".json")


def resolve_schema(name: str) -> Path | None:
    for base in (PROJECT_DIR, USER_DIR, BUILTIN_DIR):
        for ext in _SCHEMA_EXTS:
            candidate = base / name / f"schema{ext}"
            if candidate.is_file():
                return candidate
    return None


def _parse_schema_file(path: Path) -> dict:
    """Dispatch by extension. JSON: stdlib json.loads. YAML: our subset parser."""
    text = path.read_text()
    if path.suffix == ".json":
        import json as _json  # local — keeps top-of-file imports lean
        return _json.loads(text)
    return parse_schema_yaml(text)


def load_schema(name: str) -> dict:
    """Load + validate. Returns a dict (back-compat); raises on schema bugs.

    v1.30.0+: passes the result through `validate_schema_typed` for fail-fast
    detection of duplicate ids, dangling `requires:` refs, missing gate, etc.
    The existing `validate_schema(dict) -> list[str]` is kept for callers that
    want a soft error list rather than an exception."""
    path = resolve_schema(name)
    if path is None:
        sys.exit(f"schema not found: {name!r} (searched: {PROJECT_DIR}, {USER_DIR}, {BUILTIN_DIR})")
    data = _parse_schema_file(path)
    # Fail-fast validation. If we got here with a malformed schema, the user
    # wants to know NOW, not after the workflow runner has scheduled phases
    # off a broken graph.
    errors = validate_schema(data)
    if errors:
        msg = "\n  • ".join(errors)
        sys.exit(f"schema {name!r} failed validation:\n  • {msg}")
    return data


# ─── Topo-sort (Kahn) + validation ────────────────────────────────────


def topo_order(artifacts: list[dict]) -> list[str]:
    """Return artifact ids in execution order. Raises on cycle/unknown ref."""
    nodes = {a["id"]: a for a in artifacts}
    if len(nodes) != len(artifacts):
        raise ValueError("duplicate artifact id")
    indeg = {aid: 0 for aid in nodes}
    fwd: dict[str, list[str]] = {aid: [] for aid in nodes}
    for a in artifacts:
        for req in a.get("requires") or []:
            if req not in nodes:
                raise ValueError(f"artifact {a['id']!r} requires unknown {req!r}")
            fwd[req].append(a["id"])
            indeg[a["id"]] += 1
    queue = deque(sorted([aid for aid, d in indeg.items() if d == 0]))
    out: list[str] = []
    while queue:
        cur = queue.popleft()
        out.append(cur)
        for nxt in sorted(fwd[cur]):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    if len(out) != len(nodes):
        cycle_nodes = [aid for aid, d in indeg.items() if d > 0]
        raise ValueError(f"cycle detected among: {cycle_nodes}")
    return out


def validate_schema(schema: dict) -> list[str]:
    errs: list[str] = []
    if not schema.get("name"):
        errs.append("missing name")
    if not isinstance(schema.get("artifacts"), list) or not schema["artifacts"]:
        errs.append("missing artifacts (must be non-empty list)")
        return errs
    seen = set()
    for a in schema["artifacts"]:
        aid = a.get("id")
        if not aid:
            errs.append("artifact missing id")
            continue
        if aid in seen:
            errs.append(f"duplicate artifact id: {aid}")
        seen.add(aid)
        if not isinstance(a.get("requires") or [], list):
            errs.append(f"artifact {aid}: requires must be a list")
    apply_block = schema.get("apply") or {}
    if apply_block:
        gate = apply_block.get("gate")
        if gate and gate not in seen:
            errs.append(f"apply.gate {gate!r} is not a known artifact id")
    if not errs:
        try:
            topo_order(schema["artifacts"])
        except ValueError as e:
            errs.append(f"DAG: {e}")
    return errs


# ─── List ──────────────────────────────────────────────────────────────


def list_schemas() -> list[tuple[str, Path]]:
    """Return (name, path) for every schema found across the 3 dirs. First hit wins on name conflicts.

    v1.30.0+: scans for .yaml, .yml, AND .json variants. The first
    extension found per dir-precedence-tier wins."""
    seen: dict[str, Path] = {}
    for base in (PROJECT_DIR, USER_DIR, BUILTIN_DIR):
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if not entry.is_dir():
                continue
            for ext in _SCHEMA_EXTS:
                schema_path = entry / f"schema{ext}"
                if schema_path.is_file():
                    seen.setdefault(entry.name, schema_path)
                    break
    return list(seen.items())


# ─── CLI ───────────────────────────────────────────────────────────────


# ─── State machine (Phase 3 of /kaizen:workflow automation) ──────────


def _state_path() -> Path:
    """Resolve <repo>/.kaizen/workflow/state.json (env override honored)."""
    override = os.environ.get("KAIZEN_PROJECT_ROOT_OVERRIDE")
    if override:
        return Path(override) / ".kaizen" / "workflow" / "state.json"
    cur = Path.cwd().resolve()
    while cur != cur.parent:
        if (cur / ".git").exists():
            return cur / ".kaizen" / "workflow" / "state.json"
        cur = cur.parent
    return Path.cwd() / ".kaizen" / "workflow" / "state.json"


def _load_state() -> dict | None:
    p = _state_path()
    if not p.exists():
        return None
    state = json.loads(p.read_text(encoding="utf-8"))
    if "current_stage" not in state or "schema" not in state:
        print(
            f"workflow_runner: legacy state.json at {p} (missing "
            "`current_stage`/`schema`; written by an older runner). "
            "Run `kaizen-workflow run state-reset --yes` to clear it, "
            "then `start <schema>` to re-init.",
            file=sys.stderr,
        )
        return None
    return state


def _save_state(state: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _emit_trace(evt: str, data: dict) -> None:
    """Best-effort kaizen trace emit. Never raises (trace is observability,
    not behaviour). Honored env: KAIZEN_TRACE_DIR + KAIZEN_TRACE_DISABLE.
    """
    try:
        import trace as _trace
        _trace.append_event({
            "ts":   _now_iso(),
            "src":  "tool",
            "evt":  evt,
            "tool": "kaizen-workflow-runner",
            "data": data,
        })
    except Exception:
        pass


def cmd_start(name: str, force: bool = False) -> int:
    """Initialize state.json for a schema. Refuses to clobber unless --force."""
    sp = _state_path()
    if sp.exists() and not force:
        print(
            f"workflow_runner: state already exists at {sp} — "
            f"pass --force to overwrite",
            file=sys.stderr,
        )
        return 1
    schema_path = resolve_schema(name)
    if schema_path is None:
        print(f"workflow_runner: schema {name!r} not found", file=sys.stderr)
        return 1
    schema = load_schema(name)
    errs = validate_schema(schema)
    if errs:
        for e in errs:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1
    order = topo_order(schema["artifacts"])
    now = _now_iso()
    state = {
        "schema":        name,
        "schema_path":   str(schema_path),
        "current_stage": order[0] if order else None,
        "completed":     [],
        "remaining":     order[1:] if order else [],
        "started_at":    now,
        "advanced_at":   now,
        "done":          False,
    }
    _save_state(state)
    _emit_trace("schema.start", {
        "schema":        name,
        "first_stage":   state["current_stage"],
        "stage_count":   len(order),
    })
    print(f"workflow_runner: started {name!r} @ stage {state['current_stage']!r}")
    return 0


def cmd_current(emit_json: bool = False) -> int:
    state = _load_state()
    if state is None:
        print("workflow_runner: no state (run `start <schema>` first)",
              file=sys.stderr)
        return 1
    if state.get("done"):
        print("workflow_runner: schema done — no current stage", file=sys.stderr)
        return 1
    schema = load_schema(state["schema"])
    cur_id = state["current_stage"]
    for a in schema["artifacts"]:
        if a.get("id") == cur_id:
            if emit_json:
                print(json.dumps(a, indent=2))
            else:
                print(f"current stage: {cur_id}")
                print(f"  description: {a.get('description', '').strip()}")
                print(f"  gate:        {a.get('gate', '').strip()}")
            return 0
    print(f"workflow_runner: current stage {cur_id!r} missing from schema",
          file=sys.stderr)
    return 1


def cmd_advance() -> int:
    state = _load_state()
    if state is None:
        print("workflow_runner: no state (run `start <schema>` first)",
              file=sys.stderr)
        return 1
    if state.get("done"):
        print("workflow_runner: schema already done — nothing to advance",
              file=sys.stderr)
        return 1
    cur = state["current_stage"]
    state["completed"].append(cur)
    if state["remaining"]:
        next_stage = state["remaining"].pop(0)
        state["current_stage"] = next_stage
        state["advanced_at"] = _now_iso()
        _save_state(state)
        _emit_trace("schema.advance", {
            "schema":          state["schema"],
            "from":            cur,
            "to":              next_stage,
            "completed_count": len(state["completed"]),
        })
        print(f"workflow_runner: {cur!r} done → advanced to {next_stage!r}")
    else:
        state["current_stage"] = None
        state["done"] = True
        state["advanced_at"] = _now_iso()
        _save_state(state)
        _emit_trace("schema.done", {
            "schema":            state["schema"],
            "stages_completed":  state["completed"],
        })
        print(f"workflow_runner: {cur!r} done → schema complete")
    return 0


def cmd_state(emit_json: bool = False) -> int:
    state = _load_state()
    if state is None:
        print("workflow_runner: no state", file=sys.stderr)
        return 1
    if emit_json:
        print(json.dumps(state, indent=2))
    else:
        print(f"schema:        {state['schema']}")
        print(f"current_stage: {state.get('current_stage') or '(done)'}")
        print(f"completed:     {state.get('completed', [])}")
        print(f"remaining:     {state.get('remaining', [])}")
        print(f"done:          {state.get('done', False)}")
    return 0


def cmd_state_reset(yes: bool = False) -> int:
    sp = _state_path()
    if not sp.exists():
        print("workflow_runner: no state to reset")
        return 0
    if not yes:
        print(f"workflow_runner: would delete {sp} — pass --yes to apply")
        return 0
    # Best-effort: read schema name before deletion for the trace payload
    schema_name = None
    try:
        existing = json.loads(sp.read_text(encoding="utf-8"))
        schema_name = existing.get("schema")
    except Exception:
        pass
    sp.unlink()
    _emit_trace("schema.reset", {"schema": schema_name})
    print(f"workflow_runner: deleted {sp}")
    return 0


def _need(arg_idx: int, what: str) -> str:
    if len(sys.argv) <= arg_idx:
        sys.exit(f"usage: {sys.argv[0]} {sys.argv[1] if len(sys.argv) > 1 else '<cmd>'} <{what}>")
    return sys.argv[arg_idx]


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"

    if cmd == "list":
        rows = list_schemas()
        if not rows:
            print("(no schemas found)")
            return
        for name, path in rows:
            tier = (
                "project" if PROJECT_DIR in path.parents
                else "user" if USER_DIR in path.parents
                else "built-in"
            )
            print(f"  {name:<24} [{tier}] {path}")

    elif cmd == "show":
        name = _need(2, "schema-name")
        print(json.dumps(load_schema(name), indent=2))

    elif cmd == "validate":
        name = _need(2, "schema-name")
        errs = validate_schema(load_schema(name))
        if errs:
            for e in errs:
                print(f"  ✗ {e}")
            sys.exit(1)
        print(f"  ✓ schema {name!r} valid")

    elif cmd == "stages":
        name = _need(2, "schema-name")
        schema = load_schema(name)
        errs = validate_schema(schema)
        if errs:
            for e in errs:
                print(f"# error: {e}", file=sys.stderr)
            sys.exit(1)
        for stage in topo_order(schema["artifacts"]):
            print(stage)

    elif cmd == "artifact":
        name = _need(2, "schema-name")
        aid = _need(3, "artifact-id")
        schema = load_schema(name)
        for a in schema["artifacts"]:
            if a.get("id") == aid:
                print(json.dumps(a, indent=2))
                return
        sys.exit(f"artifact {aid!r} not found in schema {name!r}")

    elif cmd == "branches":
        name = _need(2, "schema-name")
        aid = _need(3, "artifact-id")
        schema = load_schema(name)
        for a in schema["artifacts"]:
            if a.get("id") != aid:
                continue
            out = {k[len("branch_"):]: v for k, v in a.items() if k.startswith("branch_")}
            if not out:
                sys.exit(f"artifact {aid!r} has no branch_* fields")
            print(json.dumps(out, indent=2))
            return
        sys.exit(f"artifact {aid!r} not found in schema {name!r}")

    elif cmd == "start":
        name = _need(2, "schema-name")
        force = "--force" in sys.argv[3:]
        sys.exit(cmd_start(name, force=force))

    elif cmd == "current":
        emit_json = "--json" in sys.argv[2:]
        sys.exit(cmd_current(emit_json=emit_json))

    elif cmd == "advance":
        sys.exit(cmd_advance())

    elif cmd == "state":
        emit_json = "--json" in sys.argv[2:]
        sys.exit(cmd_state(emit_json=emit_json))

    elif cmd == "state-reset":
        yes = "--yes" in sys.argv[2:]
        sys.exit(cmd_state_reset(yes=yes))

    elif cmd in ("-h", "--help"):
        print(__doc__)

    else:
        sys.exit(
            f"unknown subcommand: {cmd}\n"
            "try: list | show <name> | validate <name> | stages <name> | "
            "artifact <name> <id> | branches <name> <id> | "
            "start <name> [--force] | current [--json] | advance | "
            "state [--json] | state-reset [--yes]"
        )


if __name__ == "__main__":
    main()
