"""kaizen-token-bloat — scan everything Claude sees for token bloat.

Finds high-token content in places the agent loads at runtime:

  1. YAML reason_template / additionalContext / systemMessage values
     in skills/*/domain/*.yaml (auto-handoff config.yaml is the canonical
     example — every Stop-hook fire burns the template into agent context)
  2. SKILL.md bodies over a size threshold (default 400 lines)
  3. commands/*.md bodies over a size threshold (default 100 lines)
  4. hooks/claude/*.sh scripts that emit multi-line additionalContext /
     systemMessage strings (the session-intake.sh pattern)

Stdlib-only. Fast (<200ms over the whole plugin). Designed to be
fired from SessionEnd hook and surfaced at next SessionStart so the
agent sees fresh findings without the user running anything.

## Subcommands

    scan [--json] [--cache]    full scan; --cache writes findings file
    report [--json]            print last cached findings
    surface                    one-line SessionStart-injection summary
                               (empty stdout if no findings or cache stale)

## Cache

Findings written to:  $KAIZEN_DIR/token-bloat-findings.json
(default: ~/.claude/.kaizen/token-bloat-findings.json)
TTL: KAIZEN_TOKEN_BLOAT_TTL_HOURS (default 6h)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

# ── Thresholds (override via env) ────────────────────────────────────

def _envint(key: str, default: int) -> int:
    v = os.environ.get(key, "")
    try:
        return int(v) if v else default
    except ValueError:
        return default


_YAML_TEMPLATE_LINES_HIGH   = _envint("KAIZEN_BLOAT_YAML_LINES_HIGH",   15)
_YAML_TEMPLATE_LINES_MED    = _envint("KAIZEN_BLOAT_YAML_LINES_MED",    8)
_SKILLMD_LINES_HIGH         = _envint("KAIZEN_BLOAT_SKILLMD_LINES_HIGH", 800)
_SKILLMD_LINES_MED          = _envint("KAIZEN_BLOAT_SKILLMD_LINES_MED",  400)
_COMMANDMD_LINES_HIGH       = _envint("KAIZEN_BLOAT_CMDMD_LINES_HIGH",   200)
_COMMANDMD_LINES_MED        = _envint("KAIZEN_BLOAT_CMDMD_LINES_MED",    100)
_HOOK_HEREDOC_LINES_HIGH    = _envint("KAIZEN_BLOAT_HOOK_LINES_HIGH",    40)
_HOOK_HEREDOC_LINES_MED     = _envint("KAIZEN_BLOAT_HOOK_LINES_MED",     20)


# ── Token estimation ─────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Rough char/4 heuristic. Good enough for relative ranking."""
    return len(text) // 4


# ── Quality scoring ──────────────────────────────────────────────────

# Phrases that signal procedural restatement / wordy prose. Each
# occurrence costs quality points. Lowercase; matched case-insensitive.
_BOILERPLATE_PHRASES = (
    "in order to",
    "please note",
    "it is important to note",
    "it should be noted",
    "as you can see",
    "as mentioned",
    "as discussed",
    "needless to say",
    "first and foremost",
)

# Decorative box-drawing / separator characters.
_DECORATIVE_CHARS = set("━─═│┃┣┫┳┻╋▓░▒▀▄█")

# Pattern: step-by-step numbered recipe (3+ numbered lines).
_NUMBERED_STEP_RE = re.compile(r"^\s*\d+\.\s", re.MULTILINE)

# Pattern: skill / file reference (raises quality — pointer beats paste).
_REFERENCE_RE = re.compile(
    r"\b(see|refer to|cf\.|`[A-Za-z][-A-Za-z0-9_/.]*\.(md|py|yaml|sh|json)`)",
    re.IGNORECASE,
)

# Imperative verbs (one-word command phrasing — high signal per token).
_IMPERATIVE_VERBS = (
    "run", "use", "set", "add", "remove", "fix", "check", "load",
    "scan", "trim", "split", "merge", "wire", "drop", "skip",
)


