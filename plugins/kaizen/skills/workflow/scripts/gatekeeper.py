#!/usr/bin/env python3
"""kaizen gatekeeper — unified gate aggregating every Python-callable check.

One entry point. Runs all sub-gates, emits a structured verdict, exits 1
on any red finding. Sub-gates:

  - iron-laws        — `_iron_laws.run_checks()` over staged or all
  - efficient-tool-use — `etu_scan.scan_files()` over staged shell scripts
  - karpathy          — subprocess `karpathy/scripts/*.py` on changed paths
  - plugin-validator  — `plugin-development/scripts/validate.py` (light)

Each sub-gate's findings normalize into a common `GateFinding` shape and
roll up into a single verdict (`green` / `yellow` / `red`).

## CLI

    python3 gatekeeper.py check [--staged|--all] [--json]
    python3 gatekeeper.py list                    # list sub-gates
    python3 gatekeeper.py only <gate-name>        # run one sub-gate
    python3 gatekeeper.py --version

## Exit

  0 — green (no findings, or only `info`)
  1 — red (one or more `error` / `hard`)
  2 — invocation error
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import ModuleType

_SCRIPT_DIR = Path(__file__).resolve().parent
_PLUGIN_ROOT = _SCRIPT_DIR.parent.parent.parent  # plugins/kaizen/
_REPO_ROOT_DEFAULT = _PLUGIN_ROOT.parent.parent  # repo root (kaizen-md)

# ─── Common shapes ──────────────────────────────────────────────────────


@dataclass
class GateFinding:
    """Normalized finding shape — every sub-gate maps into this."""
    gate: str               # iron-laws | etu | karpathy | validator
    severity: str           # error | warn | info  (mapped from each sub-gate's vocab)
    rule_id: str            # source-gate-specific id (law_id, pattern_id, etc.)
    message: str
    file: str = ""
    line: int | None = None


@dataclass
class Verdict:
    overall: str            # green | yellow | red
    findings: list[GateFinding] = field(default_factory=list)
    durations_ms: dict[str, int] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)  # severity → count


# ─── Severity normalization ─────────────────────────────────────────────

# iron-laws use "hard" / "soft"; etu uses "error" / "warn" / "info";
# karpathy scripts return exit codes; validator emits "hard" / "soft".
_SEV_MAP = {
    "hard": "error",
    "soft": "warn",
    "error": "error",
    "warn": "warn",
    "info": "info",
}


def _norm_sev(s: str) -> str:
    return _SEV_MAP.get(s, "warn")


def _load_module(name: str, path: Path) -> ModuleType:
    """Explicit module loader — avoids `sys.path` collisions when two skills
    both have `application/_loader.py` (iron-laws and efficient-tool-use).
    Each call gives the module a unique synthetic name so the import cache
    doesn't return the wrong one."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ─── Sub-gate: iron-laws ────────────────────────────────────────────────


def _gate_iron_laws(scope: str, repo_root: Path) -> list[GateFinding]:
    try:
        # iron-laws's _iron_laws.py also imports its own _loader.py from
        # iron-laws/application/ — let it manage its own sys.path inside,
        # we just load THIS module by file path to avoid collisions.
        mod = _load_module("kaizen_iron_laws", _SCRIPT_DIR / "_iron_laws.py")
    except ImportError as e:
        return [GateFinding(gate="iron-laws", severity="warn",
                            rule_id="import-error",
                            message=f"_iron_laws not importable: {e}")]
    findings = mod.run_checks(scope=scope, repo_root=repo_root)
    return [
        GateFinding(
            gate="iron-laws",
            severity=_norm_sev(f.severity),
            rule_id=f.law_id,
            message=f.message + (f" — {f.detail}" if f.detail else ""),
            file=f.path,
        )
        for f in findings
    ]


# ─── Sub-gate: efficient-tool-use ───────────────────────────────────────


