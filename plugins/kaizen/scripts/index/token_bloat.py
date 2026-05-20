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
# MIGRATION BRIDGE — cross-cluster sibs still at legacy or shimmed there.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

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
    return _SCRIPT_DIR.parents[1]  # scripts/index/ → plugins/kaizen/

# ── DXM fire-frequency integration ───────────────────────────────────

def _dxm_dir() -> Path:
    env = os.environ.get("KAIZEN_DXM_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path.home() / ".claude" / ".kaizen" / "dxm"

def count_dxm_fires(evt_type: str) -> int:
    """Total occurrences of evt_type across ALL dxm event files (lifetime).
    Returns 0 when dxm dir missing. Fast — single grep over jsonl."""
    d = _dxm_dir()
    if not d.is_dir():
        return 0
    needle = f'"evt_type":"{evt_type}"'
    total = 0
    for p in d.glob("events-*.jsonl"):
        try:
            with p.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if needle in line:
                        total += 1
        except OSError:
            continue
    return total

# Maps a finding's path/kind to the lifecycle evt_type whose count
# approximates how often that template gets injected into agent context.
# Heuristic: hook scripts fire on their named lifecycle event; yaml
# templates fire when their owning hook fires; SKILL.md / agents /
# command bodies fire when explicitly loaded (PreToolUse: Skill / Task).
_LIFECYCLE_BY_PREFIX = (
    ("hooks/claude/session-start-",   "SessionStart"),
    ("hooks/claude/sessionend-",      "SessionEnd"),
    ("hooks/claude/session-intake",   "SessionStart"),
    ("hooks/claude/pretooluse-",      "PreToolUse"),
    ("hooks/claude/posttooluse-",     "PostToolUse"),
    ("hooks/claude/userprompt-",      "UserPromptSubmit"),
    ("hooks/claude/stop-",            "Stop"),
    ("hooks/claude/subagentstop-",    "SubagentStop"),
    ("hooks/claude/precompact",       "PreCompact"),
)

# Cache fire counts per-process — single dxm walk per scan.
_FIRE_CACHE: dict[str, int] = {}

def _fires_for(evt_type: str) -> int:
    if evt_type not in _FIRE_CACHE:
        _FIRE_CACHE[evt_type] = count_dxm_fires(evt_type)
    return _FIRE_CACHE[evt_type]

def estimate_fire_count(finding: dict) -> int:
    """Approximate lifetime fire count for a finding. Returns 0 when
    no lifecycle mapping fits (e.g. SKILL.md fires on Skill-load, hard
    to count without parsing PreToolUse tool_name + tool_input)."""
    path = finding.get("path", "")
    # Hook + intake yaml share lifecycle event with the hook
    for prefix, evt in _LIFECYCLE_BY_PREFIX:
        if path.startswith(prefix):
            return _fires_for(evt)
    # YAML auto-handoff templates fire on Stop. Post-merger the auto-*
    # yamls live at schemas/handoff/auto-*.yaml (was schemas/auto-handoff/).
    if (("auto-handoff" in path or "/handoff/auto-" in path)
            and finding.get("kind") == "yaml-template"):
        return _fires_for("Stop")
    # SKILL.md / agents / commands — count handled separately
    # (would need PreToolUse Skill / Task payload inspection)
    return 0

# ── Sensitivity tier (LLMLingua-inspired) ────────────────────────────
#
# LLMLingua splits prompt into instruction/question/context with
# decreasing compression sensitivity. Maps to our findings:
#   instruction → hook templates / agent definitions (drive behavior;
#                                                       compress with care)
#   context     → SKILL.md bodies / references (background knowledge;
#                                                  compress aggressively)
#   system      → frontmatter descriptions (routing surface;
#                                              tiny, compress only if noisy)

def sensitivity_tier(finding: dict) -> str:
    kind = finding.get("kind", "")
    path = finding.get("path", "")
    if kind in ("yaml-template", "hook-heredoc"):
        return "instruction"
    if kind == "agent-md":
        return "instruction"
    if kind == "frontmatter-desc":
        return "system"
    if kind == "command-md":
        return "instruction"  # appended to user prompt
    return "context"           # SKILL.md, references, default

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
        key_line = text[:m.start()].count("\n") + 1  # 1-indexed
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
                "start_line":   key_line,
                "end_line":     key_line + len(lines),
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
        "start_line":   1,
        "end_line":     line_count,
        "tokens":       estimate_tokens(text),
        "quality":      q,
        "quality_hint": q_hint,
        "hint":         hint,
    }]

_HOOK_HEREDOC_RE = re.compile(
    r"""body\s*=\s*['"]['"]['"]([\s\S]*?)['"]['"]['"]""",
)

_AGENT_MD_LINES_HIGH    = _envint("KAIZEN_BLOAT_AGENT_LINES_HIGH",   400)
_AGENT_MD_LINES_MED     = _envint("KAIZEN_BLOAT_AGENT_LINES_MED",    200)
_FRONTMATTER_DESC_HIGH  = _envint("KAIZEN_BLOAT_DESC_CHARS_HIGH",     800)
_FRONTMATTER_DESC_MED   = _envint("KAIZEN_BLOAT_DESC_CHARS_MED",      400)