def quality_score(body: str) -> tuple[int, str]:
    """Return (score, hint) for a chunk of agent-loaded text.

    Score 0..100; higher = more signal-per-token. The hint is a short
    diagnostic explaining the largest penalty. Pure heuristic — useful
    for ranking, not absolute judgement."""
    if not body or not body.strip():
        return 100, "empty"

    text = body.strip()
    lower = text.lower()
    score = 100
    notes: list[str] = []

    # Penalty: decorative characters > 0.5% of body
    dec_count = sum(1 for ch in text if ch in _DECORATIVE_CHARS)
    if dec_count and len(text) > 0:
        if dec_count * 200 > len(text):  # > 0.5%
            score -= 10
            notes.append(f"{dec_count} decorative chars")

    # Penalty: emoji density (rough proxy — count chars > U+2600 range)
    emoji_count = sum(1 for ch in text if ord(ch) > 0x2600 and ch not in _DECORATIVE_CHARS)
    if emoji_count > 3:
        score -= 5
        notes.append(f"{emoji_count} emoji")

    # Penalty: boilerplate phrases
    bp_hits = sum(lower.count(p) for p in _BOILERPLATE_PHRASES)
    if bp_hits:
        score -= 5 * bp_hits
        notes.append(f"{bp_hits} boilerplate phrase(s)")

    # Penalty: step-by-step numbered recipe (3+ numbered lines)
    numbered = _NUMBERED_STEP_RE.findall(text)
    if len(numbered) >= 3:
        score -= 15
        notes.append(f"{len(numbered)}-step recipe (re-teaching)")

    # Penalty: excessive blank lines (consecutive \n\n\n+)
    blank_runs = len(re.findall(r"\n\s*\n\s*\n", text))
    if blank_runs:
        score -= 5 * blank_runs
        notes.append(f"{blank_runs} blank-line run(s)")

    # Bonus: pointer references (see X / `file.py`) — high signal
    ref_hits = len(_REFERENCE_RE.findall(text))
    if ref_hits:
        score += min(10, ref_hits * 2)
        notes.append(f"{ref_hits} pointer ref(s) [+]")

    # Bonus: imperative density (one-word verbs at line starts)
    imp_count = 0
    for line in text.splitlines():
        s = line.strip().lower().split(maxsplit=1)
        if s and s[0] in _IMPERATIVE_VERBS:
            imp_count += 1
    if imp_count and len(text.splitlines()) > 0:
        line_total = max(1, len(text.splitlines()))
        if imp_count * 4 >= line_total:  # > 25% imperative lines
            score += 5
            notes.append(f"{imp_count} imperative line(s) [+]")

    score = max(0, min(100, score))
    hint = "; ".join(notes) if notes else "uniform prose"
    return score, hint


# ── Plugin root resolution ───────────────────────────────────────────

def _plugin_root() -> Path:
    """Auto-discover plugins/kaizen root from this script's location."""
    return _SCRIPT_DIR.parents[2]


# ── Scanners ─────────────────────────────────────────────────────────

# Match `key: |\n  ...indented block...` blocks in YAML.
_YAML_BLOCK_RE = re.compile(
    r"^(\s*)(reason_template|additionalContext|systemMessage|reason)\s*:\s*[|>][-+]?\s*$",
    re.MULTILINE,
)


def _scan_yaml_template(path: Path, root: Path) -> list[dict]:
    """Find oversized reason_template/additionalContext/systemMessage blocks."""
    findings: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return findings
    for m in _YAML_BLOCK_RE.finditer(text):
        indent = len(m.group(1))
        key = m.group(2)
        # Collect the indented body following this line
        start = m.end()
        lines = []
        for line in text[start:].splitlines():
            if line.strip() == "":
                lines.append(line)
                continue
            # Body lines must be indented MORE than the key's indent
            line_indent = len(line) - len(line.lstrip(" "))
            if line_indent <= indent:
                break
            lines.append(line)
        body = "\n".join(lines).rstrip()
        line_count = sum(1 for ln in lines if ln.strip())
        if line_count >= _YAML_TEMPLATE_LINES_MED:
            sev = ("high" if line_count >= _YAML_TEMPLATE_LINES_HIGH
                   else "medium")
            q, q_hint = quality_score(body)
            findings.append({
                "severity":     sev,
                "kind":         "yaml-template",
                "path":         str(path.relative_to(root)),
                "field":        key,
                "lines":        line_count,
                "tokens":       estimate_tokens(body),
                "quality":      q,
                "quality_hint": q_hint,
                "hint":         f"{key} burns into agent context on every fire — trim to ~2-3 lines",
            })
    return findings


