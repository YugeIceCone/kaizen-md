"""kaizen self_audit — Node+Flow pipeline that audits the plugin
itself against its own canonical shape + iron laws + adoption signals.

Drives a PocketFlow AsyncFlow from the schema declaration in
``skills/plugin-self-audit/domain/audit-pipeline.yaml``. Mechanical
stages run real checks; skill stages emit checkpoint Findings the
agent applies after the report.

## Pipeline shape

::

    LoadPipelineNode      → parse audit-pipeline.yaml
        ↓
    RunMechanicalStagesNode (parallel batch over each mechanical runner)
        ↓
    EmitSkillCheckpointsNode → one Finding per declared skill stage
        ↓
    AggregateFindingsNode → de-dup + sort by severity
        ↓
    BuildRemediationPlanNode → one task per actionable Finding
        ↓
    ProposeNewFunctionalityNode → emerging-pattern suggestions
        ↓
    WriteReportNode       → markdown to .kaizen/audits/<utc>-self.md

## CLI

::

   kaizen-self-audit run [--json] [--no-write]   # default
   kaizen-self-audit list-stages                  # show pipeline yaml
   kaizen-self-audit path                         # report dir
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import _self_audit as _core  # noqa: E402
import flow as _flow  # noqa: E402
from _self_audit import Finding  # noqa: E402
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-self-audit", tool_version="1.0.0")


# ─── Mechanical runners ──────────────────────────────────────────────


def run_validator(stage: dict) -> list[Finding]:
    """Invoke plugin-development/scripts/validate.py --all --json and
    convert the per-feature reports to Findings."""
    validator = (
        _core.PLUGIN_ROOT / "skills" / "plugin-development" / "scripts" / "validate.py"
    )
    if not validator.is_file():
        return [Finding(
            id=Finding.make_id(stage["id"], "missing-validator"),
            stage=stage["id"], kind="mechanical", severity="medium",
            title="plugin-development validator missing",
            detail=f"Expected at {validator}",
            remediation="Restore validate.py from git history.",
        )]
    try:
        result = subprocess.run(
            ["python3", str(validator), "--all", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        raw = json.loads(result.stdout) if result.stdout else []
        # Phase D2: validate.py wraps its list in canonical envelope.
        # Tolerate both shapes (envelope-wrapped or bare list) so the
        # audit stays compatible with older validator output too.
        if isinstance(raw, dict) and "data" in raw:
            data = raw["data"]
        else:
            data = raw
    except (subprocess.SubprocessError, json.JSONDecodeError) as e:
        return [Finding(
            id=Finding.make_id(stage["id"], "validator-failed"),
            stage=stage["id"], kind="mechanical", severity="medium",
            title="plugin-development validator failed",
            detail=f"{type(e).__name__}: {e}",
            remediation="Run validator manually + check exit code.",
        )]
    findings: list[Finding] = []
    for entry in data:
        for f in entry.get("findings", []):
            sev = "high" if f.get("severity") == "hard" else "low"
            findings.append(Finding(
                id=Finding.make_id(
                    stage["id"],
                    f"{entry['feature']}-{f.get('kind')}-{f.get('message','')[:30]}",
                ),
                stage=stage["id"], kind="mechanical", severity=sev,
                title=f"{entry['feature']}: {f.get('message','')}",
                detail=f.get("detail", ""),
                files=[entry.get("feature", "")],
                remediation=(
                    "Add the missing slot per skills/plugin-development/"
                    "domain/feature-shape.yaml."
                ),
            ))
    return findings


def run_metrics_coverage(stage: dict) -> list[Finding]:
    """Run kaizen-metrics never-used --kind {skill,mcp,bin,tool} and
    flag categories with high never-used ratios.

    Recency-guarded: a high never-used ratio on a YOUNG trace is a
    measurement artifact (the universal trace hook is recent), not
    a real adoption gap. We compute trace_age_days per kind and only
    escalate to medium/high when the trace has watched that kind for
    >= `adoption_min_trace_days` (default 14). Below that the finding
    is `info` — surfaced, not alarming. Mirrors the graveyard
    recency guard."""
    findings: list[Finding] = []
    metrics_py = _core.SCRIPT_DIR / "metrics.py"
    if not metrics_py.is_file():
        return findings
    threshold = (stage.get("threshold") or {})
    warn_pct = threshold.get("adoption_warn_pct", 10)
    systemic = threshold.get("systemic_threshold", 30)
    min_trace_days = threshold.get("adoption_min_trace_days", 14)
    # Import the core directly for trace_age_days (cheap; no subprocess).
    import _metrics as _m  # noqa: E402  — local import keeps the runner self-contained
    for kind in ("skill", "mcp", "bin", "tool"):
        try:
            result = subprocess.run(
                ["python3", str(metrics_py), "never-used",
                 "--kind", kind, "--json"],
                capture_output=True, text=True, timeout=10,
            )
            data = json.loads(result.stdout) if result.stdout else {}
        except (subprocess.SubprocessError, json.JSONDecodeError):
            continue
        available = data.get("available_count") or data.get("expected_count") or 0
        used = data.get("used_count", 0)
        never = data.get("never_used", [])
        if available == 0:
            continue
        adoption = (used / available) * 100
        age = _m.trace_age_days(kind)  # None when no events of this kind
        trace_old_enough = age is not None and age >= min_trace_days
        if not trace_old_enough:
            # Young trace → informational only. State the age so the
            # reader knows WHY it's not escalated.
            sev = "info"
            age_note = (
                f"trace too young to judge ({age:.1f}d watched"
                f" < {min_trace_days}d threshold)" if age is not None
                else "trace has captured zero events of this kind yet"
            )
        else:
            sev = "low"
            if len(never) >= systemic:
                sev = "medium"
            if adoption < warn_pct:
                sev = "medium" if sev == "low" else sev
            age_note = f"trace watched {age:.1f}d — judgment valid"
        findings.append(Finding(
            id=Finding.make_id(stage["id"], f"never-used-{kind}"),
            stage=stage["id"], kind="mechanical", severity=sev,
            title=f"{kind}: {len(never)}/{available} never invoked "
                  f"({adoption:.0f}% adoption)",
            detail=f"{age_note}\n"
                   + "\n".join(f"  - {n}" for n in never[:30])
                   + ("\n  ..." if len(never) > 30 else ""),
            remediation=(
                f"Review the {len(never)} never-used {kind}(s); "
                "retire what's dead, document what's load-bearing-but-rare, "
                "or use `kaizen-metrics top --kind " + kind + "` to see "
                "what IS hot."
            ) if trace_old_enough else (
                f"No action yet — let the trace mature past "
                f"{min_trace_days}d, then re-audit. Use `kaizen-metrics "
                f"graveyard --kind {kind}` for the recency-guarded view."
            ),
        ))
    return findings


def run_metrics_skips(stage: dict) -> list[Finding]:
    metrics_py = _core.SCRIPT_DIR / "metrics.py"
    if not metrics_py.is_file():
        return []
    try:
        result = subprocess.run(
            ["python3", str(metrics_py), "skips", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(result.stdout) if result.stdout else {}
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return []
    skips = data.get("skips", [])
    if not skips:
        return [Finding(
            id=Finding.make_id(stage["id"], "no-skips"),
            stage=stage["id"], kind="mechanical", severity="info",
            title="No skill-skips detected for the latest session",
        )]
    out = []
    for s in skips:
        out.append(Finding(
            id=Finding.make_id(stage["id"], s["skill"]),
            stage=stage["id"], kind="mechanical", severity="medium",
            title=f"skill-skip: {s['skill']} not loaded despite triggers",
            detail=f"Reason: {s.get('rationale','')}\n"
                   f"Touched: {s.get('touched_count','?')} file(s)\n"
                   + "\n".join(f"  - {p}" for p in s.get("touched_files", [])[:5]),
            skill=s["skill"],
            remediation=f"Load Skill({s['skill']}) before next "
                        "session edit on these files.",
        ))
    return out


def run_hook_trace_check(stage: dict) -> list[Finding]:
    out: list[Finding] = []
    for h in _core.list_hook_scripts():
        if h.name == "_trace.sh":
            continue  # the helper itself
        if not _core.hook_fires_trace(h):
            out.append(Finding(
                id=Finding.make_id(stage["id"], h.name),
                stage=stage["id"], kind="mechanical", severity="low",
                title=f"hook missing trace call: {h.name}",
                detail="Hook does not fire `_trace.sh` or `trace.py event`.",
                files=[str(h.relative_to(_core.REPO_ROOT))],
                remediation=f"Add `bash $PLUGIN_ROOT/hooks/claude/_trace.sh <event>` "
                            f"early in {h.name}.",
            ))
    return out


def run_bin_permission_check(stage: dict) -> list[Finding]:
    out: list[Finding] = []
    manifest_text = _core.read_plugin_manifest_text()
    for b in _core.list_bin_wrappers():
        # Find the script the bin wrapper execs
        try:
            text = b.read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(r'exec\s+python3\s+["$]\S+/([a-zA-Z_]+\.py)', text)
        if not m:
            continue
        script = m.group(1)
        if script in manifest_text:
            continue
        if "skills/workflow/scripts/*.py" in manifest_text:
            continue  # wildcard catches it
        out.append(Finding(
            id=Finding.make_id(stage["id"], b.name),
            stage=stage["id"], kind="mechanical", severity="medium",
            title=f"bin wrapper missing plugin.json permission: {b.name}",
            detail=f"Script {script} not in permissions.allow.",
            files=[str(b.relative_to(_core.REPO_ROOT))],
            remediation=f"Add `Bash(python3 ${{CLAUDE_PLUGIN_ROOT}}/skills/workflow/scripts/{script}:*)` "
                        "to plugin.json::permissions.allow.",
        ))
    return out


def run_vendored_check(stage: dict) -> list[Finding]:
    """Detect any uncommitted modifications to vendored skill bodies."""
    try:
        result = subprocess.run(
            ["git", "-C", str(_core.REPO_ROOT), "diff", "--name-only"],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.SubprocessError:
        return []
    modified = result.stdout.splitlines()
    out: list[Finding] = []
    for path in modified:
        # plugins/kaizen/skills/<vendored>/SKILL.md
        m = re.match(r"plugins/kaizen/skills/([^/]+)/", path)
        if m and m.group(1) in _core.VENDORED_SKILLS:
            out.append(Finding(
                id=Finding.make_id(stage["id"], path),
                stage=stage["id"], kind="mechanical", severity="high",
                title=f"vendored skill modified: {m.group(1)}",
                detail="Patch upstream first, then refresh per CONTRIBUTING.md.",
                files=[path],
                remediation=f"Revert {path}; submit upstream patch; refresh via bundle-refresh procedure.",
            ))
    return out


def run_claude_md_check(stage: dict) -> list[Finding]:
    out: list[Finding] = []
    for rel in (stage.get("paths") or []):
        p = _core.REPO_ROOT / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        hits = _core.file_contains_volatile(text)
        if hits:
            out.append(Finding(
                id=Finding.make_id(stage["id"], rel),
                stage=stage["id"], kind="mechanical", severity="low",
                title=f"{rel}: possible volatile data ({len(hits)} hit(s))",
                detail="Hits: " + ", ".join(hits) + "\n"
                       "(May be false-positive — review manually.)",
                files=[rel],
                remediation="Move volatile data to CHANGELOG.md / progress.md / git log.",
            ))
    return out


# Map stage runner names → callables. Schema-driven dispatch.
RUNNERS = {
    "run_validator": run_validator,
    "run_metrics_coverage": run_metrics_coverage,
    "run_metrics_skips": run_metrics_skips,
    "run_hook_trace_check": run_hook_trace_check,
    "run_bin_permission_check": run_bin_permission_check,
    "run_vendored_check": run_vendored_check,
    "run_claude_md_check": run_claude_md_check,
}


# ─── Skill checkpoint emitter ────────────────────────────────────────


def emit_skill_checkpoint(stage: dict) -> Finding:
    return Finding(
        id=Finding.make_id(stage["id"], stage.get("skill", "")),
        stage=stage["id"], kind="checkpoint", severity="medium",
        title=f"agent-checkpoint: load Skill({stage.get('skill')})",
        detail=stage.get("description", ""),
        skill=stage.get("skill", ""),
        rationale=stage.get("rationale", "") or stage.get("focus", ""),
        files=stage.get("targets") or [],
        remediation=(
            f"After this report, load `Skill({stage.get('skill')})` and "
            f"apply it to: {', '.join(stage.get('targets') or [])}. "
            "Re-run self-audit after fixes to capture the diff."
        ),
    )


# ─── Flow nodes ──────────────────────────────────────────────────────


class LoadPipelineNode(_flow.AsyncNode):
    async def prep_async(self, store: dict) -> None:
        return None

    async def exec_async(self, _) -> dict:
        return _core.load_pipeline()

    async def post_async(self, store: dict, _prep, pipeline: dict) -> str:
        store["pipeline"] = pipeline
        return "default"


class RunMechanicalStagesNode(_flow.AsyncParallelBatchNode):
    """Run each mechanical stage's runner. Emits Findings per stage."""

    concurrency = 4

    async def prep_async(self, store: dict) -> list:
        stages = store["pipeline"].get("stages", [])
        return [s for s in stages if s.get("kind") == "mechanical"]

    async def exec_one_async(self, stage: dict) -> list[Finding]:
        runner_name = stage.get("runner", "")
        runner = RUNNERS.get(runner_name)
        if runner is None:
            return [Finding(
                id=Finding.make_id(stage["id"], "no-runner"),
                stage=stage["id"], kind="mechanical", severity="info",
                title=f"stage skipped: no runner '{runner_name}'",
            )]
        return await asyncio.to_thread(runner, stage)

    async def post_async(self, store: dict, _prep, batch: list) -> str:
        # Flatten list-of-lists
        store.setdefault("findings", [])
        for sublist in batch:
            store["findings"].extend(sublist)
        return "default"


