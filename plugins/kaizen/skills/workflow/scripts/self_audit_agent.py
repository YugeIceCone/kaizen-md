"""kaizen self_audit_agent — the agent-driven follow-up to the
mechanical self-audit.

The mechanical audit (self_audit.py) emits skill-checkpoint Findings:
"load Skill X, apply it to targets Y". A script can't apply a skill —
skill bodies are LLM judgment. agent-self-audit closes that loop in
three phases:

  A. dispatch-plan  — THIS script. Run the mechanical audit, take its
     checkpoint Findings, render one self-contained subagent brief per
     checkpoint. Write a dispatch.json manifest.
  B. fan-out        — the ORCHESTRATING AGENT (not this script). Reads
     the manifest, dispatches one subagent per brief via the Agent
     tool. Each loads its Skill, applies it read-only, writes a result
     JSON. Driven by commands/agent-self-audit.md.
  C. aggregate      — THIS script. Read + jsonschema-validate every
     subagent result JSON, merge into a unified Finding list, write a
     consolidated <utc>-agent-self.md report.

Python owns A + C (mechanical, reproducible). The agent owns B — it
cannot be scripted, the Agent tool is agent-runtime-only.

## Pipeline shapes (Node+Flow)

dispatch-plan::

    LoadInputsNode   → run mechanical audit + load dispatch config + schema
        ↓
    BuildBriefsNode  → render one self-contained subagent brief per checkpoint
        ↓
    WriteManifestNode → write dispatch.json into .kaizen/audits/agent/<run-id>/

aggregate::

    LoadManifestNode        → read dispatch.json for the run
        ↓
    CollectResultsNode      → parallel-read each subagent result file
        ↓
    ValidateAndMergeNode    → jsonschema-validate + flatten into Findings
        ↓
    WriteConsolidatedReportNode → write <utc>-agent-self.md

## CLI

::

   kaizen-self-audit-agent dispatch-plan [--json]
       Run the mechanical audit, render subagent briefs, write the
       dispatch manifest. Prints run-id + manifest path + brief count.
   kaizen-self-audit-agent aggregate [--run-id ID] [--json]
       Merge a run's subagent results into a consolidated report.
       Defaults to the most recent run.
   kaizen-self-audit-agent path
       Print the agent-audit dir + dispatch config path.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import _self_audit as _core  # noqa: E402
import _envelope  # noqa: E402
import flow as _flow  # noqa: E402
import self_audit as _audit  # noqa: E402
from _self_audit import Finding  # noqa: E402

_emit = _envelope.emitter("kaizen-self-audit-agent", tool_version="1.0.0")

_RESULT_SCHEMA_PATH = (
    _core.DOMAIN_DIR / "schemas" / "checkpoint-result.schema.json"
)


# ─── Pure helpers ────────────────────────────────────────────────────


def _run_id_now() -> str:
    """UTC timestamp usable as a directory name. Sorts lexically =
    chronologically, so _latest_run_id() is a plain max()."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _latest_run_id() -> Optional[str]:
    root = _core.agent_audit_dir()
    if not root.is_dir():
        return None
    runs = sorted(p.name for p in root.iterdir() if p.is_dir())
    return runs[-1] if runs else None


def _substitute(template: str, mapping: dict) -> str:
    """Plain-string placeholder substitution. NOT str.format — the
    template and the injected JSON schema both carry literal braces."""
    out = template
    for key, value in mapping.items():
        out = out.replace("{" + key + "}", value)
    return out


