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
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import ModuleType

_SCRIPT_DIR = Path(__file__).resolve().parent
_PLUGIN_ROOT = _SCRIPT_DIR.parent.parent  # scripts/iron-laws → plugins/kaizen/
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


# ─── Sub-gate: token-bloat (waste-tokens threshold) ──────────────────

def _gate_token_bloat(scope: str, repo_root: Path) -> list[GateFinding]:
    """Surface findings from kaizen-token-bloat when waste exceeds the
    notice threshold. Advisory only — never blocks the commit."""
    script = _PLUGIN_ROOT / "skills" / "workflow" / "scripts" / "token_bloat.py"
    if not script.is_file():
        return []
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "scan", "--json"],
            cwd=repo_root, capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    out: list[GateFinding] = []
    try:
        data = json.loads(proc.stdout)
    except (ValueError, json.JSONDecodeError):
        return []
    high = int(data.get("high", 0))
    if high:
        out.append(GateFinding(
            gate="token-bloat", severity="warn",
            rule_id="high-findings",
            message=f"{high} high finding(s) — run `kaizen-token-bloat report`"))
    return out


# ─── Sub-gate: coverage (test-coverage gap) ──────────────────────────

def _gate_coverage(scope: str, repo_root: Path) -> list[GateFinding]:
    """Surface kaizen-coverage gaps — uncovered workflow scripts."""
    script = _PLUGIN_ROOT / "skills" / "workflow" / "scripts" / "coverage.py"
    if not script.is_file():
        return []
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "gaps", "--json"],
            cwd=repo_root, capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    try:
        data = json.loads(proc.stdout)
    except (ValueError, json.JSONDecodeError):
        return []
    gaps = data.get("uncovered", []) or []
    if gaps:
        sample = ", ".join(gaps[:3]) + ("…" if len(gaps) > 3 else "")
        return [GateFinding(
            gate="coverage", severity="warn",
            rule_id="uncovered-scripts",
            message=f"{len(gaps)} uncovered script(s): {sample}")]
    return []


# ─── Sub-gate: schema-coverage (feature shape conformance) ───────────

def _gate_schema_coverage(scope: str, repo_root: Path) -> list[GateFinding]:
    """Surface kaizen-schema-coverage gaps — features that fail shape
    conformance (lens-manifest / decision-rubric / plain-config /
    rule-catalog)."""
    script = _PLUGIN_ROOT / "skills" / "workflow" / "scripts" / "schema_coverage.py"
    if not script.is_file():
        return []
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "gaps", "--json"],
            cwd=repo_root, capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    try:
        data = json.loads(proc.stdout)
    except (ValueError, json.JSONDecodeError):
        return []
    if isinstance(data, list) and data:
        sample = ", ".join(f["feature"] for f in data[:3])
        if len(data) > 3:
            sample += "…"
        return [GateFinding(
            gate="schema-coverage", severity="warn",
            rule_id="shape-gaps",
            message=f"{len(data)} feature(s) with shape gaps: {sample}")]
    return []


# ─── Orchestrator ───────────────────────────────────────────────────────

def _classify_frontmatter_findings(audit_data: list) -> list[GateFinding]:
    """Pure-function classifier: convert frontmatter audit rows into split
    GateFinding(s). Two distinct findings emitted:

      - name-mismatch  → severity=error (blocks commit; skill-loader can't route)
      - weak-routing   → severity=warn  (advisory; skill-suggest may miss)

    A single skill with BOTH issues surfaces in BOTH findings — they're
    independent dimensions (rename fixes routing in many cases, but not all).
    """
    if not isinstance(audit_data, list):
        return []
    name_miss = [r for r in audit_data if not r.get("name_match", True)]
    weak = [r for r in audit_data if r.get("trigger_count", 99) < 3]
    out: list[GateFinding] = []
    if name_miss:
        sample = ", ".join(r.get("skill", "?") for r in name_miss[:3])
        if len(name_miss) > 3:
            sample += "…"
        out.append(GateFinding(
            gate="frontmatter-coverage", severity="error",
            rule_id="name-mismatch",
            message=(f"{len(name_miss)} skill(s) — frontmatter `name:` "
                     f"≠ dir basename ({sample}). Fix with: kaizen-frontmatter gaps"),
        ))
    if weak:
        sample = ", ".join(r.get("skill", "?") for r in weak[:3])
        if len(weak) > 3:
            sample += "…"
        out.append(GateFinding(
            gate="frontmatter-coverage", severity="warn",
            rule_id="weak-routing",
            message=(f"{len(weak)} skill(s) — description has <3 quoted "
                     f"trigger phrases ({sample}). Skill-suggest may miss them."),
        ))
    return out