class EmitSkillCheckpointsNode(_flow.AsyncNode):
    async def prep_async(self, store: dict) -> list:
        stages = store["pipeline"].get("stages", [])
        return [s for s in stages if s.get("kind") == "skill"]

    async def exec_async(self, stages: list) -> list[Finding]:
        return [emit_skill_checkpoint(s) for s in stages]

    async def post_async(self, store: dict, _prep, checkpoints: list) -> str:
        store.setdefault("findings", []).extend(checkpoints)
        return "default"


class AggregateFindingsNode(_flow.AsyncNode):
    async def prep_async(self, store: dict) -> list:
        return store.get("findings", [])

    async def exec_async(self, findings: list[Finding]) -> list[Finding]:
        # De-dup by id; preserve first occurrence
        seen: set[str] = set()
        unique = []
        for f in findings:
            if f.id in seen:
                continue
            seen.add(f.id)
            unique.append(f)
        # Sort by severity descending then stage
        unique.sort(
            key=lambda f: (-_core.SEVERITY_ORDER.index(f.severity) if f.severity in _core.SEVERITY_ORDER else -99, f.stage)
        )
        return unique

    async def post_async(self, store: dict, _prep, findings: list) -> str:
        store["findings"] = findings
        return "default"


class BuildRemediationPlanNode(_flow.AsyncNode):
    async def prep_async(self, store: dict) -> list:
        return store.get("findings", [])

    async def exec_async(self, findings: list[Finding]) -> list[dict]:
        plan: list[dict] = []
        for f in findings:
            if f.severity == "info":
                continue
            if not f.remediation:
                continue
            plan.append({
                "severity": f.severity,
                "stage": f.stage,
                "title": f.title,
                "task": f.remediation,
                "files": f.files,
            })
        return plan

    async def post_async(self, store: dict, _prep, plan: list) -> str:
        store["remediation_plan"] = plan
        return "default"