def _scan_agent_md(path: Path, root: Path) -> list[dict]:
    """Subagent definitions — loaded in full when the agent is dispatched.
    Larger ones = more context per Agent() call."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    line_count = text.count("\n") + 1
    if line_count < _AGENT_MD_LINES_MED:
        return []
    sev = "high" if line_count >= _AGENT_MD_LINES_HIGH else "medium"
    q, q_hint = quality_score(text)
    return [{
        "severity":     sev,
        "kind":         "agent-md",
        "path":         str(path.relative_to(root)),
        "field":        "(body)",
        "lines":        line_count,
        "start_line":   1,
        "end_line":     line_count,
        "tokens":       estimate_tokens(text),
        "quality":      q,
        "quality_hint": q_hint,
        "hint":         "agent body loads in full per Agent() dispatch — trim or split into helper agents",
    }]

# Frontmatter `description:` extractor. Single-line OR YAML block scalar.
_FRONTMATTER_RE = re.compile(
    r"^---\n(.*?)\n---", re.DOTALL,
)
_DESC_RE = re.compile(
    r"^description:\s*(.+?)$", re.MULTILINE,
)

def _scan_frontmatter_desc(path: Path, root: Path) -> list[dict]:
    """SKILL.md `description:` fields — loaded into the skills catalog
    at EVERY SessionStart. Even small bloat here is amortised heavily."""
    findings: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return findings
    fm = _FRONTMATTER_RE.match(text)
    if not fm:
        return findings
    m = _DESC_RE.search(fm.group(1))
    if not m:
        return findings
    desc = m.group(1).strip().strip('"\'')
    char_count = len(desc)
    if char_count < _FRONTMATTER_DESC_MED:
        return findings
    sev = "high" if char_count >= _FRONTMATTER_DESC_HIGH else "medium"
    q, q_hint = quality_score(desc)
    # Frontmatter sits at lines 1..frontmatter_end; description is one of
    # its keys. Approximate the description's own line range.
    desc_start = fm.group(1)[:m.start()].count("\n") + 2  # +1 for `---`, +1 for 1-index
    findings.append({
        "severity":     sev,
        "kind":         "frontmatter-desc",
        "path":         str(path.relative_to(root)),
        "field":        "description",
        "lines":        desc.count("\n") + 1,
        "start_line":   desc_start,
        "end_line":     desc_start + desc.count("\n"),
        "tokens":       estimate_tokens(desc),
        "quality":      q,
        "quality_hint": q_hint,
        "hint":         "description loads at EVERY SessionStart — keep <400 chars; only quoted trigger phrases earn space",
    })
    return findings

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
            start_line = text[:m.start()].count("\n") + 1
            findings.append({
                "severity":     sev,
                "kind":         "hook-heredoc",
                "path":         str(path.relative_to(root)),
                "field":        "body=''' ... '''",
                "lines":        line_count,
                "start_line":   start_line,
                "end_line":     start_line + line_count - 1,
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

    # YAML reason_template blocks (post-consolidation: schemas/<X>/*.yaml)
    for p in (root / "schemas").rglob("*.yaml"):
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

    # Agent definitions (loaded per Agent() dispatch)
    agents = root / "agents"
    if agents.is_dir():
        for p in sorted(agents.glob("*.md")):
            findings.extend(_scan_agent_md(p, root))

    # SKILL.md frontmatter descriptions (loaded every SessionStart)
    for p in (root / "skills").rglob("SKILL.md"):
        findings.extend(_scan_frontmatter_desc(p, root))

    # Augment each finding with fire-frequency + sensitivity tier +
    # cumulative cost (tokens × fires). Reset DXM cache per scan.
    _FIRE_CACHE.clear()
    for f in findings:
        fires = estimate_fire_count(f)
        f["fire_count"]         = fires
        # Cumulative = base tokens × (1 + observed fires). The +1 is
        # the per-scan baseline; fires multiply the impact for hooks
        # that fire many times per session.
        f["cumulative_tokens"]  = f["tokens"] * max(1, fires)
        f["sensitivity"]        = sensitivity_tier(f)

    # Sort: severity desc, then cumulative tokens desc (real-world cost),
    # then per-finding waste (tokens × (100-quality)) as tiebreaker.
    sev_rank = {"high": 0, "medium": 1, "low": 2}
    def _waste(f: dict) -> int:
        q = f.get("quality", 50)
        return f["tokens"] * (100 - q)
    findings.sort(key=lambda f: (
        sev_rank.get(f["severity"], 9),
        -f.get("cumulative_tokens", f["tokens"]),
        -_waste(f),
    ))
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

def _kaizen_dir() -> Path:
    env = os.environ.get("KAIZEN_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path.home() / ".claude" / ".kaizen"

def _project_root() -> Path:
    """Walk up cwd to find the repo root (.git or .kaizen marker).
    Falls back to cwd when neither marker exists (works under bare dirs)."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".kaizen").is_dir() or (parent / ".git").is_dir():
            return parent
    return cwd