def _scan_markdown_size(path: Path, root: Path, line_med: int, line_high: int,
                          kind: str, hint: str) -> list[dict]:
    """Flag oversized markdown bodies."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    line_count = text.count("\n") + 1
    if line_count < line_med:
        return []
    sev = "high" if line_count >= line_high else "medium"
    q, q_hint = quality_score(text)
    return [{
        "severity":     sev,
        "kind":         kind,
        "path":         str(path.relative_to(root)),
        "field":        "(body)",
        "lines":        line_count,
        "tokens":       estimate_tokens(text),
        "quality":      q,
        "quality_hint": q_hint,
        "hint":         hint,
    }]


_HOOK_HEREDOC_RE = re.compile(
    r"""body\s*=\s*['"]['"]['"]([\s\S]*?)['"]['"]['"]""",
)


def _scan_hook_heredoc(path: Path, root: Path) -> list[dict]:
    """Find multi-line additionalContext / systemMessage embedded in hook scripts."""
    findings: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return findings
    for m in _HOOK_HEREDOC_RE.finditer(text):
        body = m.group(1)
        line_count = body.count("\n") + 1
        if line_count >= _HOOK_HEREDOC_LINES_MED:
            sev = ("high" if line_count >= _HOOK_HEREDOC_LINES_HIGH
                   else "medium")
            q, q_hint = quality_score(body)
            findings.append({
                "severity":     sev,
                "kind":         "hook-heredoc",
                "path":         str(path.relative_to(root)),
                "field":        "body=''' ... '''",
                "lines":        line_count,
                "tokens":       estimate_tokens(body),
                "quality":      q,
                "quality_hint": q_hint,
                "hint":         "hook injects this into SessionStart/Stop context — trim or move to a skill",
            })
    return findings


def scan_all(root: Path | None = None) -> list[dict]:
    """Run every scanner over the plugin. Returns findings sorted by tokens desc."""
    root = root or _plugin_root()
    findings: list[dict] = []

    # YAML reason_template blocks
    for p in (root / "skills").rglob("domain/*.yaml"):
        findings.extend(_scan_yaml_template(p, root))

    # SKILL.md sizes
    for p in (root / "skills").rglob("SKILL.md"):
        findings.extend(_scan_markdown_size(
            p, root, _SKILLMD_LINES_MED, _SKILLMD_LINES_HIGH,
            kind="skill-md",
            hint="SKILL.md loads in full when invoked — split references/ or trim prose",
        ))

    # commands/*.md sizes
    cmds = root / "commands"
    if cmds.is_dir():
        for p in sorted(cmds.glob("*.md")):
            findings.extend(_scan_markdown_size(
                p, root, _COMMANDMD_LINES_MED, _COMMANDMD_LINES_HIGH,
                kind="command-md",
                hint="slash-command body is appended to user prompt — trim preamble",
            ))

    # Hook script heredocs
    hooks = root / "hooks" / "claude"
    if hooks.is_dir():
        for p in sorted(hooks.glob("*.sh")):
            findings.extend(_scan_hook_heredoc(p, root))

    # Sort: severity desc, then "waste score" desc (tokens × (100-quality))
    # so high-volume low-quality bloat surfaces first.
    sev_rank = {"high": 0, "medium": 1, "low": 2}
    def _waste(f: dict) -> int:
        q = f.get("quality", 50)
        return f["tokens"] * (100 - q)
    findings.sort(key=lambda f: (sev_rank.get(f["severity"], 9), -_waste(f)))
    return findings


# ── Cache ────────────────────────────────────────────────────────────

def _cache_path() -> Path:
    env = os.environ.get("KAIZEN_DIR")
    base = Path(os.path.expandvars(env)).expanduser() if env \
        else Path.home() / ".claude" / ".kaizen"
    return base / "token-bloat-findings.json"


def _cache_ttl_seconds() -> int:
    hours = _envint("KAIZEN_TOKEN_BLOAT_TTL_HOURS", 6)
    return hours * 3600


def _cache_fresh() -> bool:
    p = _cache_path()
    if not p.is_file():
        return False
    age = _dt.datetime.now().timestamp() - p.stat().st_mtime
    return age < _cache_ttl_seconds()


def _write_cache(findings: list[dict]) -> None:
    p = _cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scanned_at": _dt.datetime.now(_dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "total":      len(findings),
        "high":       sum(1 for f in findings if f["severity"] == "high"),
        "medium":     sum(1 for f in findings if f["severity"] == "medium"),
        "findings":   findings,
    }
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_cache() -> dict | None:
    p = _cache_path()
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ── Output formatters ────────────────────────────────────────────────

def _print_text(findings: list[dict]) -> None:
    if not findings:
        print("kaizen-token-bloat: clean (no findings)")
        return
    h = sum(1 for f in findings if f["severity"] == "high")
    m = sum(1 for f in findings if f["severity"] == "medium")
    print(f"kaizen-token-bloat: {len(findings)} finding(s) — {h} high, {m} medium")
    for f in findings:
        mark = "▲" if f["severity"] == "high" else "△"
        q = f.get("quality")
        q_str = f"q={q:>3d}" if isinstance(q, int) else "q=  ?"
        print(f"  {mark} [{f['severity']:6s}] {f['kind']:14s} "
              f"{f['path']}::{f['field']}  "
              f"{f['lines']:>4d} ln (~{f['tokens']:>5d} tok)  "
              f"{q_str}  {f.get('quality_hint', '')}")


def _total_waste(findings: list[dict]) -> int:
    """Sum of estimated wasted tokens — Σ tokens × (100 - quality) / 100.
    A 1000-token finding at q=80 contributes 200 wasted tokens."""
    total = 0
    for f in findings:
        q = f.get("quality", 50)
        total += f.get("tokens", 0) * (100 - q) // 100
    return total


def _worst_quality(findings: list[dict]) -> dict | None:
    """Finding with the largest per-item waste (tokens × (100 - quality))."""
    if not findings:
        return None
    return max(findings,
                key=lambda f: f.get("tokens", 0) * (100 - f.get("quality", 50)))


def _surface_line(cache: dict | None) -> str:
    """One-line SessionStart-injection summary. Empty when nothing to say.

    Notice-trigger: only surfaces when estimated total waste exceeds
    KAIZEN_BLOAT_NOTICE_THRESHOLD (default 1000 tokens). Below that, the
    findings are background noise; we don't burn agent context on them."""
    if not cache or cache.get("total", 0) == 0:
        return ""
    findings = cache.get("findings", [])
    waste = _total_waste(findings)
    threshold = _envint("KAIZEN_BLOAT_NOTICE_THRESHOLD", 1000)
    if waste < threshold:
        return ""
    h = cache.get("high", 0)
    m = cache.get("medium", 0)
    worst = _worst_quality(findings)
    parts = [f"kaizen-token-bloat: ~{waste} wasted tok across "
             f"{h} high + {m} medium findings"]
    if worst:
        parts.append(
            f"worst: {worst['path']}::{worst['field']} "
            f"(q={worst.get('quality', '?')}, ~{worst['tokens']} tok)"
        )
    parts.append("run `kaizen-token-bloat report` for the full list")
    return " — ".join(parts)