def _gate_etu(scope: str, repo_root: Path) -> list[GateFinding]:
    etu_dir = _PLUGIN_ROOT / "skills" / "efficient-tool-use" / "application"
    try:
        mod = _load_module("kaizen_etu_scan", etu_dir / "etu_scan.py")
    except ImportError as e:
        return [GateFinding(gate="etu", severity="warn",
                            rule_id="import-error",
                            message=f"etu_scan not importable: {e}")]

    if scope == "staged":
        files = mod._staged_shell_files(repo_root)  # noqa: SLF001
    else:
        files = mod._all_shell_files(repo_root)  # noqa: SLF001

    findings = mod.scan_files(files, repo_root=repo_root)
    return [
        GateFinding(
            gate="etu",
            severity=_norm_sev(f.severity),
            rule_id=f.pattern_id,
            message=f"{f.matched} — {f.why_bad}",
            file=f.file,
            line=f.line,
        )
        for f in findings
    ]


# ─── Sub-gate: karpathy scanners ────────────────────────────────────────


def _gate_karpathy(scope: str, repo_root: Path) -> list[GateFinding]:
    """Run karpathy diff-level scanners. Skipped when no staged diff."""
    karpathy_dir = _PLUGIN_ROOT / "skills" / "karpathy" / "scripts"
    if not karpathy_dir.is_dir():
        return []
    if scope != "staged":
        # Karpathy scanners are diff-oriented; running --all is noisy.
        return []

    try:
        staged = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=AM"],
            cwd=repo_root, text=True,
        ).strip().splitlines()
    except subprocess.CalledProcessError:
        return []
    if not staged:
        return []

    out: list[GateFinding] = []
    for script in ("complexity_checker.py", "diff_surgeon.py",
                   "assumption_linter.py", "goal_verifier.py"):
        sp = karpathy_dir / script
        if not sp.is_file():
            continue
        try:
            proc = subprocess.run(
                [sys.executable, str(sp), *staged],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            out.append(GateFinding(gate="karpathy", severity="warn",
                                   rule_id=script,
                                   message=f"scanner failed: {e}"))
            continue
        # karpathy scanners are best-effort; exit-non-zero means a finding.
        if proc.returncode != 0 and proc.stdout.strip():
            for line in proc.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                out.append(GateFinding(gate="karpathy", severity="warn",
                                       rule_id=script.replace(".py", ""),
                                       message=line[:200]))
    return out


# ─── Sub-gate: plugin-validator ─────────────────────────────────────────


def _gate_validator(scope: str, repo_root: Path) -> list[GateFinding]:
    """Light wrapper: invoke validate.py and count hard/soft findings."""
    val = _PLUGIN_ROOT / "skills" / "plugin-development" / "scripts" / "validate.py"
    if not val.is_file():
        return []
    try:
        proc = subprocess.run(
            [sys.executable, str(val)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return [GateFinding(gate="validator", severity="warn",
                            rule_id="invocation-error",
                            message=f"{e}")]
    # validate.py's summary line: "plugin-development validate: 0 hard, 0 soft across N feature(s)"
    out: list[GateFinding] = []
    for line in proc.stdout.splitlines():
        if "hard" in line and "soft" in line:
            try:
                hard = int(line.split("hard")[0].rsplit(":", 1)[-1].strip().rstrip(","))
                soft = int(line.split("hard,")[1].split("soft")[0].strip())
            except (ValueError, IndexError):
                continue
            if hard:
                out.append(GateFinding(gate="validator", severity="error",
                                       rule_id="hard-findings",
                                       message=f"{hard} hard finding(s) — re-run `validate.py -v`"))
            if soft:
                out.append(GateFinding(gate="validator", severity="warn",
                                       rule_id="soft-findings",
                                       message=f"{soft} soft finding(s)"))
            break
    if proc.returncode != 0 and not out:
        out.append(GateFinding(gate="validator", severity="error",
                               rule_id="exit-nonzero",
                               message=f"validate.py exited {proc.returncode}"))
    return out


# ─── Orchestrator ───────────────────────────────────────────────────────

SUB_GATES = {
    "iron-laws": _gate_iron_laws,
    "etu": _gate_etu,
    "karpathy": _gate_karpathy,
    "validator": _gate_validator,
}


def gate_all(scope: str = "staged",
             repo_root: Path | None = None,
             only: str | None = None) -> Verdict:
    """Run all (or one) sub-gates and aggregate the verdict."""
    if repo_root is None:
        repo_root = _REPO_ROOT_DEFAULT
    findings: list[GateFinding] = []
    durations: dict[str, int] = {}

    gates = {only: SUB_GATES[only]} if only else SUB_GATES
    for name, fn in gates.items():
        t0 = time.monotonic()
        try:
            findings.extend(fn(scope, repo_root))
        except Exception as e:  # noqa: BLE001
            findings.append(GateFinding(gate=name, severity="warn",
                                        rule_id="gate-crashed",
                                        message=f"{type(e).__name__}: {e}"))
        durations[name] = int((time.monotonic() - t0) * 1000)

    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1

    if counts.get("error", 0):
        overall = "red"
    elif counts.get("warn", 0):
        overall = "yellow"
    else:
        overall = "green"

    return Verdict(overall=overall, findings=findings,
                   durations_ms=durations, counts=counts)


def render_text(v: Verdict) -> str:
    out = [f"kaizen gatekeeper: {v.overall.upper()}\n"]
    if v.counts:
        out.append(f"  counts: {dict(sorted(v.counts.items()))}\n")
    out.append(f"  timings (ms): {dict(sorted(v.durations_ms.items()))}\n")
    if v.findings:
        out.append("\n")
        for f in v.findings:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            out.append(f"  [{f.severity}] {f.gate}:{f.rule_id}  {loc}\n"
                       f"    {f.message}\n")
    return "".join(out)


def render_json(v: Verdict, argv: list[str] | None = None) -> str:
    """Canonical-envelope-wrapped JSON output. Schema:
    `assets/schemas/tool-output.schema.json`. Use this over hand-rolled
    JSON so consumers get the same shape across all kaizen tools."""
    # Lazy import — _envelope.py lives in the same dir
    sys.path.insert(0, str(_SCRIPT_DIR))
    try:
        import _envelope  # type: ignore
    except ImportError:
        # Fallback: legacy bare-JSON shape if helper missing
        return json.dumps({
            "overall": v.overall,
            "counts": v.counts,
            "durations_ms": v.durations_ms,
            "findings": [asdict(f) for f in v.findings],
        }, indent=2)

    # Total elapsed = sum of sub-gate durations (parallelism would skew
    # this; current gates run sequentially so sum is accurate).
    total_ms = sum(v.durations_ms.values()) if v.durations_ms else None

    envelope = _envelope.wrap(
        tool="kaizen-gatekeeper",
        tool_version="1.0.0",
        data={
            "durations_ms": dict(sorted(v.durations_ms.items())),
            "findings": [asdict(f) for f in v.findings],
        },
        verdict=v.overall,
        counts=v.counts,
        duration_ms=total_ms,
        argv=argv,
    )
    return _envelope.render(envelope)


# ─── CLI ────────────────────────────────────────────────────────────────


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        sys.stderr.write(__doc__ or "")
        return 2
    if argv[0] == "--version":
        print("kaizen-gatekeeper 1.0.0")
        return 0
    if argv[0] == "list":
        for name in SUB_GATES:
            print(name)
        return 0

    want_json = "--json" in argv
    scope = "all" if "--all" in argv else "staged"
    only = None
    if argv[0] == "only":
        if len(argv) < 2:
            sys.stderr.write("gatekeeper: `only` needs a sub-gate name\n")
            return 2
        only = argv[1]
        if only not in SUB_GATES:
            sys.stderr.write(f"gatekeeper: unknown sub-gate: {only}\n")
            return 2
    elif argv[0] != "check":
        sys.stderr.write(f"gatekeeper: unknown command: {argv[0]}\n")
        return 2

    v = gate_all(scope=scope, only=only)
    sys.stdout.write(render_json(v, argv=sys.argv) if want_json else render_text(v))
    return 1 if v.overall == "red" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
