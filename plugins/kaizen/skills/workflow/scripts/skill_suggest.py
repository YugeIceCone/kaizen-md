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
    # workflow/scripts/ → skills/
    return here.parent.parent


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

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