def build_briefs(
    checkpoints: list[dict],
    config: dict,
    schema_text: str,
    run_dir: Path,
) -> list[dict]:
    """Render one self-contained subagent brief per checkpoint Finding.

    Each brief is fully standalone — a subagent has none of the
    orchestrator's context, so the prompt carries the skill, the
    targets, the focus, the output path, and the result schema."""
    template = config.get("prompt_template", "")
    severity_hint = config.get("severity_hint", "")
    default_subagent = (config.get("dispatch") or {}).get(
        "subagent_type", "general-purpose"
    )
    briefs: list[dict] = []
    for cp in checkpoints:
        skill = cp.get("skill", "")
        targets = cp.get("files") or []
        rationale = cp.get("rationale") or cp.get("detail") or ""
        if severity_hint:
            rationale = f"{rationale}\n\n{severity_hint}".strip()
        targets_block = (
            "\n".join(f"     - `{t}`" for t in targets)
            if targets
            else "     (no targets declared — audit the plugin broadly)"
        )
        result_path = run_dir / f"{cp['id']}.json"
        prompt = _substitute(template, {
            "skill": skill,
            "targets_block": targets_block,
            "rationale": rationale,
            "result_path": str(result_path),
            "result_schema": _prompt_schema(schema_text),
        })
        briefs.append({
            "checkpoint_id": cp["id"],
            "skill": skill,
            "targets": targets,
            "subagent_type": cp.get("subagent_type") or default_subagent,
            "result_path": str(result_path),
            "prompt": prompt,
        })
    return briefs


def _strip_meta_keys(d: dict) -> dict:
    """Drop JSON-Schema meta-keys ($schema, $id, …) from a dict. LLM
    subagents routinely echo these from the schema embedded in their
    brief into the result body; they carry no contract meaning, so
    strip rather than reject."""
    return {k: v for k, v in d.items() if not k.startswith("$")}


def _prompt_schema(schema_text: str) -> str:
    """The schema embedded in a subagent brief, minus its own meta-keys.
    `$schema` / `$id` / `title` / `description` are noise for "match
    this shape" — and worse, subagents copy them into their result,
    where additionalProperties:false then rejects an otherwise-valid
    result. Strip at the source so there's nothing to copy."""
    try:
        schema = json.loads(schema_text)
    except json.JSONDecodeError:
        return schema_text.strip()
    for meta in ("$schema", "$id", "title", "description"):
        schema.pop(meta, None)
    return json.dumps(schema, indent=2)


def _validate_result(raw: dict, schema: Optional[dict]) -> Optional[str]:
    """Return None when `raw` satisfies the checkpoint-result contract,
    else a short error string. Uses jsonschema when available; falls
    back to a structural check so aggregate still works without it.

    `$`-prefixed meta-keys are stripped before validating — see
    _strip_meta_keys for why."""
    raw = _strip_meta_keys(raw)
    if schema is not None:
        try:
            import jsonschema  # type: ignore
        except ImportError:
            jsonschema = None  # type: ignore
        if jsonschema is not None:
            try:
                jsonschema.validate(raw, schema)
                return None
            except jsonschema.ValidationError as e:  # type: ignore
                return f"schema: {e.message}"
    # Structural fallback — covers the no-jsonschema env.
    for key in ("checkpoint_id", "skill", "status", "findings"):
        if key not in raw:
            return f"missing required key: {key}"
    if raw["status"] not in ("clean", "findings", "error"):
        return f"bad status: {raw['status']!r}"
    if not isinstance(raw["findings"], list):
        return "findings is not a list"
    return None