def _project_slug() -> str:
    """`/home/u/repo` → `-home-u-repo` — same shape as CC's
    `~/.claude/projects/<slug>/`. Reused from _session_jsonl when
    available; otherwise a self-contained re-impl."""
    root = _project_root()
    try:
        sys.path.insert(0, str(_SCRIPT_DIR))
        import _session_jsonl as _sj
        return _sj.cwd_to_slug(root)
    except ImportError:
        return str(root.resolve()).replace("/", "-")

def _bloat_dir() -> Path:
    """Per-project token-bloat dir under the user-global $KAIZEN_DIR.

    Layout (project-aware):
      $KAIZEN_DIR/token-bloat/<project-slug>/session.md
      $KAIZEN_DIR/token-bloat/<project-slug>/history.jsonl

    Survives `git clean` / repo wipe / fresh clone. Multiple repos
    coexist without clobbering."""
    return _kaizen_dir() / "token-bloat" / _project_slug()

def _session_state_path() -> Path:
    """Per-project state file. Override via KAIZEN_BLOAT_SESSION_FILE
    (full path; useful for tests / one-off redirection)."""
    env = os.environ.get("KAIZEN_BLOAT_SESSION_FILE")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return _bloat_dir() / "session.md"

def _session_history_path() -> Path:
    """Continuous JSONL history. Sibling of the snapshot.
    Override via KAIZEN_BLOAT_HISTORY_FILE (full path)."""
    env = os.environ.get("KAIZEN_BLOAT_HISTORY_FILE")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    # When KAIZEN_BLOAT_SESSION_FILE is set without a paired history env,
    # derive the history from the snapshot path (back-compat with tests).
    if os.environ.get("KAIZEN_BLOAT_SESSION_FILE"):
        return _session_state_path().with_suffix(".history.jsonl")
    return _bloat_dir() / "history.jsonl"