def _gate_frontmatter(scope: str, repo_root: Path) -> list[GateFinding]:
    """SKILL.md frontmatter conformance: name matches dir + ≥3 trigger phrases.

    Emits TWO distinct findings (see ``_classify_frontmatter_findings``) —
    name-mismatch as error (hard-gate), weak-routing as warn (soft-gate).
    """
    script = _PLUGIN_ROOT / "skills" / "workflow" / "scripts" / "frontmatter.py"
    if not script.is_file():
        return []
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "gaps", "--json"],
            cwd=repo_root, capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    try:
        data = json.loads(proc.stdout)
    except (ValueError, json.JSONDecodeError):
        return []
    return _classify_frontmatter_findings(data)


def _gate_name_quality(scope: str, repo_root: Path) -> list[GateFinding]:
    """Surface kaizen-name-quality bad/weak findings — files whose
    name doesn't match their docstring intent."""
    script = _PLUGIN_ROOT / "skills" / "workflow" / "scripts" / "name_quality.py"
    if not script.is_file():
        return []
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "gaps", "--json"],
            cwd=repo_root, capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    try:
        data = json.loads(proc.stdout)
    except (ValueError, json.JSONDecodeError):
        return []
    bads = [r for r in data if r.get("verdict") == "bad"]
    weak = [r for r in data if r.get("verdict") == "weak"]
    if bads:
        sample = ", ".join(Path(r["path"]).name for r in bads[:3])
        if len(bads) > 3:
            sample += "…"
        return [GateFinding(
            gate="name-quality-coverage", severity="warn",
            rule_id="name-intent-mismatch",
            message=f"{len(bads)} bad + {len(weak)} weak: {sample}")]
    if weak:
        return [GateFinding(
            gate="name-quality-coverage", severity="warn",
            rule_id="weak-naming",
            message=f"{len(weak)} weak name-intent match(es)")]
    return []


def _gate_slash_collision(scope: str, repo_root: Path) -> list[GateFinding]:
    """Surface tab-completion-ambiguous slash pairs (>=4-char shared prefix).

    Advisory — most collisions are intentional families (trace /
    trace-search / trace-proxy) and the user accepts them. New
    collisions surfacing means a fresh slash collided with an existing
    one and the author should rename.
    """
    script = _PLUGIN_ROOT / "skills" / "workflow" / "scripts" / "slash_collision.py"
    if not script.is_file():
        return []
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "check", "--json"],
            cwd=repo_root, capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    try:
        data = json.loads(proc.stdout)
    except (ValueError, json.JSONDecodeError):
        return []
    collisions = data.get("collisions", []) if isinstance(data, dict) else []
    if not collisions:
        return []
    sample = "; ".join(
        f"'{c['prefix']}*': {','.join(c['members'])}"
        for c in collisions[:3]
    )
    if len(collisions) > 3:
        sample += "…"
    return [GateFinding(
        gate="slash-collision", severity="warn",
        rule_id="prefix-collision",
        message=(f"{len(collisions)} slash prefix collision(s): {sample}. "
                 f"Run `kaizen-slash-collision check` for the full list."),
    )]


def _gate_menu_lint(scope: str, repo_root: Path) -> list[GateFinding]:
    """AskUserQuestion-driven menu slash commands must declare the perm
    + respect the 4Q × 4-option contract. Errors (missing perm = runtime
    AskUserQuestion failure) surface as error-severity; option/question
    overflows surface as warn-severity (advisory)."""
    script = _PLUGIN_ROOT / "skills" / "workflow" / "scripts" / "menu_lint.py"
    if not script.is_file():
        return []
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "check", "--json"],
            cwd=repo_root, capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    try:
        data = json.loads(proc.stdout)
    except (ValueError, json.JSONDecodeError):
        return []
    findings = data.get("findings", []) if isinstance(data, dict) else []
    if not findings:
        return []
    errors = [f for f in findings if f.get("severity") == "error"]
    warns  = [f for f in findings if f.get("severity") == "warn"]
    out: list[GateFinding] = []
    if errors:
        sample = "; ".join(Path(f["path"]).name for f in errors[:3])
        if len(errors) > 3:
            sample += "…"
        out.append(GateFinding(
            gate="menu-lint", severity="error",
            rule_id="menu-runtime-break",
            message=(f"{len(errors)} menu(s) missing AskUserQuestion perm "
                     f"(wizard would runtime-fail): {sample}. "
                     f"Run `kaizen-menu-lint check` for the full list."),
        ))
    if warns:
        out.append(GateFinding(
            gate="menu-lint", severity="warn",
            rule_id="menu-contract-overflow",
            message=(f"{len(warns)} menu(s) over the 4Q × 4-option "
                     "AskUserQuestion contract — see `kaizen-menu-lint check`."),
        ))
    return out


