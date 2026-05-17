#!/usr/bin/env python3
"""Kaizen intent router — load + lookup + match against
`skills/workflow/domain/intent_routing.yaml`.

Replaces the prose `code-router` SKILL.md. The yaml is the single source
of truth; this script is the only piece of code that loads it. Skill
bodies, slash commands, and downstream tooling all read through here.

## CLI

    python3 route_intent.py validate           # schema-validate the yaml
    python3 route_intent.py list               # one line per route
    python3 route_intent.py route <id>         # print one route as JSON
    python3 route_intent.py match "<prompt>"   # substring-match cues → ranked routes (top 4)
    python3 route_intent.py disambig <a> <b>   # tiebreaker rule between two routes
    python3 route_intent.py composition "<prompt>"   # match composition patterns
    python3 route_intent.py elsewhere          # list route_to redirects + null intents

## Python API

    from route_intent import load, match
    cfg = load()                # full dict
    hits = match("simplify this")    # [(route_id, score), ...] sorted desc

## Stdlib + optional deps

Requires pyyaml. The jsonschema lib is optional — validation skipped with
a warning when absent (mirrors `_loader.py`).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# H1 dedup: shared YAML + JSON-Schema helpers.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _yaml import load_yaml as _load_yaml  # noqa: E402
from _yaml import validate as _check  # noqa: E402

DOMAIN_DIR = Path(__file__).resolve().parent.parent / "domain"
INTENT_YAML = DOMAIN_DIR / "intent_routing.yaml"
INTENT_SCHEMA = DOMAIN_DIR / "schemas" / "intent_routing.schema.json"


def load() -> dict:
    """Return the validated intent_routing.yaml as a dict."""
    data = _load_yaml(INTENT_YAML)
    _check(data, INTENT_SCHEMA, "intent_routing.yaml")
    return data


def routes_by_id(cfg: dict | None = None) -> dict[str, dict]:
    cfg = cfg or load()
    return {r["id"]: r for r in cfg.get("routes", [])}


def disambiguation_index(cfg: dict | None = None) -> dict[frozenset, dict]:
    """Return {frozenset({a, b}): rule_dict} for set-based lookup."""
    cfg = cfg or load()
    return {frozenset(d["pair"]): d for d in cfg.get("disambiguation", [])}


# ─── Matcher ─────────────────────────────────────────────────────────


_WORD_RE = re.compile(r"[a-z0-9]+")


def _normalize(s: str) -> str:
    """Lowercase + collapse whitespace for substring match."""
    return " ".join(_WORD_RE.findall(s.lower()))


def match(prompt: str, cfg: dict | None = None, top_k: int = 4) -> list[tuple[str, int]]:
    """Substring-match `prompt` against each route's `cues`.

    Score = count of distinct cues that appear in the normalised prompt.
    Returns `[(route_id, score), ...]` sorted desc; ties broken by route
    order in the yaml (i.e. the catalog's curated priority).
    """
    cfg = cfg or load()
    norm = _normalize(prompt)
    scored: list[tuple[str, int]] = []
    for r in cfg.get("routes", []):
        hits = sum(1 for cue in r.get("cues", []) if _normalize(cue) in norm)
        if hits > 0:
            scored.append((r["id"], hits))
    # Stable sort: -score, then yaml order (already in scored insertion order).
    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]


def match_composition(prompt: str, cfg: dict | None = None) -> list[dict]:
    """Match the prompt against composition `prompt_shape` text (substring match).

    Composition rules describe meta-shapes ("unfamiliar repo + fix"), not
    raw cues. We surface anything whose shape phrase appears in the prompt.
    """
    cfg = cfg or load()
    norm = _normalize(prompt)
    out = []
    for c in cfg.get("composition", []):
        shape_norm = _normalize(c.get("prompt_shape", ""))
        if shape_norm and shape_norm in norm:
            out.append(c)
    return out


def disambiguate(a: str, b: str, cfg: dict | None = None) -> dict | None:
    """Look up the disambiguation rule between two route ids. Order-independent."""
    cfg = cfg or load()
    return disambiguation_index(cfg).get(frozenset([a, b]))


# ─── CLI ─────────────────────────────────────────────────────────────


def _cli() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        sys.stderr.write(__doc__ or "")
        return 0

    cmd = argv[0]
    args = argv[1:]

    if cmd == "validate":
        load()
        print("ok")
        return 0

    if cmd == "list":
        for r in load().get("routes", []):
            print(f"{r['id']}\t{r['skill']}\t{r['intent']}")
        return 0

    if cmd == "route":
        if not args:
            sys.stderr.write("usage: route_intent.py route <id>\n")
            return 2
        idx = routes_by_id()
        r = idx.get(args[0])
        if r is None:
            sys.stderr.write(f"[route_intent] unknown route id: {args[0]}\n")
            return 1
        json.dump(r, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if cmd == "match":
        if not args:
            sys.stderr.write("usage: route_intent.py match '<prompt>'\n")
            return 2
        cfg = load()
        idx = routes_by_id(cfg)
        hits = match(" ".join(args), cfg)
        if not hits:
            print("(no match)")
            return 1
        for rid, score in hits:
            r = idx[rid]
            print(f"{score}\t{rid}\t{r['skill']}\t{r['intent']}")
        return 0

    if cmd == "disambig":
        if len(args) < 2:
            sys.stderr.write("usage: route_intent.py disambig <a> <b>\n")
            return 2
        rule = disambiguate(args[0], args[1])
        if rule is None:
            sys.stderr.write(f"[route_intent] no disambiguation rule for ({args[0]}, {args[1]})\n")
            return 1
        json.dump(rule, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if cmd == "composition":
        if not args:
            sys.stderr.write("usage: route_intent.py composition '<prompt>'\n")
            return 2
        cfg = load()
        hits = match_composition(" ".join(args), cfg)
        if not hits:
            print("(no composition match)")
            return 1
        json.dump(hits, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if cmd == "elsewhere":
        for e in load().get("elsewhere", []):
            route = e.get("route_to") or "(no skill)"
            print(f"{route}\t{e['intent']}")
        return 0

    sys.stderr.write(f"[route_intent] unknown command: {cmd}\n")
    return 2


if __name__ == "__main__":
    sys.exit(_cli())