def _archive_dir() -> Path:
    """Where rendered .md snapshots get archived per scan. Sibling of
    the live snapshot. Override via KAIZEN_BLOAT_ARCHIVE_DIR."""
    env = os.environ.get("KAIZEN_BLOAT_ARCHIVE_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return _session_state_path().parent / "archive"

def _archive_path_for(scanned_at: str) -> Path:
    """Timestamped archive file. Filename matches the history JSONL
    entry's scanned_at field so they can be cross-referenced by grep."""
    safe = scanned_at.replace(":", "").replace("-", "").replace("Z", "Z")
    return _archive_dir() / f"{safe}.md"

def _uniq_archive_path(scanned_at: str) -> Path:
    """Collision-safe archive path. When two scans share a second,
    appends `-N` so neither overwrites the other.

    Without this, the second scan's atomic_write silently replaces
    the first archive — data loss. Returns the base path when free.
    """
    base = _archive_path_for(scanned_at)
    if not base.exists():
        return base
    stem = base.stem
    for n in range(1, 1000):
        cand = base.with_name(f"{stem}-{n}.md")
        if not cand.exists():
            return cand
    return base  # cap: 1000 archives/sec is absurd — fall back

def _history_max_mb() -> int:
    return _envint("KAIZEN_BLOAT_HISTORY_MAX_MB", 5)

def _rotate_history_if_huge(p: Path) -> None:
    """Rotate the history file when it exceeds the cap — mirrors the
    pattern in trace.py. Rotation is best-effort; never raises."""
    try:
        if not p.exists():
            return
        size_mb = p.stat().st_size / (1024 * 1024)
        if size_mb < _history_max_mb():
            return
        ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        rotated = p.parent / f"{p.stem}.{ts}.jsonl"
        p.rename(rotated)
    except OSError:
        pass

def _render_split_plans_section(plans: list[dict]) -> str:
    """Render the auto-generated split-plan summaries as an appendix
    on the session.md snapshot. Plans with 0 extract candidates are
    listed as one-liners (silent skip); plans with candidates expand."""
    if not plans:
        return ""
    actionable = [p for p in plans if p.get("estimated_tokens_saved", 0) > 0]
    if not actionable and not plans:
        return ""
    lines = [
        "",
        "## Split plans (advisory — apply via manual section extraction)",
        "",
    ]
    for plan in plans:
        skill = plan.get("skill", "?")
        ln = plan.get("current_lines", 0)
        tok = plan.get("current_tokens", 0)
        saved = plan.get("estimated_tokens_saved", 0)
        head = (f"split-plan: {skill} ({ln} ln, ~{tok} tok) — "
                f"~{saved} tok savings if extracted")
        lines.append(head)
        for c in plan.get("candidates", []):
            if c.get("verdict") != "extract":
                continue
            lines.append(
                f"  → L{c['start']:>4d}-{c['end']:<4d} "
                f"[{c['kind']:18s}] ~{c['tokens']:>5d}tok "
                f"{c['section']}  → {c['extract_to']}"
            )
        lines.append("")
    return "\n".join(lines)

def _generate_split_plans_for_oversized(root: Path | None = None) -> list[dict]:
    """Auto-run split-plan against every SKILL.md > medium threshold.
    Returns the same list shape `_cmd_split_plan` emits with --json."""
    root = root or _plugin_root()
    plans = []
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        return plans
    for p in sorted(skills_dir.iterdir()):
        if not p.is_dir():
            continue
        skill_md = p / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            if skill_md.read_text(encoding="utf-8").count("\n") + 1 >= _SKILLMD_LINES_MED:
                plans.append(build_split_plan(p.name, root=root))
        except OSError:
            continue
    return plans

def _render_snapshot(findings: list[dict], scanned_at: str,
                       split_plans: list[dict] | None = None) -> str:
    """Pure: render the markdown snapshot from findings + timestamp.
    Used by both _write_session_state and the restore path."""
    waste = _total_waste(findings)
    cumul = sum(f.get("cumulative_tokens", f.get("tokens", 0)) for f in findings)
    h = sum(1 for f in findings if f["severity"] == "high")
    m = sum(1 for f in findings if f["severity"] == "medium")
    lines = [
        f"# kaizen token-bloat — session state",
        f"# scanned: {scanned_at}",
        f"# findings: {len(findings)} ({h} high, {m} medium) | waste: ~{waste} tok | cumulative: ~{cumul} tok",
        f"# format: `path:start-end` <sev>|<sens> q=<q> ~<tok>tok ×<fires>→<cumul>",
        f"",
    ]
    for f in findings:
        path = f.get("path", "")
        s = f.get("start_line", 1)
        e = f.get("end_line", s)
        sev = f.get("severity", "?")[:1].upper()  # H / M
        sens = (f.get("sensitivity", "context") or "context")[:4]
        q = f.get("quality", "?")
        tok = f.get("tokens", 0)
        fires = f.get("fire_count", 0)
        cumul_i = f.get("cumulative_tokens", tok)
        fire_str = f"×{fires}" if fires else "×1"
        lines.append(
            f"`{path}:{s}-{e}` {sev}|{sens} q={q} ~{tok}tok {fire_str}→~{cumul_i}"
        )
    body = "\n".join(lines) + "\n"
    if split_plans:
        body += _render_split_plans_section(split_plans)
    # Footer link to the archived twin of this snapshot. The reviewer
    # can `cd archive/ && ls -t` to walk history; each archive is the
    # rendered snapshot at that scanned_at, linkable to history.jsonl
    # via the matching timestamp.
    body += (
        f"\n---\n"
        f"# archived: archive/{_archive_path_for(scanned_at).name}\n"
        f"# history:  history.jsonl  (grep '{scanned_at}' for this scan)\n"
    )
    return body

def _write_session_state(findings: list[dict]) -> None:
    """Atomic snapshot + continuous JSONL history.

    Survival guarantees:
      - snapshot via _atomic.atomic_write (tempfile + os.replace).
        Power-loss mid-write leaves the prior snapshot intact.
      - history appended via _atomic.atomic_append_line. Either fully
        appended or fully not — never a half line.
      - history rotated when > KAIZEN_BLOAT_HISTORY_MAX_MB (default 5).
      - all errors swallowed; the scan never raises from persistence.

    Either file alone is recoverable: snapshot regenerable from latest
    history entry via `kaizen-token-bloat restore`.
    """
    snap = _session_state_path()
    hist = _session_history_path()
    scanned_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Lazy-import _atomic so token_bloat.py stays standalone-runnable
    # when _atomic.py is somehow missing — fall back to direct write.
    try:
        sys.path.insert(0, str(_SCRIPT_DIR))
        import _atomic
        atomic_write = _atomic.atomic_write
        atomic_append_line = _atomic.atomic_append_line
    except ImportError:
        def atomic_write(p, content):
            Path(p).parent.mkdir(parents=True, exist_ok=True)
            Path(p).write_text(content, encoding="utf-8")

        def atomic_append_line(p, line):
            Path(p).parent.mkdir(parents=True, exist_ok=True)
            with Path(p).open("a", encoding="utf-8") as f:
                f.write(line + ("" if line.endswith("\n") else "\n"))

    # Auto-generate split plans for every oversized SKILL.md so the
    # session state surfaces them alongside findings — no separate
    # invocation needed. Best-effort; never raises.
    split_plans: list[dict] = []
    try:
        split_plans = _generate_split_plans_for_oversized()
    except Exception:
        pass

    # 1) Snapshot — atomic replace (includes split-plans + archive link)
    rendered = _render_snapshot(findings, scanned_at, split_plans)
    try:
        atomic_write(snap, rendered)
    except OSError:
        pass  # never raise from persistence

    # 1b) Archive — atomic timestamped copy of THIS scan's rendered .md.
    # Lets the reviewer compare snapshots across scans without
    # re-rendering from history. Cross-referenced to history.jsonl by
    # matching scanned_at timestamp.
    try:
        atomic_write(_uniq_archive_path(scanned_at), rendered)
    except OSError:
        pass

    # 2) History — append one JSONL line, rotate if huge
    try:
        _rotate_history_if_huge(hist)
        atomic_append_line(hist, json.dumps({
            "scanned_at":        scanned_at,
            "total":             len(findings),
            "high":              sum(1 for f in findings if f["severity"] == "high"),
            "medium":            sum(1 for f in findings if f["severity"] == "medium"),
            "waste_tokens":      _total_waste(findings),
            "cumulative_tokens": sum(f.get("cumulative_tokens", f.get("tokens", 0)) for f in findings),
            "findings":          findings,
            "split_plans":       split_plans,
        }, default=str))
    except OSError:
        pass

def validate_finding(finding: dict, root: Path | None = None) -> str:
    """Cross-reference a finding against the live filesystem. Returns one of:

      "active"   — file exists, range still in file, content still at or
                   above the original size (still bloated)
      "missing"  — file doesn't exist anymore
      "moved"    — file exists but end_line now exceeds file's line count
      "resolved" — file + range still valid, but the body shrank below
                   half its recorded line count (someone trimmed it)
      "unknown"  — finding lacks the fields we need

    Pure function: no side effects, no writes.
    """
    root = root or _plugin_root()
    path_rel = finding.get("path")
    if not path_rel:
        return "unknown"
    p = root / path_rel
    if not p.is_file():
        return "missing"
    start = finding.get("start_line")
    end = finding.get("end_line")
    if start is None or end is None:
        return "unknown"
    try:
        actual_lines = p.read_text(encoding="utf-8", errors="ignore").count("\n") + 1
    except OSError:
        return "missing"
    if end > actual_lines:
        return "moved"
    recorded_lines = max(1, int(finding.get("lines", end - start + 1)))
    # Heuristic: if the file shrank to less than half the recorded size,
    # the original bloat is almost certainly gone (someone trimmed it).
    if actual_lines * 2 < recorded_lines:
        return "resolved"
    return "active"

def _validate_and_partition(findings: list[dict], root: Path | None = None) -> dict:
    """Split findings into {active, missing, moved, resolved, unknown}."""
    root = root or _plugin_root()
    buckets: dict[str, list[dict]] = {
        "active": [], "missing": [], "moved": [], "resolved": [], "unknown": [],
    }
    for f in findings:
        status = validate_finding(f, root)
        buckets.setdefault(status, []).append(f)
    return buckets

_CITATION_RE = re.compile(r"^([^:]+):(\d+)(?:-(\d+))?$")

def smart_read(citation: str, root: Path | None = None,
                 context_lines: int = 0) -> dict:
    """Read the cited line range from a source file. Returns:
      {ok, path, start, end, content, error?}

    citation: 'plugins/kaizen/foo.py:42-58' or 'foo.md:10'.
    context_lines: pad N lines above + below the range (default 0)."""
    m = _CITATION_RE.match(citation.strip("`"))
    if not m:
        return {"ok": False, "error": f"bad citation: {citation!r}",
                 "path": citation, "start": 0, "end": 0, "content": ""}
    rel, start_s, end_s = m.group(1), m.group(2), m.group(3)
    start = int(start_s)
    end = int(end_s) if end_s else start
    base = root or _plugin_root()
    p = base / rel if not Path(rel).is_absolute() else Path(rel)
    if not p.is_file():
        # Try cwd-relative as fallback
        p2 = Path(rel)
        if p2.is_file():
            p = p2
        else:
            return {"ok": False, "error": f"not found: {p}",
                     "path": rel, "start": start, "end": end, "content": ""}
    try:
        all_lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError as e:
        return {"ok": False, "error": str(e), "path": rel,
                 "start": start, "end": end, "content": ""}
    pad = max(0, context_lines)
    lo = max(1, start - pad)
    hi = min(len(all_lines), end + pad)
    snippet = "\n".join(
        f"{i:5d}: {all_lines[i - 1]}"
        for i in range(lo, hi + 1)
    )
    return {
        "ok":      True,
        "path":    str(p),
        "start":   start,
        "end":     end,
        "padded_start": lo,
        "padded_end":   hi,
        "content": snippet,
    }

def _list_archives() -> list[dict]:
    """Sorted (newest first) list of archived snapshots with metadata."""
    d = _archive_dir()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.md"), reverse=True):
        try:
            st = p.stat()
            out.append({
                "path":      str(p),
                "name":      p.name,
                "size":      st.st_size,
                "mtime":     st.st_mtime,
            })
        except OSError:
            continue
    return out

def _cmd_read(args) -> int:
    """Smart line-read: emit the cited `path:start-end` snippet."""
    out = smart_read(args.citation, context_lines=args.context)
    if args.json:
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 1
    if not out.get("ok"):
        sys.stderr.write(f"[kaizen-token-bloat read] {out.get('error')}\n")
        return 1
    print(f"# {out['path']}:{out['start']}-{out['end']}")
    print(out["content"])
    return 0

def _cmd_archives(args) -> int:
    archives = _list_archives()
    if args.json:
        print(json.dumps(archives, indent=2))
        return 0
    if not archives:
        print("kaizen-token-bloat archives: (empty)")
        return 0
    print(f"kaizen-token-bloat archives ({len(archives)}):")
    for a in archives:
        kb = a["size"] // 1024
        print(f"  {a['name']:30s} {kb:>4d}KB  {a['path']}")
    return 0

def _restore_snapshot_from_history() -> bool:
    """Regenerate the .md snapshot from the LAST entry in the history
    JSONL. Returns True on success, False when no history available."""
    hist = _session_history_path()
    if not hist.is_file():
        return False
    last_obj = None
    try:
        with hist.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    last_obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return False
    if not last_obj:
        return False
    snap = _session_state_path()
    findings = last_obj.get("findings") or []
    split_plans = last_obj.get("split_plans") or []
    scanned_at = last_obj.get("scanned_at") or "unknown"
    rendered = _render_snapshot(findings, scanned_at, split_plans)
    try:
        sys.path.insert(0, str(_SCRIPT_DIR))
        import _atomic
        _atomic.atomic_write(snap, rendered)
    except (OSError, ImportError):
        try:
            snap.parent.mkdir(parents=True, exist_ok=True)
            snap.write_text(rendered, encoding="utf-8")
        except OSError:
            return False
    return True

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
        fires = f.get("fire_count", 0)
        cumul = f.get("cumulative_tokens", f["tokens"])
        sens = (f.get("sensitivity", "context") or "context")[:4]
        fire_str = f"×{fires}" if fires else "×?"
        print(f"  {mark} [{f['severity']:6s}] {f['kind']:16s} "
              f"{f['path']}::{f['field']}  "
              f"{f['lines']:>4d} ln (~{f['tokens']:>5d} tok)  "
              f"{q_str} {sens:4s} {fire_str:>5s}→~{cumul:>7d} cumul")

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
    findings are background noise; we don't burn agent context on them.

    Surfaces CUMULATIVE cost (tokens × dxm fire-count) as the primary
    metric — a 200-token template fired 50× costs more than a one-off
    10k-token doc."""
    if not cache or cache.get("total", 0) == 0:
        return ""
    findings = cache.get("findings", [])
    waste = _total_waste(findings)
    threshold = _envint("KAIZEN_BLOAT_NOTICE_THRESHOLD", 1000)
    if waste < threshold:
        return ""
    h = cache.get("high", 0)
    m = cache.get("medium", 0)
    # Top by cumulative cost (real impact)
    top = max(findings,
               key=lambda f: f.get("cumulative_tokens", f.get("tokens", 0))) \
          if findings else None
    parts = [f"kaizen-token-bloat: ~{waste} wasted tok "
             f"({h} high + {m} medium)"]
    if top:
        fires = top.get("fire_count", 0)
        cumul = top.get("cumulative_tokens", top["tokens"])
        sens = top.get("sensitivity", "context")
        fire_note = f"×{fires} fires" if fires else "1-shot"
        parts.append(
            f"top-cost: {top['path']}::{top['field']} "
            f"({sens}, ~{top['tokens']} tok {fire_note} "
            f"= ~{cumul} cumul, q={top.get('quality', '?')})"
        )
    parts.append("run `kaizen-token-bloat report` for the full list")
    return " — ".join(parts)

# ── CLI ──────────────────────────────────────────────────────────────

def _emit_trace(findings: list[dict]) -> None:
    """Emit one trace event summarising the scan. Best-effort — trace
    must never break the scanner."""
    try:
        sys.path.insert(0, str(_SCRIPT_DIR))
        import trace as _trace
        waste = _total_waste(findings)
        cumul = sum(f.get("cumulative_tokens", f.get("tokens", 0))
                     for f in findings)
        _trace.append_event({
            "ts":         _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "evt_type":   "token_bloat.scanned",
            "tool_name":  "kaizen-token-bloat",
            "payload":    {
                "total":             len(findings),
                "high":              sum(1 for f in findings if f["severity"] == "high"),
                "medium":            sum(1 for f in findings if f["severity"] == "medium"),
                "waste_tokens":      waste,
                "cumulative_tokens": cumul,
            },
        })
    except Exception:
        pass

def _read_last_history_findings() -> list[dict]:
    """Pull findings list from the most recent history JSONL entry."""
    hist = _session_history_path()
    if not hist.is_file():
        return []
    last_obj = None
    try:
        with hist.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    last_obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return (last_obj or {}).get("findings") or []

# ── Split-plan: rubric-driven section classifier ────────────────────

def _load_split_rubric() -> dict:
    """Load the section-split rubric. Stdlib YAML-subset parser; falls
    back to PyYAML when available for safety on edge cases."""
    # scripts/index/ → plugins/kaizen/ + schemas/token-bloat/
    p = (_SCRIPT_DIR.parents[1] / "schemas" / "token-bloat" /
         "split-rubric.yaml")
    if not p.is_file():
        return {"version": 1, "rules": []}
    text = p.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {"version": 1, "rules": []}
    except ImportError:
        pass
    # Minimal stdlib parser for the rubric's shape:
    #   version: 1
    #   rules:
    #     - kind: theory
    #       heading_contains: "THEORY"
    #       verdict: extract
    #       ...
    rules: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        if line.lstrip().startswith("- "):
            if cur is not None:
                rules.append(cur)
            cur = {}
            rest = line.split("- ", 1)[1]
            if ":" in rest:
                k, v = rest.split(":", 1)
                cur[k.strip()] = v.strip().strip('"\'')
            continue
        if cur is not None and ":" in line and line.startswith(" "):
            k, v = line.split(":", 1)
            v = v.strip().strip('"\'')
            if v.isdigit():
                v = int(v)
            cur[k.strip()] = v
    if cur is not None:
        rules.append(cur)
    return {"version": 1, "rules": rules}

def _parse_skill_sections(path: Path) -> list[dict]:
    """Walk a markdown file; return [{heading, level, start, end, lines, body}].
    Heading levels 1-3. Frontmatter stripped."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    lines = text.splitlines()
    # Strip frontmatter
    if lines and lines[0].strip() == "---":
        try:
            close = next(i for i, ln in enumerate(lines[1:], start=1)
                          if ln.strip() == "---")
            lines = lines[close + 1:]
            body_offset = close + 1
        except StopIteration:
            body_offset = 0
    else:
        body_offset = 0

    sections: list[dict] = []
    cur: dict | None = None
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{1,3})\s+(.+?)\s*$", ln)
        if m:
            if cur is not None:
                cur["end"] = i + body_offset  # 0-indexed → adjust later
                cur["lines"] = cur["end"] - cur["start"] + 1
                cur["body"] = "\n".join(
                    lines[cur["start"] - body_offset - 1:cur["end"] - body_offset])
                sections.append(cur)
            cur = {
                "heading": m.group(2),
                "level":   len(m.group(1)),
                "start":   i + body_offset + 1,  # 1-indexed
            }
    if cur is not None:
        cur["end"] = len(lines) + body_offset
        cur["lines"] = cur["end"] - cur["start"] + 1
        cur["body"] = "\n".join(lines[cur["start"] - body_offset - 1:])
        sections.append(cur)
    return sections

