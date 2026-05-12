#!/usr/bin/env python3
"""Kaizen workflow — codegen for human-readable references.

Reads skills/workflow/domain/{routines.yaml, git-discipline.yaml} and
regenerates skills/workflow/references/{routines.md, git-discipline.md}
so the yaml stays the single source of truth.

## CLI

    python3 codegen.py              # regenerate both references
    python3 codegen.py --check      # exit non-zero if regenerated content differs
                                     # from disk (use in CI)

## Idempotency

Running twice in a row produces byte-identical output. This is enforced
by the test suite (_tests.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _loader import load_routines, load_git_discipline  # noqa: E402

REFS_DIR = Path(__file__).resolve().parent.parent / "references"
GENERATED_HEADER = """<!-- DO NOT HAND-EDIT.

Generated from skills/workflow/domain/{source}.yaml by
skills/workflow/application/codegen.py.

To change content, edit the yaml and run:
    python3 skills/workflow/application/codegen.py
or rely on refresh-cache.sh which invokes codegen before sync.
-->

"""


def _render_routines() -> str:
    routines = load_routines()
    out = [GENERATED_HEADER.format(source="routines"), "# Workflow Routines\n\n"]
    out.append(
        "Routines are stage chains the kaizen workflow runs. Each stage maps to "
        "a skill via the stage-skill table in references/orchestration.md. "
        "Hardcoded routines are verb-detected from the user's prompt; "
        "schema routines opt in via `schema=<name>` on `/workflow init`.\n\n"
    )

    out.append("## Quick reference\n\n")
    out.append("| Routine | Kind | Trigger words | Stages |\n")
    out.append("|---|---|---|---|\n")
    for name, r in routines.items():
        trig = ", ".join(f"`{w}`" for w in (r.get("trigger_words") or [])) or "—"
        stages = " → ".join(r.get("stages") or []) or "—"
        out.append(f"| `{name}` | {r.get('kind')} | {trig} | {stages} |\n")
    out.append("\n")

    out.append("## Routines\n\n")
    for name, r in routines.items():
        out.append(f"### `{name}` ({r.get('kind')})\n\n")
        out.append(f"{(r.get('description') or '').rstrip()}\n\n")
        if r.get("trigger_words"):
            out.append(f"**Triggers:** {', '.join(repr(w) for w in r['trigger_words'])}\n\n")
        if r.get("schema_path"):
            out.append(f"**Schema:** `{r['schema_path']}`\n\n")
        stages = r.get("stages") or []
        if stages:
            out.append(f"**Stages:** {' → '.join(f'`{s}`' for s in stages)}\n\n")
        else:
            out.append("**Stages:** (none — user-pinned via `skill=NAME`)\n\n")
        out.append(f"**End state:** {r.get('end_state', '—')}\n\n")
        cs = r.get("coding_skills") or []
        if cs:
            out.append(f"**Coding skills cross-link:** {', '.join(f'`kaizen:{s}`' for s in cs)}\n\n")
    return "".join(out)


def _render_git_discipline() -> str:
    g = load_git_discipline()
    out = [GENERATED_HEADER.format(source="git-discipline"), "# Git Workflow Discipline\n\n"]
    out.append(
        "Project-agnostic discipline for committing code via the kaizen plugin. "
        "Rules in this file are derived from the canonical "
        "`domain/git-discipline.yaml`. The pre-commit hook + commit-msg hook + "
        "backlog.py read the yaml directly; this markdown is for humans + agents.\n\n"
    )

    cf = g.get("commit_format", {})
    out.append("## Commit format\n\n")
    out.append(f"- **Style:** {cf.get('style', 'conventional')}\n")
    out.append(f"- **Subject max chars:** {cf.get('subject_max_chars', 72)}\n")
    out.append(f"- **Body wrap chars:** {cf.get('body_wrap_chars', 76)}\n")
    out.append(f"- **Scope required:** {cf.get('scope_required', True)}\n")
    if cf.get("allowed_prefixes"):
        prefixes = ", ".join(f"`{p}`" for p in cf["allowed_prefixes"])
        out.append(f"- **Allowed prefixes:** {prefixes}\n")
    out.append("\n")

    sz = g.get("sizing_thresholds", {})
    out.append("## Sizing model (NEVER by clock-time)\n\n")
    out.append(
        "Size work by **trace + sem + grep** — count actual files touched, "
        "manifest edits, trait moves, cross-context hops. Never by hours.\n\n"
    )
    out.append("| Tier | Threshold | Destination |\n|---|---|---|\n")
    if sz.get("micro"):
        m = sz["micro"]
        out.append(
            f"| Micro | ≤{m.get('max_files', 3)} files, "
            f"0 manifest edits, 0 trait moves | "
            f"`{m.get('destination', 'backlog.json')}` |\n"
        )
    if sz.get("split_into_siblings"):
        s = sz["split_into_siblings"]
        out.append(
            f"| Split siblings | 4–{s.get('max_files', 15)} files OR "
            f"1 manifest OR 1 trait move | sibling micros |\n"
        )
    if sz.get("plan_file"):
        p = sz["plan_file"]
        out.append(
            f"| Plan file | ≥{p.get('min_files', 16)} files OR "
            f"≥{p.get('min_manifest_edits', 2)} manifests OR cross-context OR "
            f"carve-out trigger | `{p.get('destination', 'plans/<date>-<slug>.md')}` |\n"
        )
    out.append("\n")

    gates = g.get("pre_commit_gates", [])
    out.append(f"## Pre-commit gates ({len(gates)})\n\n")
    out.append("Each gate runs in order; cheaper gates first. Errors block; warnings notify.\n\n")
    for gate in gates:
        sev = gate.get("severity", "error")
        out.append(f"### `{gate['id']}` ({sev})\n\n")
        out.append(f"{gate.get('description', '')}\n\n")
        if gate.get("probe"):
            out.append(f"**Probe:** `{gate['probe']}`\n\n")
        if gate.get("bypass_env"):
            out.append(f"**Bypass:** `{gate['bypass_env']}=1`\n\n")

    pd = g.get("pre_deletion_belief", {})
    if pd.get("enabled"):
        out.append("## Pre-deletion belief\n\n")
        out.append(f"{(pd.get('description') or '').strip()}\n\n")
        if pd.get("bypass_env"):
            out.append(f"**Bypass (single commit):** `{pd['bypass_env']}=1 git commit ...`\n\n")

    pf = g.get("plan_files", {})
    if pf:
        out.append("## Plan files\n\n")
        out.append(f"- **Location:** `{pf.get('location', 'plans/')}`\n")
        out.append(f"- **Archive:** `{pf.get('archive_location')}`\n")
        if pf.get("triggers_for_new_plan"):
            out.append(f"- **Triggers:** {', '.join(pf['triggers_for_new_plan'])}\n")
        if pf.get("status_values"):
            out.append(f"- **Status values:** {', '.join(pf['status_values'])}\n")
        out.append("\n")

    rp = g.get("recovery_patterns", {})
    if rp:
        out.append("## Recovery patterns\n\n")
        for k, v in rp.items():
            out.append(f"- **{k.replace('_', ' ')}:** `{v}`\n")
        out.append("\n")

    fb = g.get("forbidden_without_explicit_permission") or []
    if fb:
        out.append("## Forbidden without explicit user permission\n\n")
        for item in fb:
            out.append(f"- `{item}`\n")
        out.append("\n")

    bid = g.get("bash_invocation_discipline") or {}
    rules = bid.get("rules") or []
    if rules:
        out.append("## Bash invocation discipline\n\n")
        if bid.get("description"):
            out.append(f"{bid['description'].strip()}\n\n")
        for r in rules:
            sev = r.get("severity", "soft")
            badge = "**hard**" if sev == "hard" else "soft"
            out.append(f"### `{r['id']}` ({badge})\n\n")
            out.append(f"{r['rule']}\n\n")
            out.append(f"_Why:_ {r['reason']}\n\n")
            if r.get("good"):
                good = r["good"].rstrip()
                out.append(f"**Good:**\n```bash\n{good}\n```\n\n")
            if r.get("bad"):
                bad = r["bad"].rstrip()
                out.append(f"**Bad:**\n```bash\n{bad}\n```\n\n")
        enf = bid.get("enforcement") or {}
        if enf:
            out.append("**Enforcement:** ")
            if enf.get("advisory_via_pretooluse_hook"):
                out.append("advisory via PreToolUse hook (see `references/orchestration.md`). ")
            out.append(f"Blocking: `{enf.get('blocking', False)}`.\n\n")

    return "".join(out)


def _write_atomic(path: Path, content: str) -> bool:
    """Write only if content differs. Returns True iff write happened."""
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def generate(check_only: bool = False) -> int:
    targets = [
        (REFS_DIR / "routines.md", _render_routines()),
        (REFS_DIR / "git-discipline.md", _render_git_discipline()),
    ]
    drift = False
    for path, content in targets:
        if check_only:
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            if existing != content:
                print(f"DRIFT: {path}")
                drift = True
            else:
                print(f"OK:    {path}")
        else:
            changed = _write_atomic(path, content)
            print(f"{'wrote' if changed else 'unchanged'}: {path}")
    return 1 if (check_only and drift) else 0


if __name__ == "__main__":
    sys.exit(generate(check_only="--check" in sys.argv))