class ProposeNewFunctionalityNode(_flow.AsyncNode):
    """Heuristic: surface emerging-pattern proposals from the findings.

    This is intentionally rule-based (not LLM) so the audit is
    reproducible. Each rule converts a finding-pattern into a
    new-functionality suggestion."""

    async def prep_async(self, store: dict) -> list:
        return store.get("findings", [])

    async def exec_async(self, findings: list[Finding]) -> list[dict]:
        proposals: list[dict] = []
        # Rule 1: many never-used skills → propose a "skill graveyard"
        # auto-archiver
        for f in findings:
            if f.stage == "metrics-coverage" and "skill" in f.title and "never invoked" in f.title:
                proposals.append({
                    "title": "Auto-archive cold skills",
                    "rationale": "Many plugin-original skills never invoked. Either dead, or not surfaced. Propose: kaizen-metrics graveyard subcommand that, given a stale-threshold, lists candidates + offers archive (move skill to skills/_archive/, drop from plugin.json).",
                    "size": "medium",
                    "from_finding": f.id,
                })
                break
        # Rule 2: missing bin permissions → propose a CI check
        if any(f.stage == "bin-permission-coverage" for f in findings):
            proposals.append({
                "title": "Pre-commit gate: bin/permission diff check",
                "rationale": "Bin wrappers without plugin.json permission entries cause user-prompts. Add a gate check that, on commit touching bin/ OR plugin.json, validates all bin/kaizen-* have a matching script entry.",
                "size": "small",
            })
        # Rule 3: hooks not tracing → propose extending iron-laws
        if any(f.stage == "hook-trace-coverage" for f in findings):
            proposals.append({
                "title": "Iron law: every-hook-script-traces-its-firing",
                "rationale": "Hook scripts that don't fire _trace.sh leave lifecycle gaps. Add iron-laws.yaml entry; validator gates new hooks at commit time.",
                "size": "small",
            })
        # Rule 4: skill-checkpoint findings → propose an LLM-driven follow-up audit
        if any(f.kind == "checkpoint" for f in findings):
            proposals.append({
                "title": "Agent-driven follow-up audit (LLM stage)",
                "rationale": "Self-audit emits skill-checkpoint TODOs. Wrap them in an `agent-self-audit` flow that, given the report, dispatches subagents (Skill + apply) and aggregates results.",
                "size": "large",
            })
        # Rule 5: never-used MCP tools → propose adoption smoke-tests
        for f in findings:
            if f.stage == "metrics-coverage" and "mcp" in f.title and "never invoked" in f.title:
                proposals.append({
                    "title": "MCP smoke-test command (`kaizen-metrics smoke --kind mcp`)",
                    "rationale": "0 MCP invocations means we can't validate the servers actually work. Add a smoke-test command that calls each registered MCP tool with a noop payload + reports pass/fail.",
                    "size": "medium",
                    "from_finding": f.id,
                })
                break
        return proposals

    async def post_async(self, store: dict, _prep, proposals: list) -> str:
        store["new_functionality"] = proposals
        return "default"