def _classify_section(section: dict, rubric: dict) -> dict:
    """First-match-wins rule application. Returns the section dict
    augmented with kind / verdict / extract_to / reason."""
    heading = section.get("heading", "")
    line_count = section.get("lines", 0)
    for rule in rubric.get("rules", []):
        if "heading_contains" in rule:
            if rule["heading_contains"].lower() not in heading.lower():
                continue
        if "heading_regex" in rule:
            if not re.search(rule["heading_regex"], heading):
                continue
        if "line_count_min" in rule:
            if line_count < int(rule["line_count_min"]):
                continue
        return {
            **section,
            "kind":       rule.get("kind", "unknown"),
            "verdict":    rule.get("verdict", "keep-inline"),
            "extract_to": rule.get("extract_to", ""),
            "reason":     rule.get("reason", ""),
            "tokens":     estimate_tokens(section.get("body", "")),
        }
    return {
        **section,
        "kind":       "unknown",
        "verdict":    "keep-inline",
        "extract_to": "",
        "reason":     "no rule matched; default keep-inline",
        "tokens":     estimate_tokens(section.get("body", "")),
    }

def build_split_plan(skill: str, root: Path | None = None) -> dict:
    """Generate a split plan for `skills/<skill>/SKILL.md`. Returns a
    dict conforming to domain/schemas/split-plan.schema.json."""
    root = root or _plugin_root()
    skill_md = root / "skills" / skill / "SKILL.md"
    if not skill_md.is_file():
        return {"skill": skill, "error": "SKILL.md not found",
                 "current_lines": 0, "current_tokens": 0,
                 "candidates": [], "estimated_tokens_saved": 0}
    sections = _parse_skill_sections(skill_md)
    rubric = _load_split_rubric()
    classified = [_classify_section(s, rubric) for s in sections]
    candidates = []
    saved = 0
    for s in classified:
        cand = {
            "section":    s["heading"],
            "start":      s["start"],
            "end":        s["end"],
            "kind":       s["kind"],
            "extract_to": s["extract_to"],
            "tokens":     s["tokens"],
            "verdict":    s["verdict"],
            "reason":     s["reason"],
        }
        candidates.append(cand)
        if s["verdict"] == "extract":
            saved += s["tokens"]
    try:
        body = skill_md.read_text(encoding="utf-8")
        cur_lines = body.count("\n") + 1
        cur_tokens = estimate_tokens(body)
    except OSError:
        cur_lines = 0; cur_tokens = 0
    return {
        "skill":                  skill,
        "path":                   str(skill_md.relative_to(root)),
        "current_lines":          cur_lines,
        "current_tokens":         cur_tokens,
        "estimated_tokens_saved": saved,
        "candidates":             candidates,
    }