def merge_results(briefs: list[dict], collected: list[dict]) -> dict:
    """Flatten subagent results into a unified Finding list + a
    per-checkpoint status summary.

    `collected` items: {brief, raw, read_error}. A missing file, a
    malformed result, or a status=error result each becomes a
    `medium` Finding rather than aborting the aggregate — a partial
    run is still worth reporting."""
    try:
        schema = json.loads(_RESULT_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        schema = None

    by_id = {c["brief"]["checkpoint_id"]: c for c in collected}
    findings: list[Finding] = []
    checkpoints: list[dict] = []

    for brief in briefs:
        cid = brief["checkpoint_id"]
        skill = brief.get("skill", "")
        item = by_id.get(cid)
        if item is None or item.get("read_error"):
            reason = (item or {}).get("read_error", "no result collected")
            findings.append(Finding(
                id=Finding.make_id(cid, "missing-result"),
                stage=cid, kind="checkpoint", severity="medium",
                title=f"checkpoint result missing: {skill}",
                detail=f"No usable result for {cid}: {reason}",
                skill=skill,
                remediation=f"Re-dispatch the {skill} subagent for "
                            f"checkpoint {cid}, then re-run aggregate.",
            ))
            checkpoints.append({"checkpoint_id": cid, "skill": skill,
                                "status": "missing", "finding_count": 0,
                                "summary": reason})
            continue

        raw = item["raw"]
        err = _validate_result(raw, schema)
        if err is not None:
            findings.append(Finding(
                id=Finding.make_id(cid, "malformed-result"),
                stage=cid, kind="checkpoint", severity="medium",
                title=f"checkpoint result malformed: {skill}",
                detail=f"Result for {cid} failed the contract — {err}",
                skill=skill,
                remediation=f"Re-dispatch the {skill} subagent; its "
                            "result must match checkpoint-result.schema.json.",
            ))
            checkpoints.append({"checkpoint_id": cid, "skill": skill,
                                "status": "malformed", "finding_count": 0,
                                "summary": err})
            continue

        status = raw["status"]
        summary = raw.get("summary", "")
        sub_findings = raw.get("findings", [])
        if status == "error":
            findings.append(Finding(
                id=Finding.make_id(cid, "subagent-error"),
                stage=cid, kind="checkpoint", severity="medium",
                title=f"checkpoint errored: {skill}",
                detail=summary or "subagent reported status=error",
                skill=skill,
                remediation=f"Inspect the {skill} subagent's summary; "
                            "re-dispatch once the blocker is cleared.",
            ))
        else:
            for fr in sub_findings:
                findings.append(Finding(
                    id=Finding.make_id(cid, fr.get("title", "")),
                    stage=cid, kind="checkpoint",
                    severity=fr.get("severity", "low"),
                    title=fr.get("title", "(untitled finding)"),
                    detail=fr.get("detail", ""),
                    files=fr.get("files", []),
                    skill=skill,
                    remediation=fr.get("remediation", ""),
                ))
        checkpoints.append({
            "checkpoint_id": cid, "skill": skill, "status": status,
            "finding_count": len(sub_findings), "summary": summary,
        })

    # De-dup by id, then severity-sort (highest first).
    seen: set[str] = set()
    unique: list[Finding] = []
    for f in findings:
        if f.id in seen:
            continue
        seen.add(f.id)
        unique.append(f)
    unique.sort(key=lambda f: (
        -_core.SEVERITY_ORDER.index(f.severity)
        if f.severity in _core.SEVERITY_ORDER else -99,
        f.stage,
    ))
    return {"findings": unique, "checkpoints": checkpoints}


# ─── dispatch-plan flow ──────────────────────────────────────────────


class LoadInputsNode(_flow.AsyncNode):
    """Run the mechanical audit + load the dispatch config + read the
    result schema. One responsibility: gather phase-A inputs."""

    async def exec_async(self, _prep) -> dict:
        # _run_audit_async is the async entry — calling run_audit()
        # here would nest asyncio.run() inside a running loop.
        audit = await _audit._run_audit_async(no_write=True)
        checkpoints = [
            f for f in audit.get("findings", [])
            if f.get("kind") == "checkpoint"
        ]
        config = _core.load_agent_dispatch()
        schema_text = _RESULT_SCHEMA_PATH.read_text(encoding="utf-8")
        return {"checkpoints": checkpoints, "config": config,
                "schema_text": schema_text}

    async def post_async(self, store: dict, _prep, exec_result: dict) -> str:
        store.update(exec_result)
        return "default"


class BuildBriefsNode(_flow.AsyncNode):
    async def prep_async(self, store: dict) -> dict:
        return {
            "checkpoints": store["checkpoints"],
            "config": store["config"],
            "schema_text": store["schema_text"],
            "run_dir": store["run_dir"],
        }

    async def exec_async(self, prep: dict) -> list[dict]:
        return build_briefs(
            prep["checkpoints"], prep["config"],
            prep["schema_text"], prep["run_dir"],
        )

    async def post_async(self, store: dict, _prep, briefs: list) -> str:
        store["briefs"] = briefs
        return "default"


class WriteManifestNode(_flow.AsyncNode):
    async def prep_async(self, store: dict) -> dict:
        return {
            "run_id": store["run_id"],
            "run_dir": store["run_dir"],
            "briefs": store["briefs"],
            "config": store["config"],
        }

    async def exec_async(self, prep: dict) -> dict:
        run_dir: Path = prep["run_dir"]
        run_dir.mkdir(parents=True, exist_ok=True)
        dispatch = (prep["config"].get("dispatch") or {})
        manifest = {
            "run_id": prep["run_id"],
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "subagent_type": dispatch.get("subagent_type", "general-purpose"),
            "max_parallel": dispatch.get("max_parallel", 5),
            "checkpoint_count": len(prep["briefs"]),
            "briefs": prep["briefs"],
        }
        manifest_path = run_dir / "dispatch.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")
        return {"manifest": manifest, "manifest_path": str(manifest_path)}

    async def post_async(self, store: dict, _prep, exec_result: dict) -> str:
        store["manifest"] = exec_result["manifest"]
        store["manifest_path"] = exec_result["manifest_path"]
        return "default"