# ── CLI ──────────────────────────────────────────────────────────────

def _cmd_scan(args) -> int:
    findings = scan_all()
    if args.cache:
        _write_cache(findings)
    if args.json:
        print(json.dumps({"findings": findings,
                            "high":     sum(1 for f in findings if f["severity"] == "high"),
                            "medium":   sum(1 for f in findings if f["severity"] == "medium"),
                            "total":    len(findings)}, indent=2))
    else:
        _print_text(findings)
    return 0


def _cmd_report(args) -> int:
    cache = _read_cache()
    if cache is None:
        sys.stderr.write("[kaizen-token-bloat] no cache — run `scan --cache` first\n")
        return 1
    if args.json:
        print(json.dumps(cache, indent=2))
    else:
        _print_text(cache.get("findings", []))
        print(f"\n(cache scanned_at: {cache.get('scanned_at')})")
    return 0


def _cmd_surface(args) -> int:
    """One-line summary for SessionStart injection. Empty stdout when
    cache is missing, stale, or has no findings."""
    if not _cache_fresh():
        return 0
    cache = _read_cache()
    line = _surface_line(cache)
    if line:
        print(line)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kaizen-token-bloat",
                                  description="Scan everything Claude sees for token bloat.")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("scan", help="full scan")
    ps.add_argument("--json", action="store_true")
    ps.add_argument("--cache", action="store_true",
                     help="write findings to cache file for SessionStart surface")
    ps.set_defaults(func=_cmd_scan)

    pr = sub.add_parser("report", help="print last cached findings")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=_cmd_report)

    psf = sub.add_parser("surface", help="SessionStart one-line summary")
    psf.set_defaults(func=_cmd_surface)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