def _print_split_plan(plan: dict) -> None:
    print(f"split-plan: {plan['skill']} "
          f"({plan['current_lines']} ln, ~{plan['current_tokens']} tok) — "
          f"~{plan['estimated_tokens_saved']} tok savings if extracted")
    for c in plan["candidates"]:
        mark = "→" if c["verdict"] == "extract" else " "
        target = f"→ {c['extract_to']}" if c["extract_to"] else ""
        print(f"  {mark} L{c['start']:>4d}-{c['end']:<4d} "
              f"[{c['verdict']:11s}] {c['kind']:18s} "
              f"~{c['tokens']:>5d}tok  {c['section']}  {target}")

def _cmd_split_plan(args) -> int:
    """Emit a split plan for one skill (--skill) or all oversized skills."""
    if args.skill:
        plans = [build_split_plan(args.skill)]
    else:
        # Plan-all: every skill whose SKILL.md exceeds the medium threshold
        plans = []
        skills_dir = _plugin_root() / "skills"
        for p in sorted(skills_dir.iterdir()):
            if not p.is_dir():
                continue
            skill_md = p / "SKILL.md"
            if not skill_md.is_file():
                continue
            try:
                if skill_md.read_text().count("\n") + 1 >= _SKILLMD_LINES_MED:
                    plans.append(build_split_plan(p.name))
            except OSError:
                continue
    if args.json:
        print(json.dumps(plans if not args.skill else plans[0], indent=2))
    else:
        for plan in plans:
            _print_split_plan(plan)
            print()
    return 0