# Phase 4.C — known kaizen index registry.
# Each entry: (indexer_name, corpus_path_resolver, glob).
# The resolver returns the directory whose contents drive index drift;
# returns None when the index doesn't exist on this machine.
def _brain_corpus_dir() -> Path | None:
    env = os.environ.get("KAIZEN_BRAIN_DIR")
    base = Path(env) if env else Path.home() / ".claude" / ".kaizen" / "brain"
    notes = base / "Notes"
    return notes if notes.is_dir() else None


_INDEXER_REGISTRY: list[tuple[str, "callable", str]] = [
    ("brain", _brain_corpus_dir, "*.md"),
    # Extension point: add (name, dir_fn, glob) for other indexers as
    # they migrate to _index_kit.compute_corpus_drift.
]


def _check_indexer_stale() -> list[GateFinding]:
    """Compare each registered index's current corpus hash against the
    last-recorded hash in indexer-state.json. Warn on mismatch.
    """
    state_dir_env = os.environ.get("KAIZEN_INDEXER_STATE_DIR")
    state_dir = (Path(state_dir_env).expanduser() if state_dir_env
                  else Path.home() / ".claude" / ".kaizen")
    state_file = state_dir / "indexer-state.json"
    try:
        sys.path.insert(0, str(_PLUGIN_ROOT / "skills" / "workflow" / "scripts"))
        # Post-DOMAIN-6: _index_kit moved to scripts/daemon/
        sys.path.insert(0, str(_PLUGIN_ROOT / "scripts" / "daemon"))
        import _index_kit as _ik  # type: ignore
    except ImportError:
        return []
    try:
        state = (json.loads(state_file.read_text(encoding="utf-8"))
                  if state_file.is_file() else {})
    except (OSError, json.JSONDecodeError):
        state = {}
    out: list[GateFinding] = []
    for name, dir_fn, glob in _INDEXER_REGISTRY:
        try:
            corpus_dir = dir_fn()
        except Exception:  # noqa: BLE001 — indexer probe shouldn't blow gate
            continue
        if corpus_dir is None:
            continue
        current = _ik.compute_corpus_drift(corpus_dir, glob)
        if not current:
            continue
        prior = state.get(name, "")
        if prior and prior != current:
            out.append(GateFinding(
                gate="brain-drift", severity="warn",
                rule_id="indexer-stale",
                message=(f"{name!r} index hash drift: state={prior} "
                         f"current={current}. Run "
                         f"`kaizen-{name} index` (or wait for the matching "
                         f"daemon job) to refresh."),
            ))
    return out


def _top_level_imports(claude_md_text: str, base_dir: Path) -> list[Path]:
    """Return resolved Paths of top-level `@import` directives in
    a CLAUDE.md body. Same resolution rules as _expand_imports but
    NO recursion — top level only.
    """
    out: list[Path] = []
    for m in _IMPORT_LINE_RE.finditer(claude_md_text):
        raw = m.group(1)
        if raw.startswith("~/"):
            target = Path.home() / raw[2:]
        elif raw.startswith("/"):
            target = Path(raw)
        else:
            target = base_dir / raw
        try:
            out.append(target.resolve())
        except OSError:
            continue
    return out