def build_dispatch_flow() -> _flow.AsyncFlow:
    load = LoadInputsNode()
    briefs = BuildBriefsNode()
    write = WriteManifestNode()
    load >> briefs >> write
    return _flow.AsyncFlow(load)


def run_dispatch_plan() -> dict:
    return asyncio.run(_run_dispatch_plan_async())


async def _run_dispatch_plan_async() -> dict:
    run_id = _run_id_now()
    store: dict = {
        "run_id": run_id,
        "run_dir": _core.agent_audit_dir() / run_id,
    }
    await build_dispatch_flow().run_async(store)
    return {
        "run_id": run_id,
        "manifest_path": store.get("manifest_path"),
        "checkpoint_count": len(store.get("briefs", [])),
        "max_parallel": store.get("manifest", {}).get("max_parallel"),
        "subagent_type": store.get("manifest", {}).get("subagent_type"),
        "briefs": store.get("briefs", []),
    }


# ─── aggregate flow ──────────────────────────────────────────────────


class LoadManifestNode(_flow.AsyncNode):
    async def prep_async(self, store: dict) -> Path:
        return store["run_dir"]

    async def exec_async(self, run_dir: Path) -> dict:
        manifest_path = run_dir / "dispatch.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(
                f"no dispatch.json in {run_dir} — run dispatch-plan first"
            )
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    async def post_async(self, store: dict, _prep, manifest: dict) -> str:
        store["manifest"] = manifest
        return "default"


class CollectResultsNode(_flow.AsyncParallelBatchNode):
    """Read each subagent's result file. I/O-bound fan-out — a missing
    or unparseable file is captured, never raised (a partial run is
    still worth aggregating)."""

    async def prep_async(self, store: dict) -> list:
        return store["manifest"].get("briefs", [])

    async def exec_one_async(self, brief: dict) -> dict:
        path = Path(brief["result_path"])
        if not path.is_file():
            return {"brief": brief, "raw": None,
                    "read_error": "result file not written"}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return {"brief": brief, "raw": None,
                    "read_error": f"{type(e).__name__}: {e}"}
        return {"brief": brief, "raw": raw, "read_error": None}

    async def post_async(self, store: dict, _prep, collected: list) -> str:
        store["collected"] = collected
        return "default"