def _cmd_validate(args) -> int:
    """Validate the LATEST snapshot's findings against the live FS.

    With --prune: rewrite the snapshot to drop missing/resolved entries,
    keeping only those still active or moved (worth investigating).
    Records the prune in a sibling resolved.log for auditability."""
    prior = _read_last_history_findings()
    if not prior:
        sys.stderr.write("[kaizen-token-bloat] no history to validate\n")
        return 1
    buckets = _validate_and_partition(prior)
    summary = {k: len(v) for k, v in buckets.items()}
    if args.json:
        print(json.dumps({"summary": summary, "buckets": buckets},
                          default=str, indent=2))
    else:
        print(f"kaizen-token-bloat validate: "
              f"{summary['active']} active, {summary['missing']} missing, "
              f"{summary['moved']} moved, {summary['resolved']} resolved")
        for status in ("missing", "resolved", "moved"):
            for f in buckets[status]:
                print(f"  [{status:8s}] {f.get('path')}:"
                      f"{f.get('start_line')}-{f.get('end_line')}")
    if args.prune:
        keep = buckets["active"] + buckets["moved"]  # moved == still worth a look
        dropped = buckets["missing"] + buckets["resolved"]
        _write_session_state(keep)
        # Audit log for what was pruned. _atomic shim at legacy is on
        # sys.path via the MIGRATION BRIDGE at the top of this module.
        resolved_log = _session_state_path().parent / "resolved.log"
        try:
            import _atomic
            for f in dropped:
                _atomic.atomic_append_line(resolved_log, json.dumps({
                    "pruned_at":  _dt.datetime.now(_dt.timezone.utc).strftime(
                                      "%Y-%m-%dT%H:%M:%SZ"),
                    "status":     validate_finding(f),
                    "finding":    f,
                }, default=str))
        except (OSError, ImportError) as _e:
            sys.stderr.write(f"[token-bloat] resolved.log write skipped: {_e}\n")
        if not args.json:
            print(f"pruned {len(dropped)} stale entries → snapshot now "
                  f"contains {len(keep)} (audit: {resolved_log})")
    return 0