def _loaded_file_paths_set() -> set[str]:
    """Set of file_paths from the InstructionsLoaded jsonl. Empty when
    the log is absent / unreadable / not yet seeded."""
    log_env = os.environ.get("KAIZEN_INSTRUCTIONS_LOADED_LOG")
    if log_env:
        path = Path(log_env).expanduser()
    else:
        base = os.environ.get("KAIZEN_DIR") or (Path.home() / ".claude" / ".kaizen")
        path = Path(base) / "instructions-loaded.jsonl"
    if not path.is_file():
        return set()
    seen: set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            fp = entry.get("file_path")
            if isinstance(fp, str) and fp:
                # Normalize: resolve symlinks so comparisons match.
                try:
                    seen.add(str(Path(fp).resolve()))
                except OSError:
                    seen.add(fp)
    except OSError:
        return set()
    return seen


def _check_expected_imports_fired() -> list[GateFinding]:
    """Detect @imports in CLAUDE.md whose targets exist on disk but the
    InstructionsLoaded audit never recorded loading them."""
    target_env = os.environ.get("KAIZEN_CLAUDE_MD_PATH")
    claude_md = (Path(target_env).expanduser() if target_env
                 else Path.home() / ".claude" / "CLAUDE.md")
    if not claude_md.is_file():
        return []
    try:
        text = claude_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    expected = _top_level_imports(text, claude_md.parent)
    # Filter: only paths that EXIST on disk (broken / typo paths are
    # a different concern — Claude Code tolerates them silently, but
    # they're not a "didn't fire" signal).
    expected_existing = [p for p in expected if p.is_file()]
    if not expected_existing:
        return []
    fired = _loaded_file_paths_set()
    out: list[GateFinding] = []
    for p in expected_existing:
        if str(p) not in fired:
            out.append(GateFinding(
                gate="brain-drift", severity="warn",
                rule_id="expected-import-not-fired",
                message=(f"{claude_md} @imports {p.name} but the "
                         "InstructionsLoaded audit never recorded it "
                         "loading. Either the import was declined (run "
                         "Claude Code once + approve), or the path "
                         "is wrong. File exists on disk; just no load "
                         "event for it."),
            ))
    return out


# ─── Sub-gate: brain-drift ───────────────────────────────────────────


