"""kaizen parallel-dispatch audit — pre-flight checks for parallel-branches plans.

Phase 5.B of the symbol-search arc. Bridges the kaizen-md side of the
parallel-branches kit: validates a plan.yaml + its chunks before
dispatch so silent install failures surface upfront.

Scope: structural validation only. Runtime concerns (worktree
orchestration / merge-handler readiness / live MCP wiring) belong in
clever-lama-mcp (per the kit's scope split).

## Public surface

  audit(plan_path: Path) -> list[dict]
    Returns ``[{severity, rule_id, message}]``. Empty = ready to dispatch.
    severity ∈ {error, warn, info}.

  main(argv) -> int
    CLI. Default = pretty-print findings; --json = envelope.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ─── Audit checks (each returns 0..N findings) ──────────────────────

def _check_plan_file_exists(plan_path: Path) -> list[dict]:
    if not plan_path.is_file():
        return [{
            "severity": "error", "rule_id": "plan-missing",
            "message": f"plan file not found: {plan_path}",
        }]
    return []

def _parse_yaml_or_error(plan_path: Path) -> tuple[dict | None, list[dict]]:
    try:
        import yaml
    except ImportError:
        return None, [{
            "severity": "error", "rule_id": "pyyaml-missing",
            "message": "PyYAML required for plan audit (pip install pyyaml)",
        }]
    try:
        raw = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return None, [{
            "severity": "error", "rule_id": "yaml-parse-error",
            "message": f"plan YAML parse failed: {e}",
        }]
    if not isinstance(raw, dict):
        return None, [{
            "severity": "error", "rule_id": "plan-not-mapping",
            "message": "plan must be a mapping at top level",
        }]
    return raw, []

def _check_required_keys(plan: dict) -> list[dict]:
    out = []
    for key in ("chunks",):
        if key not in plan:
            out.append({
                "severity": "error", "rule_id": "missing-required-key",
                "message": f"required key missing: {key!r}",
            })
    return out

def _resolve_chunks(plan: dict, plan_path: Path) -> tuple[list[dict], list[dict]]:
    """Resolve chunks (inline list OR ``./chunks/*.yaml`` glob). Returns
    (chunks_list, findings)."""
    chunks = plan.get("chunks", [])
    if isinstance(chunks, list):
        return chunks, []
    if not isinstance(chunks, str):
        return [], [{
            "severity": "error", "rule_id": "chunks-bad-type",
            "message": f"chunks must be list or glob string, got {type(chunks).__name__}",
        }]
    # Glob form: load each file
    try:
        import yaml
    except ImportError:
        return [], [{
            "severity": "error", "rule_id": "pyyaml-missing",
            "message": "PyYAML required to resolve chunks glob",
        }]
    base = plan_path.parent
    glob = chunks.removeprefix("./")
    out = []
    matches = sorted(base.glob(glob))
    if not matches:
        return [], [{
            "severity": "warn", "rule_id": "chunks-glob-empty",
            "message": f"glob {chunks!r} matched zero files",
        }]
    for p in matches:
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("_source_path", str(p))
                out.append(data)
        except yaml.YAMLError as e:
            return out, [{
                "severity": "error", "rule_id": "chunk-yaml-parse-error",
                "message": f"{p}: {e}",
            }]
    return out, []

def _check_chunk_id_uniqueness(chunks: list[dict]) -> list[dict]:
    seen: dict[str, int] = {}
    out = []
    for c in chunks:
        cid = c.get("id")
        if cid is None:
            out.append({
                "severity": "error", "rule_id": "chunk-missing-id",
                "message": f"chunk {c.get('_source_path', '?')} has no `id`",
            })
            continue
        if cid in seen:
            out.append({
                "severity": "error", "rule_id": "chunk-id-duplicate",
                "message": f"chunk id {cid!r} duplicated "
                           f"(at {c.get('_source_path', '?')})",
            })
        seen[cid] = seen.get(cid, 0) + 1
    return out

def _check_chunk_perms_collide(chunks: list[dict]) -> list[dict]:
    """Two chunks claiming exclusive write on the same path is a
    silent-collision blocker."""
    owners: dict[str, str] = {}
    out = []
    for c in chunks:
        cid = c.get("id", "?")
        for perm in (c.get("perms") or []):
            if not isinstance(perm, dict):
                continue
            if perm.get("mode") != "exclusive":
                continue
            path = perm.get("path")
            if not path:
                continue
            if path in owners and owners[path] != cid:
                out.append({
                    "severity": "error", "rule_id": "perm-collision",
                    "message": (f"exclusive perm on {path!r} claimed by "
                                f"both {owners[path]!r} and {cid!r}"),
                })
            else:
                owners[path] = cid
    return out

# ─── Composition ─────────────────────────────────────────────────────

def audit(plan_path: Path) -> list[dict]:
    """Run all checks; return aggregated findings (empty = ready)."""
    plan_path = Path(plan_path)
    findings: list[dict] = []
    f = _check_plan_file_exists(plan_path)
    if f:
        return f
    plan, f = _parse_yaml_or_error(plan_path)
    findings.extend(f)
    if plan is None:
        return findings
    findings.extend(_check_required_keys(plan))
    if "chunks" not in plan:
        return findings
    chunks, f = _resolve_chunks(plan, plan_path)
    findings.extend(f)
    findings.extend(_check_chunk_id_uniqueness(chunks))
    findings.extend(_check_chunk_perms_collide(chunks))
    return findings

# ─── CLI ────────────────────────────────────────────────────────────

def _render_findings(findings: list[dict]) -> str:
    if not findings:
        return "kaizen-parallel-dispatch-audit: ✓ ready to dispatch (0 findings)"
    lines = [f"kaizen-parallel-dispatch-audit: {len(findings)} finding(s)"]
    for f in findings:
        sev = f.get("severity", "?").upper()
        rid = f.get("rule_id", "?")
        msg = f.get("message", "")
        lines.append(f"  [{sev}] {rid}: {msg}")
    return "\n".join(lines)

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-parallel-dispatch-audit",
        description="Pre-flight audit for parallel-branches plan.yaml + chunks.",
    )
    p.add_argument("plan", help="path to plan.yaml")
    p.add_argument("--json", action="store_true", help="envelope output")
    args = p.parse_args(argv)
    findings = audit(Path(args.plan))
    if args.json:
        errors = sum(1 for f in findings if f.get("severity") == "error")
        print(json.dumps({"data": {
            "findings": findings,
            "count": len(findings),
            "errors": errors,
            "ready": errors == 0,
        }}))
    else:
        print(_render_findings(findings))
    return 1 if any(f.get("severity") == "error" for f in findings) else 0

if __name__ == "__main__":
    sys.exit(main())