class WriteReportNode(_flow.AsyncNode):
    async def prep_async(self, store: dict) -> dict:
        return {
            "findings": store.get("findings", []),
            "plan": store.get("remediation_plan", []),
            "proposals": store.get("new_functionality", []),
            "no_write": store.get("no_write", False),
        }

    async def exec_async(self, prep: dict) -> dict:
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        report_dir = _core.REPO_ROOT / ".kaizen" / "audits"
        report_path = report_dir / f"{ts}-self.md"
        md = self._render_markdown(prep)
        if not prep.get("no_write"):
            report_dir.mkdir(parents=True, exist_ok=True)
            report_path.write_text(md, encoding="utf-8")
        return {"path": str(report_path), "markdown": md}

    @staticmethod
    def _render_markdown(prep: dict) -> str:
        findings: list[Finding] = prep["findings"]
        plan: list[dict] = prep["plan"]
        proposals: list[dict] = prep["proposals"]
        # Counts by severity
        sev_counts: dict[str, int] = {}
        for f in findings:
            sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1
        lines = [
            f"# kaizen self-audit — {dt.datetime.now(dt.timezone.utc).isoformat()}",
            "",
            "## Executive summary",
            "",
            f"- **Total findings:** {len(findings)}",
            *[f"  - {sev}: {sev_counts.get(sev, 0)}" for sev in reversed(_core.SEVERITY_ORDER)],
            f"- **Mechanical:** {sum(1 for f in findings if f.kind == 'mechanical')}",
            f"- **Skill checkpoints:** {sum(1 for f in findings if f.kind == 'checkpoint')}",
            f"- **Remediation tasks:** {len(plan)}",
            f"- **New-functionality proposals:** {len(proposals)}",
            "",
        ]
        # Mechanical findings
        mech = [f for f in findings if f.kind == "mechanical" and f.severity != "info"]
        info = [f for f in findings if f.kind == "mechanical" and f.severity == "info"]
        if mech:
            lines += ["## Mechanical findings", ""]
            for f in mech:
                lines += [
                    f"### `{f.severity}` · {f.title}",
                    f"- **stage:** `{f.stage}`",
                    *(f"- **files:** `{p}`" for p in f.files[:5]),
                    f"- **detail:** {f.detail}" if f.detail else "",
                    f"- **fix:** {f.remediation}" if f.remediation else "",
                    "",
                ]
        if info:
            lines += ["## Informational mechanical findings", ""]
            for f in info:
                lines.append(f"- `{f.stage}` — {f.title}")
            lines.append("")
        # Skill checkpoints
        cps = [f for f in findings if f.kind == "checkpoint"]
        if cps:
            lines += [
                "## Skill checkpoints (agent action required)",
                "",
                "Each row is a TODO for the agent: load the skill, apply it to the targets, "
                "re-run self-audit to compare findings. The audit doesn't run these for you "
                "— skill bodies are LLM-applied not script-executable.",
                "",
            ]
            for f in cps:
                lines += [
                    f"### `Skill({f.skill})` against `{', '.join(f.files)}`",
                    f"- **stage:** `{f.stage}`",
                    f"- **why:** {f.rationale or f.detail}",
                    f"- **action:** {f.remediation}",
                    "",
                ]
        # Remediation plan
        if plan:
            lines += ["## Remediation plan (concrete tasks)", ""]
            for i, task in enumerate(plan, 1):
                lines.append(f"{i}. **[{task['severity']}]** ({task['stage']}) {task['task']}")
            lines.append("")
        # New functionality
        if proposals:
            lines += ["## New-functionality suggestions", ""]
            for p in proposals:
                lines += [
                    f"### {p['title']}",
                    f"- **size:** {p.get('size', 'unknown')}",
                    f"- **rationale:** {p['rationale']}",
                    "",
                ]
        return "\n".join(lines).rstrip() + "\n"

    async def post_async(self, store: dict, _prep, exec_result: dict) -> str:
        store["report"] = exec_result
        return "default"