class ValidateAndMergeNode(_flow.AsyncNode):
    async def prep_async(self, store: dict) -> dict:
        return {
            "briefs": store["manifest"].get("briefs", []),
            "collected": store["collected"],
        }

    async def exec_async(self, prep: dict) -> dict:
        return merge_results(prep["briefs"], prep["collected"])

    async def post_async(self, store: dict, _prep, merged: dict) -> str:
        store["findings"] = merged["findings"]
        store["checkpoints"] = merged["checkpoints"]
        return "default"


class WriteConsolidatedReportNode(_flow.AsyncNode):
    async def prep_async(self, store: dict) -> dict:
        return {
            "run_id": store["manifest"].get("run_id", "?"),
            "run_dir": store["run_dir"],
            "findings": store.get("findings", []),
            "checkpoints": store.get("checkpoints", []),
        }

    async def exec_async(self, prep: dict) -> dict:
        ts = _run_id_now()
        report_path = prep["run_dir"] / f"{ts}-agent-self.md"
        md = self._render(prep)
        report_path.write_text(md, encoding="utf-8")
        return {"path": str(report_path), "markdown": md}

    @staticmethod
    def _render(prep: dict) -> str:
        findings: list[Finding] = prep["findings"]
        checkpoints: list[dict] = prep["checkpoints"]
        sev_counts: dict[str, int] = {}
        for f in findings:
            sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1
        status_counts: dict[str, int] = {}
        for c in checkpoints:
            status_counts[c["status"]] = status_counts.get(c["status"], 0) + 1
        lines = [
            f"# kaizen agent-self-audit — "
            f"{dt.datetime.now(dt.timezone.utc).isoformat()}",
            "",
            f"Run `{prep['run_id']}` — the agent-driven follow-up that "
            "actually applies the mechanical audit's skill checkpoints.",
            "",
            "## Executive summary",
            "",
            f"- **Checkpoints dispatched:** {len(checkpoints)}",
            *[f"  - {st}: {status_counts.get(st, 0)}"
              for st in ("clean", "findings", "error", "malformed", "missing")
              if status_counts.get(st)],
            f"- **Merged findings:** {len(findings)}",
            *[f"  - {sev}: {sev_counts.get(sev, 0)}"
              for sev in reversed(_core.SEVERITY_ORDER) if sev_counts.get(sev)],
            "",
            "## Checkpoint results",
            "",
        ]
        for c in checkpoints:
            line = (f"- `{c['skill']}` — **{c['status']}**"
                    f" ({c['finding_count']} finding(s))")
            if c.get("summary"):
                line += f" — {c['summary']}"
            lines.append(line)
        lines.append("")
        if findings:
            lines += ["## Merged findings", ""]
            for f in findings:
                lines += [
                    f"### `{f.severity}` · {f.title}",
                    f"- **skill:** `{f.skill}`  ·  **checkpoint:** `{f.stage}`",
                    *(f"- **files:** `{p}`" for p in f.files[:5]),
                    f"- **detail:** {f.detail}" if f.detail else "",
                    f"- **fix:** {f.remediation}" if f.remediation else "",
                    "",
                ]
            plan = [f for f in findings if f.severity != "info"]
            if plan:
                lines += ["## Remediation plan", ""]
                for i, f in enumerate(plan, 1):
                    lines.append(
                        f"{i}. **[{f.severity}]** ({f.skill}) {f.title}"
                        + (f" — {f.remediation}" if f.remediation else "")
                    )
                lines.append("")
        else:
            lines += [
                "## Merged findings", "",
                "No findings — every dispatched checkpoint came back clean.",
                "",
            ]
        return "\n".join(line for line in lines).rstrip() + "\n"

    async def post_async(self, store: dict, _prep, exec_result: dict) -> str:
        store["report"] = exec_result
        return "default"


def build_aggregate_flow() -> _flow.AsyncFlow:
    load = LoadManifestNode()
    collect = CollectResultsNode()
    merge = ValidateAndMergeNode()
    write = WriteConsolidatedReportNode()
    load >> collect >> merge >> write
    return _flow.AsyncFlow(load)


