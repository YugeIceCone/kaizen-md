"""kaizen skill_suggest — match user prompt against SKILL.md
trigger phrases and suggest which skills to load.

How it works:

  1. Walks skills/*/SKILL.md (one level deep — vendored sub-skill
     dirs ignored). Extracts the frontmatter `name` + `description`.
  2. Parses double-quoted phrases out of the description (the
     canonical "Triggers on \"phrase1\", \"phrase2\", ..." pattern).
  3. For each skill, checks if any trigger phrase appears in the
     prompt (case-insensitive substring).
  4. Emits matches ranked by trigger-count (more matched phrases
     → higher confidence the skill is relevant).

Skills WITHOUT quoted triggers in their description are skipped —
the substring-on-prose approach is too noisy. This is precision-
over-recall by design.

Used by:
  - hooks/claude/userprompt-skill-suggest.sh (auto-suggest hook)
  - agents that want a programmatic "what skill matches this?" check

CLI:
    skill_suggest.py match --prompt "TEXT" [--json] [--max N]
    skill_suggest.py list                  # all skills with extracted triggers
    skill_suggest.py rebuild               # placeholder for future caching
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


# Frontmatter regex — handles ---/--- delimited YAML at top of file
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)

# Extract name field from frontmatter
_NAME_RE = re.compile(r"^name:\s*(\S+)", re.MULTILINE)

# Extract description field from frontmatter. Captures up to the
# next top-level key (`<word>:`) or end-of-frontmatter. Handles
# single-line + multi-line descriptions. Works when description is
# the last field (no following key) — that case is `\Z`.
_DESC_RE = re.compile(
    r"^description:[ \t]*(.+?)(?=\n[a-zA-Z_-]+:|\Z)",
    re.MULTILINE | re.DOTALL,
)

# Double-quoted phrase extractor. Captures everything between matched
# double quotes; ignores escaped quotes (rare in skill descriptions).
_QUOTED_RE = re.compile(r'"([^"]{3,80})"')


def _skills_root() -> Path:
    env = os.environ.get("KAIZEN_SKILL_SUGGEST_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve().parent
    # scripts/util/ → plugin_root/skills/
    return here.parent.parent / "skills"


def _iter_skill_dirs(root: Path):
    """Yield each skills/<name>/ dir. One level — sub-skills under
    skills/<x>/skills/ (vendored superpowers shape) are ignored to
    keep the index focused on top-level routing targets."""
    if not root.is_dir():
        return
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        if (d / "SKILL.md").is_file():
            yield d


def parse_skill(skill_dir: Path) -> dict | None:
    """Return {name, description, triggers[]} or None on parse failure."""
    skill_md = skill_dir / "SKILL.md"
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    fm = _FRONTMATTER_RE.match(text)
    if not fm:
        return None
    fm_body = fm.group(1)
    name_m = _NAME_RE.search(fm_body)
    name = name_m.group(1).strip() if name_m else skill_dir.name
    desc_m = _DESC_RE.search(fm_body)
    desc = desc_m.group(1).strip() if desc_m else ""
    # Extract quoted trigger phrases. Lowercase + strip for matching.
    triggers = [t.strip().lower() for t in _QUOTED_RE.findall(desc) if t.strip()]
    return {"name": name, "description": desc, "triggers": triggers,
             "dir": str(skill_dir)}


def index_all() -> list[dict]:
    """Walk skills/ and return parsed catalog. Skills with no quoted
    triggers are still in the list (so `list` can show them) but the
    matcher skips them."""
    out = []
    for d in _iter_skill_dirs(_skills_root()):
        s = parse_skill(d)
        if s is not None:
            out.append(s)
    return out


def match_prompt(prompt: str, *, max_results: int = 3) -> list[dict]:
    """Return skills whose triggers match the prompt, ranked by
    trigger hit count (more hits → higher relevance)."""
    if not prompt:
        return []
    p_lower = prompt.lower()
    hits: list[tuple[int, dict]] = []
    for skill in index_all():
        if not skill["triggers"]:
            continue
        matched = [t for t in skill["triggers"] if t in p_lower]
        if matched:
            hits.append((len(matched), {
                "name":          skill["name"],
                "matched":       matched,
                "trigger_count": len(skill["triggers"]),
                "match_count":   len(matched),
                "description":   skill["description"][:140],
            }))
    # Sort by match_count desc, then total triggers desc as tiebreak
    hits.sort(key=lambda x: (-x[0], -x[1]["trigger_count"]))
    return [h[1] for h in hits[:max_results]]


def _cmd_match(args) -> int:
    prompt = args.prompt or sys.stdin.read().strip()
    if not prompt:
        if args.json:
            print(json.dumps({"matches": []}))
        return 0
    matches = match_prompt(prompt, max_results=args.max)
    if args.json:
        print(json.dumps({"matches": matches}, indent=2))
    else:
        for m in matches:
            print(f"  {m['name']:<30}  ({m['match_count']}/{m['trigger_count']} triggers matched)")
            print(f"    triggers: {', '.join(m['matched'])}")
    return 0


def _dxm_dir() -> Path:
    env = os.environ.get("KAIZEN_DXM_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path.home() / ".claude" / ".kaizen" / "dxm"


def _iter_dxm_events(session_id: str):
    """Yield dxm events for the given session (best-effort, no raise)."""
    path = _dxm_dir() / f"events-{session_id}.jsonl"
    if not path.is_file():
        return
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _read_inbox_prompts(session_id: str) -> list[tuple[float, str]]:
    """Return [(ts_unix, prompt_text), ...] for the session's inbox
    captures. Inbox writes one JSON per UserPromptSubmit at capture
    time, with session_id + prompt + ISO ts."""
    _here = Path(__file__).resolve().parent
    sys.path.insert(0, str(_here))
    sys.path.insert(0, str(_here.parent / "intent"))
    try:
        import inbox as _inbox
    except ImportError:
        return []
    import datetime as _dt
    out = []
    d = _inbox.inbox_dir()
    if not d.is_dir():
        return []
    for f in sorted(d.glob("*.json")):
        if f.name.startswith("."):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("session_id") != session_id:
            continue
        ts_str = data.get("ts") or ""
        try:
            # ISO with trailing "Z" → UTC. Naive datetime defaults to
            # local TZ in .timestamp(), so explicitly attach UTC when
            # the input ended with Z (the inbox convention).
            naive = _dt.datetime.fromisoformat(ts_str.rstrip("Z"))
            if naive.tzinfo is None:
                naive = naive.replace(tzinfo=_dt.timezone.utc)
            ts = naive.timestamp()
        except (ValueError, AttributeError):
            ts = 0.0
        prompt = data.get("prompt") or ""
        if prompt:
            out.append((ts, prompt))
    return out


def audit_misses(session_id: str, back_seconds: float | None = None) -> list[dict]:
    """Cross-reference inbox prompts with dxm Skill loads. Returns a
    list of misses — prompts that matched a skill the agent did not
    subsequently load. Empty when nothing missed.

    Each miss: {ts, prompt (truncated), skill_matched, skill_loaded?}.
    Pure read-side — no side effects.
    """
    import time as _t
    cutoff = (_t.time() - back_seconds) if back_seconds else 0.0

    prompts = [(ts, p) for ts, p in _read_inbox_prompts(session_id)
               if ts >= cutoff]
    if not prompts:
        return []

    # Collect all Skill loads from dxm in (ts, skill_name) form.
    skill_loads: list[tuple[float, str]] = []
    for e in _iter_dxm_events(session_id):
        if e.get("evt_type") not in ("PreToolUse", "PostToolUse"):
            continue
        if e.get("tool_name") != "Skill":
            continue
        ts = e.get("ts_unix") or 0
        # The skill name lives in the tool_input — dxm shell hot path
        # doesn't capture tool_input (only tool_name / tool_use_id),
        # so we can't know WHICH skill was loaded from dxm alone. Use
        # bare "Skill" loads as a presence signal; the audit reports
        # "matched skills + at least one Skill load happened" vs "no
        # Skill loads at all" rather than per-skill load-vs-match.
        skill_loads.append((float(ts), "Skill"))

    out = []
    for ts, prompt in prompts:
        matches = match_prompt(prompt, max_results=5)
        if not matches:
            continue
        # Any Skill load after this prompt?
        loaded_after = any(slts >= ts for slts, _ in skill_loads)
        for m in matches:
            out.append({
                "ts_unix":          ts,
                "prompt":           prompt[:120],
                "skill":            m["name"],
                "match_count":      m["match_count"],
                "trigger_count":    m["trigger_count"],
                "matched_phrases":  m["matched"][:5],
                "any_skill_loaded_after": loaded_after,
            })
    return out


def _cmd_from_dxm(args) -> int:
    """Post-hoc miss-detector — reads dxm + inbox, reports prompts
    that matched skills the agent likely should have loaded.

    Zero UserPromptSubmit latency cost — runs from already-captured
    trace data, on-demand or via Stop-hook later.
    """
    _here = Path(__file__).resolve().parent
    sys.path.insert(0, str(_here))
    sys.path.insert(0, str(_here.parent / "handoff"))
    sys.path.insert(0, str(_here.parent / "intent"))
    try:
        import _session_jsonl as _sj
    except ImportError:
        if args.json:
            print(json.dumps({"misses": [], "error": "no _session_jsonl"}))
        return 0
    sid = args.session or _sj.discover_active_session_id()
    if not sid:
        if args.json:
            print(json.dumps({"misses": [], "error": "no session"}))
        return 0
    misses = audit_misses(sid, back_seconds=args.back)
    if args.json:
        print(json.dumps({
            "session_id": sid,
            "misses":     misses,
            "count":      len(misses),
        }, indent=2))
    else:
        if not misses:
            print(f"no skill-suggest misses in session {sid}")
            return 0
        # Group by skill for readable output
        by_skill: dict[str, list[dict]] = {}
        for m in misses:
            by_skill.setdefault(m["skill"], []).append(m)
        print(f"kaizen-skill-suggest: {len(misses)} miss(es) in session {sid}")
        for skill, items in sorted(by_skill.items(), key=lambda x: -len(x[1])):
            print(f"\n  Skill: {skill} ({len(items)} prompts matched)")
            for m in items[:3]:
                print(f"    - matched: {', '.join(m['matched_phrases'])}")
                print(f"      prompt: {m['prompt']}")
    return 0


def _cmd_list(args) -> int:
    catalog = index_all()
    if args.json:
        # Strip dir (absolute path) for cleaner JSON
        for s in catalog:
            s.pop("dir", None)
        print(json.dumps({"skills": catalog}, indent=2))
    else:
        for s in catalog:
            n_trig = len(s["triggers"])
            print(f"  {s['name']:<30}  ({n_trig} triggers)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kaizen-skill-suggest",
                                  description="Match prompts to skill triggers.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pm = sub.add_parser("match", help="match a prompt against skill triggers")
    pm.add_argument("--prompt", default="",
                     help="prompt text (or pipe via stdin)")
    pm.add_argument("--max", type=int, default=3,
                     help="max suggestions to return (default 3)")
    pm.add_argument("--json", action="store_true")
    pm.set_defaults(func=_cmd_match)

    pl = sub.add_parser("list", help="list all indexed skills + trigger counts")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=_cmd_list)

    pd = sub.add_parser("from-dxm",
                          help="post-hoc miss-detector — reads dxm + inbox, "
                               "reports prompts that matched skills (zero "
                               "UserPromptSubmit latency)")
    pd.add_argument("--session", default=None,
                     help="session-id override (default: discover from cwd)")
    pd.add_argument("--back", type=float, default=None,
                     help="only consider prompts from last N seconds "
                          "(default: no limit — whole session)")
    pd.add_argument("--json", action="store_true")
    pd.set_defaults(func=_cmd_from_dxm)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