def build_flow() -> _flow.AsyncFlow:
    load = LoadPipelineNode()
    mech = RunMechanicalStagesNode()
    cp = EmitSkillCheckpointsNode()
    agg = AggregateFindingsNode()
    plan = BuildRemediationPlanNode()
    new = ProposeNewFunctionalityNode()
    rep = WriteReportNode()
    load >> mech >> cp >> agg >> plan >> new >> rep
    return _flow.AsyncFlow(load)


def run_audit(*, no_write: bool = False) -> dict:
    return asyncio.run(_run_audit_async(no_write=no_write))


async def _run_audit_async(*, no_write: bool = False) -> dict:
    store: dict = {"no_write": no_write}
    await build_flow().run_async(store)
    return {
        "report_path": store.get("report", {}).get("path"),
        "markdown": store.get("report", {}).get("markdown"),
        "finding_count": len(store.get("findings", [])),
        "remediation_task_count": len(store.get("remediation_plan", [])),
        "new_functionality_count": len(store.get("new_functionality", [])),
        "findings": [f.to_dict() for f in store.get("findings", [])],
    }


# ─── CLI ─────────────────────────────────────────────────────────────


def _cmd_run(args) -> int:
    result = run_audit(no_write=args.no_write)
    if args.json:
        _emit({k: v for k, v in result.items() if k != "markdown"})
        return 0
    print(result.get("markdown") or "")
    if result.get("report_path"):
        print(f"\n→ report saved: {result['report_path']}")
    return 0


