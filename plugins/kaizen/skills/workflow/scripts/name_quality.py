#!/usr/bin/env python3
"""kaizen-name-quality — does the filename match the file's stated intent?

Walks Python scripts under `skills/workflow/scripts/` and scores each
filename against the intent extracted from its first docstring (or
top header comment for .sh files).

## Scoring (0-100)

For each file:
  1. Tokenize the FILENAME (snake/kebab split, lowercased, alpha only).
     `code_to_test_coverage.py` → {code, to, test, coverage}
  2. Tokenize the FIRST DOCSTRING (first ~30 alpha words, lowercased,
     stopwords removed). e.g. "kaizen-coverage -- mechanical 1:1 code-to-test
     mapper" -> {kaizen, coverage, mechanical, code, test, mapper}
  3. Base score = 100 * |filename ∩ intent| / |filename|  (recall-style;
     "does the filename's promise appear in the intent?")
  4. PENALTY -20 if filename is a generic junk-drawer name (utils,
     helper, misc, common, base, shared)
  5. PENALTY -15 if no docstring at all (intent unverifiable)
  6. BONUS +10 if every filename token appears in intent (perfect recall)

## Thresholds

  active (score >= 70)  — name and intent agree
  weak   (40 <= < 70)   — partial overlap; flag for renaming consideration
  bad    (< 40)         — name and intent disagree; rename or document why

## Subcommands

  report [--json]              full report
  score <path> [--json]        single-file detail
  gaps [--json]                weak + bad only (exit 1 if any)
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path


_SCRIPT_DIR = Path(__file__).resolve().parent


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[2]


# Common English stopwords — drop these from intent tokens so the
# jaccard isn't dominated by 'the', 'of', 'a', etc.
_STOPWORDS = frozenset({
    "the", "a", "an", "of", "to", "for", "in", "on", "at", "by", "with",
    "and", "or", "is", "are", "be", "this", "that", "these", "those",
    "it", "its", "as", "from", "into", "via", "we", "our", "use", "uses",
    "used", "when", "where", "what", "why", "how", "if", "but", "no",
    "not", "all", "any", "each", "per", "do", "does", "see", "via",
    "etc", "default", "i", "you", "your", "their", "his", "her",
})

# Generic junk-drawer names that earn a quality penalty
_JUNK_NAMES = frozenset({
    "utils", "util", "helper", "helpers", "misc", "common",
    "base", "shared", "stuff", "things", "tmp", "temp",
})


def _tokenize_filename(stem: str) -> set[str]:
    """Filename stem → token set (alpha only, lowercased).
    Splits snake_case + kebab-case + camelCase."""
    # snake / kebab → split
    parts = re.split(r"[_\-]", stem)
    # camelCase → split
    out = []
    for p in parts:
        for sub in re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+", p):
            if sub.isalpha():
                out.append(sub.lower())
    # Drop leading-underscore marker (e.g. _atomic → {atomic})
    return {t for t in out if t and t not in _STOPWORDS}


def _tokenize_intent(text: str, max_words: int = 40) -> set[str]:
    """First ~max_words alpha tokens from text, lowercased, stopwords dropped."""
    if not text:
        return set()
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]*", text)[:max_words]
    out: set[str] = set()
    for w in words:
        # split internal _ / - so docstring "kaizen-coverage" contributes both
        for sub in re.split(r"[_\-]", w):
            sub = sub.lower()
            if sub and sub.isalpha() and sub not in _STOPWORDS:
                out.add(sub)
    return out


def _extract_intent_py(path: Path) -> str:
    """Module docstring of a .py file (first one only)."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    try:
        mod = ast.parse(text)
    except SyntaxError:
        return ""
    return (ast.get_docstring(mod) or "").strip()


def _extract_intent_sh(path: Path) -> str:
    """Top header comment block (consecutive `# …` lines) of a .sh file."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            if lines:  # blank ends the block once we've started
                break
            continue
        if s.startswith("#!"):
            continue
        if s.startswith("#"):
            lines.append(s.lstrip("# ").rstrip())
            continue
        break
    return "\n".join(lines).strip()


def _normalize_token(t: str) -> str:
    """Strip trailing plural 's' so `paths` matches `path`. Skips short
    tokens (<= 3 chars) since `is`/`os` shouldn't be normalised."""
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _normalized_overlap(fn_tokens: set[str], int_tokens: set[str]) -> set[str]:
    """Set overlap with singular/plural normalisation. Returns the
    FILENAME tokens that have a normalised match in intent tokens."""
    int_norm = {_normalize_token(t) for t in int_tokens}
    return {t for t in fn_tokens if _normalize_token(t) in int_norm}