def run_aggregate(run_id: Optional[str] = None) -> dict:
    return asyncio.run(_run_aggregate_async(run_id))


async def _run_aggregate_async(run_id: Optional[str]) -> dict:
    run_id = run_id or _latest_run_id()
    if not run_id:
        return {"error": "no agent-self-audit runs found — "
                         "run dispatch-plan first"}
    run_dir = _core.agent_audit_dir() / run_id
    if not run_dir.is_dir():
        return {"error": f"run not found: {run_id}"}
    store: dict = {"run_dir": run_dir}
    await build_aggregate_flow().run_async(store)
    return {
        "run_id": run_id,
        "report_path": store.get("report", {}).get("path"),
        "markdown": store.get("report", {}).get("markdown"),
        "finding_count": len(store.get("findings", [])),
        "checkpoints": store.get("checkpoints", []),
        "findings": [f.to_dict() for f in store.get("findings", [])],
    }


# ─── CLI ─────────────────────────────────────────────────────────────


def _cmd_dispatch_plan(args) -> int:
    try:
        result = run_dispatch_plan()
    except RuntimeError as e:
        if getattr(args, "json", False):
            _emit({}, verdict="red", errors=[str(e)])
        else:
            print(json.dumps({"error": str(e)}))
        return 1
    if args.json:
        _emit(result,
              counts={"checkpoints": result.get("checkpoint_count", 0)})
        return 0
    print(f"\n[agent-self-audit] dispatch-plan — run {result['run_id']}")
    print(f"  checkpoints     : {result['checkpoint_count']}")
    print(f"  subagent type   : {result['subagent_type']}")
    print(f"  max parallel    : {result['max_parallel']}")
    print(f"  manifest        : {result['manifest_path']}")
    print("\n  Next: dispatch one subagent per brief (Agent tool), then")
    print("  `kaizen-self-audit-agent aggregate --run-id "
          f"{result['run_id']}`.")
    print("  See /kaizen:agent-self-audit for the full playbook.")
    return 0


def _cmd_aggregate(args) -> int:
    result = run_aggregate(run_id=args.run_id)
    if result.get("error"):
        if getattr(args, "json", False):
            _emit({}, verdict="red", errors=[result["error"]])
        else:
            print(json.dumps({"error": result["error"]}))
        return 1
    if args.json:
        out = {k: v for k, v in result.items() if k != "markdown"}
        _emit(out, counts={"findings": result.get("finding_count", 0)})
        return 0
    print(result.get("markdown") or "")
    if result.get("report_path"):
        print(f"\n→ report saved: {result['report_path']}")
    return 0


def _cmd_path(args) -> int:
    _emit({
        "agent_audit_dir": str(_core.agent_audit_dir()),
        "dispatch_config": str(_core.DOMAIN_DIR / "agent-dispatch.yaml"),
        "result_schema": str(_RESULT_SCHEMA_PATH),
        "latest_run": _latest_run_id(),
    })
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-self-audit-agent",
        description="Agent-driven follow-up to the mechanical self-audit: "
                    "dispatch a subagent per skill-checkpoint, then "
                    "aggregate the results.",
    )
    sub = p.add_subparsers(dest="cmd", required=False)

    sd = sub.add_parser(
        "dispatch-plan",
        help="(default) run the mechanical audit + render subagent briefs")
    sd.add_argument("--json", action="store_true",
                    help="machine-readable manifest (includes brief prompts)")
    sd.set_defaults(func=_cmd_dispatch_plan)

    sa = sub.add_parser("aggregate", help="merge a run's subagent results")
    sa.add_argument("--run-id", help="run id (default: most recent)")
    sa.add_argument("--json", action="store_true")
    sa.set_defaults(func=_cmd_aggregate)

    sp = sub.add_parser("path", help="agent-audit dir + config paths")
    sp.set_defaults(func=_cmd_path)

    args = p.parse_args(argv)
    if args.cmd is None:
        return _cmd_dispatch_plan(argparse.Namespace(json=False))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