def _gate_brain_drift(scope: str, repo_root: Path) -> list[GateFinding]:
    """Detect drift across the auto-recording flow:

    1. ``memory-index-drift`` — MEMORY.md entry count != sibling *.md count
    2. ``auto-load-stale`` — auto-load.md mtime < Persona.md mtime
    3. ``gate-orphan`` — gates/<slug>.md backs a directive no longer present
    4. ``pin-missing-note`` — pin references a Note that doesn't exist

    Advisory only — these are next-tick-self-healing conditions.
    """
    out: list[GateFinding] = []

    # Resolve paths via env (matches the modules they audit)
    brain_dir = Path(os.environ.get("KAIZEN_BRAIN_DIR") or
                     (Path.home() / ".claude" / ".kaizen" / "brain"))
    memory_dir = Path(os.environ.get("KAIZEN_BETTER_MEMORY_DIR") or
                      (Path.home() / ".claude" / "projects" / "default" / "memory"))
    auto_load = Path(os.environ.get("KAIZEN_AUTO_LOAD_PATH") or
                     (Path.home() / ".claude" / ".kaizen" / "auto-load.md"))
    gates_dir = Path(os.environ.get("KAIZEN_GATES_DIR") or
                     (Path.home() / ".claude" / ".kaizen" / "gates"))
    pins_path = Path(os.environ.get("KAIZEN_AUTO_LOAD_PINS_PATH") or
                     (Path.home() / ".claude" / ".kaizen" / "auto-load-pins.json"))

    # (1) MEMORY.md index drift
    if memory_dir.is_dir():
        memory_md = memory_dir / "MEMORY.md"
        siblings = [p for p in memory_dir.glob("*.md") if p.name != "MEMORY.md"]
        if memory_md.is_file() and siblings:
            text = memory_md.read_text(encoding="utf-8", errors="replace")
            indexed = sum(1 for line in text.splitlines()
                          if line.startswith("- ["))
            if indexed != len(siblings):
                out.append(GateFinding(
                    gate="brain-drift", severity="warn",
                    rule_id="memory-index-drift",
                    message=(f"MEMORY.md indexes {indexed} entries but dir "
                             f"has {len(siblings)} sibling .md files — "
                             "run `kaizen-better-memory regen` or wait for "
                             "the memory-sync daemon tick."),
                ))

    # (2) auto-load.md stale relative to Persona.md
    persona = brain_dir / "Persona.md"
    if auto_load.is_file() and persona.is_file():
        try:
            if persona.stat().st_mtime > auto_load.stat().st_mtime:
                out.append(GateFinding(
                    gate="brain-drift", severity="warn",
                    rule_id="auto-load-stale",
                    message=(f"{auto_load} older than {persona} — "
                             "run `kaizen-auto-load` or wait for the "
                             "auto-load daemon tick."),
                ))
        except OSError:
            pass

    # (3) orphan gate files (slug not in current Persona directives)
    if gates_dir.is_dir() and persona.is_file():
        try:
            sys.path.insert(0, str(_PLUGIN_ROOT / "skills" / "workflow" / "scripts"))
            import auto_load as _al  # type: ignore
            parsed = _al.parse_persona(persona.read_text(encoding="utf-8"))
            valid_slugs = {
                d["note"].rsplit("/", 1)[-1].removesuffix(".md")
                for d in parsed["directives"]
            }
            for p in gates_dir.glob("*.md"):
                if p.stem not in valid_slugs:
                    out.append(GateFinding(
                        gate="brain-drift", severity="warn",
                        rule_id="gate-orphan",
                        message=(f"gates/{p.name} has no backing directive "
                                 f"in Persona — slug {p.stem!r} not found. "
                                 "Next daemon tick will prune it."),
                    ))
        except (ImportError, OSError):
            pass

    # (4a) Expected @import didn't fire — uses Phase A's
    # InstructionsLoaded jsonl to detect silent install failures.
    out.extend(_check_expected_imports_fired())

    # (4b) Indexer-stale — for each known kaizen index, compare current
    # corpus hash against last-known-hash in indexer-state.json.
    out.extend(_check_indexer_stale())

    # (4) Pin references a Note that doesn't exist
    if pins_path.is_file() and brain_dir.is_dir():
        try:
            pins = json.loads(pins_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pins = []
        for pin in pins if isinstance(pins, list) else []:
            # Try both with + without .md suffix
            candidates = [brain_dir / f"{pin}.md", brain_dir / pin]
            if not any(c.is_file() for c in candidates):
                out.append(GateFinding(
                    gate="brain-drift", severity="warn",
                    rule_id="pin-missing-note",
                    message=(f"pin {pin!r} references a Note that does not "
                             "exist in the brain — unpin it via "
                             f"`kaizen-brain unpin {pin}` or create the Note."),
                ))

    return out


# ─── Sub-gate: claude-md-bloat (post-@import expansion) ─────────────


_IMPORT_LINE_RE = re.compile(r"(?<!\\)@([^\s@]+)")


def _expand_imports(text: str, base_dir: Path, max_depth: int = 5,
                     _seen: set | None = None) -> str:
    """Recursively expand `@path` import directives in ``text``.

    - Relative paths resolve against ``base_dir`` (per Claude Code doc:
      relative-to-file-containing-import, not cwd).
    - Absolute paths used as-is.
    - ``~`` expansion via ``Path.home()`` (sandbox-patchable).
    - Cycles short-circuit via ``_seen``.
    - Missing imports are left as literal `@path` lines (matches Claude
      Code's tolerance — declined imports stay disabled, not erroring).
    - max_depth=0 leaves all `@path` lines unexpanded; max_depth=N
      expands up to N hops (matching the documented 5-hop ceiling).

    Pure modulo filesystem reads — no writes, no env reads.
    """
    if max_depth <= 0:
        return text
    if _seen is None:
        _seen = set()
    out_lines = []
    for line in text.splitlines(keepends=False):
        m = _IMPORT_LINE_RE.search(line)
        if not m:
            out_lines.append(line)
            continue
        raw = m.group(1)
        if raw.startswith("~/"):
            target = Path.home() / raw[2:]
        elif raw.startswith("/"):
            target = Path(raw)
        else:
            target = base_dir / raw
        try:
            target = target.resolve()
        except OSError:
            out_lines.append(line)
            continue
        if not target.is_file():
            out_lines.append(line)
            continue
        if str(target) in _seen:
            # Cycle — emit the file's body once but don't recurse further.
            out_lines.append(line)
            continue
        _seen2 = _seen | {str(target)}
        try:
            inner_text = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            out_lines.append(line)
            continue
        expanded = _expand_imports(
            inner_text, target.parent, max_depth - 1, _seen2)
        out_lines.append(expanded)
    return "\n".join(out_lines)


def _gate_claude_md_bloat(scope: str, repo_root: Path) -> list[GateFinding]:
    """Warn when CLAUDE.md's post-@import expansion exceeds budget.

    Catches the case where the source CLAUDE.md is small but its
    @imports pull in megabytes — invisible to a `wc -l CLAUDE.md`
    check but very visible in context cost.

    Env:
      KAIZEN_CLAUDE_MD_PATH    — override target file (default
                                  ~/.claude/CLAUDE.md)
      KAIZEN_CLAUDE_MD_BUDGET  — bytes; default 20480 (20 KB)
    """
    target_env = os.environ.get("KAIZEN_CLAUDE_MD_PATH")
    if target_env:
        target = Path(target_env).expanduser()
    else:
        target = Path.home() / ".claude" / "CLAUDE.md"
    if not target.is_file():
        return []
    try:
        budget = int(os.environ.get("KAIZEN_CLAUDE_MD_BUDGET", "20480"))
    except ValueError:
        budget = 20480
    try:
        src = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    expanded = _expand_imports(src, target.parent, max_depth=5)
    size = len(expanded.encode("utf-8"))
    if size <= budget:
        return []
    return [GateFinding(
        gate="claude-md-bloat", severity="warn",
        rule_id="expansion-over-budget",
        message=(f"{target} expands to {size}B (budget {budget}B). "
                 "Trim @import targets, raise KAIZEN_CLAUDE_MD_BUDGET, "
                 "or move bulk content to .claude/rules/ with paths: "
                 "frontmatter (path-scoped, not always-loaded)."),
    )]


# ─── Sub-gate: auto-load-budget ──────────────────────────────────────


def _gate_auto_load_budget(scope: str, repo_root: Path) -> list[GateFinding]:
    """Warn when the daemon-built ~/.claude/.kaizen/auto-load.md exceeds
    KAIZEN_AUTO_LOAD_BUDGET (default 5120 bytes).

    Advisory only — never blocks. An oversized file means the daemon's
    truncation logic didn't fire enough; raise the budget or reduce
    top_n. Read-only filesystem probe; no subprocess.
    """
    env_path = os.environ.get("KAIZEN_AUTO_LOAD_PATH")
    if env_path:
        target = Path(env_path).expanduser()
    else:
        target = Path.home() / ".claude" / ".kaizen" / "auto-load.md"
    if not target.is_file():
        return []
    try:
        budget = int(os.environ.get("KAIZEN_AUTO_LOAD_BUDGET", "5120"))
    except ValueError:
        budget = 5120
    try:
        size = target.stat().st_size
    except OSError:
        return []
    if size <= budget:
        return []
    return [GateFinding(
        gate="auto-load-budget", severity="warn",
        rule_id="size-over-budget",
        message=(f"{target} is {size}B (budget {budget}B). "
                 "Raise KAIZEN_AUTO_LOAD_BUDGET or reduce top_n in "
                 "auto_load.build_auto_load()."),
    )]


SUB_GATES = {
    "iron-laws":              _gate_iron_laws,
    "etu":                    _gate_etu,
    "karpathy":               _gate_karpathy,
    "validator":              _gate_validator,
    "token-bloat":            _gate_token_bloat,
    "code-to-test-coverage":  _gate_coverage,           # 1:1 script ↔ test-file mapping
    "schema-coverage":        _gate_schema_coverage,    # feature shape conformance
    "name-quality-coverage":  _gate_name_quality,       # filename ↔ docstring intent
    "frontmatter-coverage":   _gate_frontmatter,        # SKILL name=dir + ≥3 trigger phrases
    "slash-collision":        _gate_slash_collision,   # tab-completion-ambiguous prefix pairs
    "menu-lint":              _gate_menu_lint,         # AskUserQuestion contract conformance
    "auto-load-budget":       _gate_auto_load_budget,  # daemon-built auto-load.md size
    "brain-drift":            _gate_brain_drift,       # MEMORY/auto-load/gates/pins drift
    "claude-md-bloat":        _gate_claude_md_bloat,   # CLAUDE.md post-@import expansion size
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
    sys.path.insert(0, str(_SCRIPT_DIR))
    import _envelope  # peer module — must exist
    total_ms = sum(v.durations_ms.values()) if v.durations_ms else None
    return _envelope.render(_envelope.wrap(
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
    ))


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