def score_file(path: Path) -> dict:
    """Compute the name-quality score for a single file."""
    stem = path.stem
    # Strip leading underscore marker (private modules) for naming check.
    canonical_stem = stem.lstrip("_")
    fn_tokens = _tokenize_filename(canonical_stem)
    if path.suffix == ".py":
        intent_text = _extract_intent_py(path)
    elif path.suffix == ".sh":
        intent_text = _extract_intent_sh(path)
    else:
        intent_text = ""
    int_tokens = _tokenize_intent(intent_text)
    matched = _normalized_overlap(fn_tokens, int_tokens)

    if not fn_tokens:
        base = 0
    else:
        base = 100 * len(matched) // len(fn_tokens)

    score = base
    notes: list[str] = []

    if canonical_stem in _JUNK_NAMES:
        score -= 20
        notes.append(f"junk-drawer name '{canonical_stem}' (-20)")
    if not intent_text:
        score -= 15
        notes.append("no docstring/header (-15)")
    if fn_tokens and matched == fn_tokens:
        score += 10
        notes.append(f"all {len(fn_tokens)} filename tokens in intent (+10)")

    score = max(0, min(100, score))
    if score >= 70:
        verdict = "active"
    elif score >= 40:
        verdict = "weak"
    else:
        verdict = "bad"

    return {
        "path":            str(path),
        "stem":            stem,
        "filename_tokens": sorted(fn_tokens),
        "intent_tokens":   sorted(int_tokens),
        "matched":         sorted(matched),
        "score":           score,
        "verdict":         verdict,
        "notes":           notes,
    }


def scan_scripts(root: Path | None = None) -> list[dict]:
    """Score every .py file under skills/workflow/scripts/."""
    root = root or _plugin_root()
    scripts_dir = root / "skills" / "workflow" / "scripts"
    if not scripts_dir.is_dir():
        return []
    results = []
    for p in sorted(scripts_dir.glob("*.py")):
        if p.name.startswith("__"):  # __init__.py / __pycache__
            continue
        results.append(score_file(p))
    # Sort: bad first, then by score asc within each verdict
    rank = {"bad": 0, "weak": 1, "active": 2}
    results.sort(key=lambda r: (rank.get(r["verdict"], 9), r["score"]))
    return results


def _print_text(reports: list[dict]) -> None:
    counts = {"active": 0, "weak": 0, "bad": 0}
    for r in reports:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print(f"name-quality: {len(reports)} file(s) — "
          f"{counts.get('active', 0)} active, "
          f"{counts.get('weak', 0)} weak, "
          f"{counts.get('bad', 0)} bad")
    for r in reports:
        if r["verdict"] == "active":
            continue
        mark = "▲" if r["verdict"] == "bad" else "△"
        rel = Path(r["path"]).relative_to(_plugin_root()) \
              if r["path"].startswith(str(_plugin_root())) else r["path"]
        print(f"  {mark} [{r['verdict']:6s}] score={r['score']:>3d}  {rel}")
        if r["filename_tokens"] and not (set(r["filename_tokens"]) & set(r["intent_tokens"])):
            print(f"      ⚠ no overlap: fn={r['filename_tokens']} ∩ intent=∅")
        for n in r["notes"]:
            print(f"      • {n}")


def _cmd_report(args) -> int:
    reports = scan_scripts()
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        _print_text(reports)
    return 0


def _cmd_score(args) -> int:
    p = Path(args.path)
    if not p.is_file():
        sys.stderr.write(f"[kaizen-name-quality] not a file: {p}\n")
        return 1
    r = score_file(p)
    if args.json:
        print(json.dumps(r, indent=2))
    else:
        _print_text([r])
    return 0


def _cmd_gaps(args) -> int:
    bad_or_weak = [r for r in scan_scripts() if r["verdict"] != "active"]
    if args.json:
        print(json.dumps(bad_or_weak, indent=2))
    else:
        _print_text(bad_or_weak)
    return 1 if bad_or_weak else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-name-quality",
        description="Does the filename match the file's stated intent?",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("report", help="score every .py under workflow/scripts/")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=_cmd_report)

    ps = sub.add_parser("score", help="score one file")
    ps.add_argument("path")
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=_cmd_score)

    pg = sub.add_parser("gaps", help="bad + weak only (exit 1 if any — CI gate)")
    pg.add_argument("--json", action="store_true")
    pg.set_defaults(func=_cmd_gaps)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