def _cmd_scan(args) -> int:
    findings = scan_all()
    if args.cache:
        # Self-cleaning: scan_all returns CURRENT bloat only, so the
        # new snapshot inherently drops resolved/missing entries from
        # the prior scan. The history JSONL keeps the full audit trail.
        _write_cache(findings)
        _write_session_state(findings)
        _emit_trace(findings)
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

    pss = sub.add_parser("session", help="print session-state file path")
    pss.set_defaults(func=lambda a: (print(_session_state_path()), 0)[1])

    phi = sub.add_parser("history", help="print history JSONL file path")
    phi.set_defaults(func=lambda a: (print(_session_history_path()), 0)[1])

    pard = sub.add_parser("archives",
                           help="list timestamped snapshot archives (newest first)")
    pard.add_argument("--json", action="store_true")
    pard.set_defaults(func=_cmd_archives)

    prd = sub.add_parser("read",
                          help="smart line-read: emit the cited `path:start-end` snippet")
    prd.add_argument("citation",
                      help="`path:start-end` (e.g. plugins/kaizen/foo.py:42-58)")
    prd.add_argument("--context", type=int, default=0,
                      help="pad N lines above + below (default 0)")
    prd.add_argument("--json", action="store_true")
    prd.set_defaults(func=_cmd_read)

    psp = sub.add_parser("split-plan",
                          help="emit a rubric-driven split plan for one skill (or all oversized)")
    psp.add_argument("--skill", default=None,
                      help="single skill (default: every SKILL.md over the medium threshold)")
    psp.add_argument("--json", action="store_true")
    psp.set_defaults(func=_cmd_split_plan)

    pv = sub.add_parser("validate",
                          help="cross-check last history's findings against the live FS")
    pv.add_argument("--json", action="store_true")
    pv.add_argument("--prune", action="store_true",
                     help="rewrite snapshot to drop missing/resolved entries")
    pv.set_defaults(func=_cmd_validate)

    prs = sub.add_parser("restore",
                          help="regenerate session-state .md from last history entry")
    prs.set_defaults(func=lambda a:
        (print(f"restored {_session_state_path()}"), 0)[1]
        if _restore_snapshot_from_history()
        else (sys.stderr.write("[kaizen-token-bloat] no history to restore from\n"), 1)[1])

    args = p.parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main())