def _cmd_list_stages(args) -> int:
    pipeline = _core.load_pipeline()
    stages = pipeline.get("stages", [])
    _emit(stages, counts={"stages": len(stages)})
    return 0


def _cmd_path(args) -> int:
    _emit({
        "report_dir": str(_core.REPO_ROOT / ".kaizen" / "audits"),
        "pipeline": str(_core.DOMAIN_DIR / "audit-pipeline.yaml"),
    })
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-self-audit",
        description="Schema-driven plugin self-audit using Node+Flow + onion-ddd + coding-skills checkpoints.",
    )
    sub = p.add_subparsers(dest="cmd", required=False)
    sr = sub.add_parser("run", help="(default) run the audit pipeline")
    sr.add_argument("--json", action="store_true", help="machine-readable output")
    sr.add_argument("--no-write", action="store_true",
                    help="don't persist to .kaizen/audits/")
    sr.set_defaults(func=_cmd_run)
    sl = sub.add_parser("list-stages", help="show the pipeline yaml")
    sl.set_defaults(func=_cmd_list_stages)
    sp = sub.add_parser("path", help="report dir + pipeline path")
    sp.set_defaults(func=_cmd_path)

    args = p.parse_args(argv)
    if args.cmd is None:
        # Bare invocation — run the audit
        return _cmd_run(argparse.Namespace(json=False, no_write=False))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
