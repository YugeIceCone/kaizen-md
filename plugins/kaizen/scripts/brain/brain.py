"""kaizen brain — capture flow + CLI.

Top-level entry for the Second-Brain capture pipeline. Drives a
PocketFlow AsyncNode graph through the canonical sequence:

::

   ParsePromptNode      ← user text + classification hints
        │
        ▼
   DetectTypeNode       ← world-fact / belief / observation / experience
        │
        ▼
   JournalNode          ← append verbatim quote to Journal/<date>.md FIRST
        │
        ▼
   RouteNode            ← decide tier (brain vs project-memory) + file
        │
        ▼
   DedupNode            ← search existing for near-duplicate; merge vs new
        │
        ▼
   WriteNode            ← create/update the L2 file with frontmatter
        │
        ▼
   ReportNode           ← surface what landed where

The flow reads its routing decisions from
``skills/brain/domain/routing.yaml`` via ``_brain.Config``. Behaviour
is fully schema-driven; the node bodies are bookkeeping over the
yaml-declared rules.

## CLI

::

   kaizen-brain capture <text>           # single-shot capture
   kaizen-brain capture <text> --type belief --confidence 0.8
   kaizen-brain detect <text>             # show inferred type only
   kaizen-brain path                      # print resolved paths
   kaizen-brain status                    # brain stats
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — kaizen helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "workflow" / "scripts"))
# Sibling cluster — build_index.py (the `index` verb's backing module)
# lives at scripts/indexers/, not scripts/brain/. Add to path so the
# consolidated-CLI dispatch can resolve `import build_index`.
sys.path.insert(0, str(_SCRIPT_DIR.parent / "indexers"))

import _brain  # noqa: E402
import flow as _flow  # noqa: E402


# ─── Capture flow nodes ──────────────────────────────────────────────


class ParsePromptNode(_flow.AsyncNode):
    """Stage 1 — normalize the input, surface explicit hints.

    Inputs (store):
      text:       raw captured text (required)
      type_hint:  user-supplied type override (optional)
      confidence: user-supplied confidence (optional, belief only)
      tier_hint:  'brain' | 'project' | None
      subject:    optional entity name (Person / Project / Area)
      cwd:        Path for project-slug derivation (default: Path.cwd())
    """

    async def prep_async(self, store: dict) -> dict:
        return {
            "text": (store.get("text") or "").strip(),
            "type_hint": store.get("type_hint"),
            "confidence": store.get("confidence"),
            "tier_hint": store.get("tier_hint"),
            "subject": store.get("subject"),
            "cwd": store.get("cwd") or Path.cwd(),
        }

    async def exec_async(self, prep: dict) -> dict:
        # Surface any cli flags as overrides in the parsed record.
        return prep

    async def post_async(self, store: dict, prep: dict, exec_result: dict) -> str:
        store["parsed"] = exec_result
        if not exec_result["text"]:
            store["error"] = "empty input — nothing to capture"
            return "abort"
        return "default"


class DetectTypeNode(_flow.AsyncNode):
    """Stage 2 — classify into one of four epistemic types.

    Respects an explicit ``type_hint`` if present and valid; otherwise
    runs ``_brain.detect_type`` against the loaded Config."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "text": store["parsed"]["text"],
            "type_hint": store["parsed"]["type_hint"],
            "cfg": store["cfg"],
        }

    async def exec_async(self, prep: dict) -> str:
        if prep["type_hint"] and prep["type_hint"] in prep["cfg"].types:
            return prep["type_hint"]
        return _brain.detect_type(prep["text"], prep["cfg"])

    async def post_async(self, store: dict, prep: dict, type_name: str) -> str:
        store["type"] = type_name
        return "default"


class JournalNode(_flow.AsyncNode):
    """Stage 3 — journal-first capture per the Remember discipline.

    Appends the verbatim quote to ``<brain_root>/Journal/<today>.md``
    before any L2 write. Creates the file if absent (matches the
    daily template shape — H1 with date + "## Captures" section)."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "text": store["parsed"]["text"],
            "type": store["type"],
            "brain_root": store["brain_root"],
            "subject": store["parsed"]["subject"],
        }

    async def exec_async(self, prep: dict) -> dict:
        today = dt.date.today().isoformat()
        journal_path = prep["brain_root"] / "Journal" / f"{today}.md"
        # Ensure the file exists with a header
        if not journal_path.is_file():
            journal_path.parent.mkdir(parents=True, exist_ok=True)
            journal_path.write_text(
                f"---\ndate: {today}\ntype: experience\n---\n\n"
                f"# Journal — {today}\n\n",
                encoding="utf-8",
            )
        # Append the capture under a subject header
        subject = prep["subject"] or prep["type"].title()
        existing = journal_path.read_text(encoding="utf-8")
        # Avoid duplicating the verbatim quote within the same day
        quote_line = f'- "{prep["text"]}"'
        if quote_line in existing:
            return {"path": str(journal_path), "appended": False}
        with journal_path.open("a", encoding="utf-8") as f:
            # Insert a subject section if not already present that day
            if f"\n## {subject}\n" not in existing:
                f.write(f"\n## {subject}\n")
            f.write(f"{quote_line}\n")
        return {"path": str(journal_path), "appended": True}

    async def post_async(self, store: dict, prep: dict, exec_result: dict) -> str:
        store["journal_path"] = exec_result["path"]
        store["journal_appended"] = exec_result["appended"]
        return "default"


class RouteNode(_flow.AsyncNode):
    """Stage 4 — pick tier + target file from routing.yaml.

    Tier rules iterate ``cfg.tier_rules`` in order; first match wins.
    File rules within the chosen tier iterate the per-type list."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "parsed": store["parsed"],
            "type": store["type"],
            "cfg": store["cfg"],
            "brain_root": store["brain_root"],
            "project_memory_root": store["project_memory_root"],
        }

    async def exec_async(self, prep: dict) -> dict:
        cfg = prep["cfg"]
        type_name = prep["type"]
        confidence = prep["parsed"]["confidence"]
        tier_hint = prep["parsed"]["tier_hint"]
        text = prep["parsed"]["text"]

        # Tier selection
        tier = "project-memory"  # default
        if tier_hint == "brain":
            tier = "brain"
        elif tier_hint == "project":
            tier = "project-memory"
        else:
            tier = _select_tier(cfg, type_name, confidence, text)

        # File selection
        if tier == "brain":
            base = prep["brain_root"]
            rules = (cfg.file_rules.get("brain") or {}).get(type_name, [])
            subdir, filename = _apply_file_rules(rules, prep["parsed"], type_name)
            target = base / subdir / filename if subdir else base / filename
        else:
            base = prep["project_memory_root"]
            rules = (cfg.file_rules.get("project-memory") or {}).get(type_name, [])
            subdir, filename = _apply_file_rules(rules, prep["parsed"], type_name)
            target = base / subdir / filename if subdir else base / filename

        return {"tier": tier, "target": target, "subdir": subdir, "filename": filename}

    async def post_async(self, store: dict, prep: dict, exec_result: dict) -> str:
        store["tier"] = exec_result["tier"]
        store["target_path"] = exec_result["target"]
        return "default"


def _select_tier(cfg: "_brain.Config", type_name: str, confidence: Any, text: str) -> str:
    """Walk cfg.tier_rules; first match wins."""
    text_l = (text or "").lower()
    for rule in cfg.tier_rules:
        when = rule.when or {}
        # keyword_any
        kws = when.get("keyword_any") or []
        if kws and not any(_pattern_match(k, text_l) for k in kws):
            continue
        # type_in
        if when.get("type_in") and type_name not in when["type_in"]:
            continue
        # confidence_gte
        if "confidence_gte" in when:
            try:
                if confidence is None or float(confidence) < float(when["confidence_gte"]):
                    continue
            except (TypeError, ValueError):
                continue
        # Empty when {} matches everything
        return rule.route_to
    return "project-memory"


def _pattern_match(pattern: str, text_l: str) -> bool:
    """Substring + simple regex-glob match. Triggers in yaml use
    `.*` literals so we treat them as substring with that wildcard."""
    if ".*" in pattern:
        import re
        try:
            return re.search(pattern, text_l, re.IGNORECASE) is not None
        except re.error:
            return pattern.lower() in text_l
    return pattern.lower() in text_l


def _apply_file_rules(rules: list, parsed: dict, type_name: str) -> tuple[str, str]:
    """Return (subdir, filename) for the first matching file rule.

    ``subdir`` may contain placeholders like ``<project>`` / ``<area>``
    which are substituted from the parsed record's ``subject`` field
    or fall through to the catch-all when no subject is provided.

    The filename template supports ``{slug}`` / ``{entity}`` /
    ``{iso_date}`` substitutions."""
    if not rules:
        # No rule for this type → land at Notes/ root as a last resort
        slug = _brain.slugify(parsed.get("subject") or parsed["text"][:80])
        return "Notes", f"{slug}.md"
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        when = rule.get("when") or {}
        if when and not _file_rule_matches(when, parsed):
            continue
        subdir = rule.get("subdir") or ""
        filename_template = rule.get("filename_template") or ""
        subdir = _substitute(subdir, parsed)
        filename = _substitute(filename_template, parsed) or f"{_brain.slugify(parsed.get('subject') or parsed['text'][:80])}.md"
        return subdir, filename
    # Fallthrough
    slug = _brain.slugify(parsed.get("subject") or parsed["text"][:80])
    return "Notes", f"{slug}.md"


def _file_rule_matches(when: dict, parsed: dict) -> bool:
    """Tiny matcher for file-rule predicates (project/area/person flags).
    For now: only check `subject_is_person` / `subject_is_project` if
    the parsed subject is supplied with a sentinel prefix. Most uses
    pass {} (catch-all)."""
    subject = parsed.get("subject") or ""
    if when.get("subject_is_person"):
        return subject.lower().startswith("person:") or "@" in subject
    if when.get("subject_is_project"):
        return subject.lower().startswith("project:")
    return True


def _substitute(template: str, parsed: dict) -> str:
    """Replace {slug} / {entity} / {iso_date} / <project> / <area> /
    <person> placeholders in a path template."""
    if not template:
        return ""
    s = template
    subject = parsed.get("subject") or ""
    slug_source = subject or parsed["text"][:80]
    s = s.replace("{slug}", _brain.slugify(slug_source))
    s = s.replace("{entity}", _brain.slugify(subject.replace("person:", "").replace("project:", "").replace("@", "")))
    s = s.replace("{iso_date}", dt.date.today().isoformat())
    s = s.replace("<project>", _brain.slugify(subject.replace("project:", "")) if "project:" in subject else "")
    s = s.replace("<area>", _brain.slugify(subject.replace("area:", "")) if "area:" in subject else "")
    s = s.replace("<person>", _brain.slugify(subject.replace("person:", "")) if "person:" in subject else "")
    # Strip any unresolved <...> placeholders
    import re
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("//", "/").strip("/")
    return s


class DedupNode(_flow.AsyncNode):
    """Stage 5 — check the target path for an existing note with a
    similar `name` or `description`. When found, increment the existing
    note's sources_count and append-only update; otherwise mark for
    fresh create."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "target": store["target_path"],
            "text": store["parsed"]["text"],
            "type": store["type"],
            "subject": store["parsed"]["subject"],
            "confidence": store["parsed"]["confidence"],
        }

    async def exec_async(self, prep: dict) -> dict:
        target: Path = prep["target"]
        existing: Optional[tuple[dict, str]] = None
        if target.is_file():
            existing = _brain.parse_note(target.read_text(encoding="utf-8"))
        return {"existing": existing}

    async def post_async(self, store: dict, prep: dict, exec_result: dict) -> str:
        store["existing"] = exec_result["existing"]
        return "default"


class WriteNode(_flow.AsyncNode):
    """Stage 6 — write the L2 file. Either CREATE or MERGE.

    CREATE: brand-new file. Build frontmatter from the parsed record
    + detected type + today's date. sources_count starts at 1.

    MERGE: file exists. Bump sources_count, set updated=today, append
    an evidence row tied to the journal entry. Body gains an "Evidence"
    section if not present."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "target": store["target_path"],
            "type": store["type"],
            "tier": store["tier"],
            "parsed": store["parsed"],
            "existing": store["existing"],
            "journal_path": store.get("journal_path"),
        }

    async def exec_async(self, prep: dict) -> dict:
        target: Path = prep["target"]
        type_name = prep["type"]
        parsed = prep["parsed"]
        today = dt.date.today().isoformat()
        evidence_row = {
            "source": prep["journal_path"] or "",
            "quote": parsed["text"],
            "date": today,
        }
        if prep["existing"]:
            fm, body = prep["existing"]
            fm.setdefault("name", parsed.get("subject") or _brain.slugify(parsed["text"][:80]))
            fm.setdefault("description", parsed["text"][:200])
            fm["type"] = type_name
            if type_name == "belief":
                fm["confidence"] = float(parsed["confidence"] or fm.get("confidence") or 0.7)
            fm["sources_count"] = int(fm.get("sources_count") or 1) + 1
            fm.setdefault("evidence", [])
            fm["evidence"].append(evidence_row)
            action = "merged"
        else:
            fm = {
                "name": parsed.get("subject") or parsed["text"][:80].strip(),
                "description": parsed["text"][:200],
                "type": type_name,
            }
            if type_name == "belief":
                fm["confidence"] = float(parsed["confidence"]) if parsed["confidence"] is not None else 0.7
            fm["tags"] = []
            fm["sources_count"] = 1
            fm["freshness"] = "fresh"
            fm["evidence"] = [evidence_row]
            body = f"# {fm['name']}\n\n{parsed['text']}\n"
            action = "created"
        _brain.write_note(target, fm, body)
        return {"action": action, "path": str(target), "sources_count": fm.get("sources_count")}

    async def post_async(self, store: dict, prep: dict, exec_result: dict) -> str:
        store["action"] = exec_result["action"]
        store["written_path"] = exec_result["path"]
        store["sources_count"] = exec_result["sources_count"]
        return "default"


class ReportNode(_flow.AsyncNode):
    """Final stage — emit a JSON-able summary into the store for the
    CLI / MCP / hook callers."""

    async def prep_async(self, store: dict) -> dict:
        return {}

    async def exec_async(self, prep: dict) -> dict:
        return {}

    async def post_async(self, store: dict, prep: dict, exec_result: dict) -> str:
        store["report"] = {
            "type": store.get("type"),
            "tier": store.get("tier"),
            "action": store.get("action"),
            "path": store.get("written_path"),
            "journal": store.get("journal_path"),
            "sources_count": store.get("sources_count"),
        }
        return "default"


def build_capture_flow() -> _flow.AsyncFlow:
    """Assemble the capture flow. Linear pipeline: Parse → Detect →
    Journal → Route → Dedup → Write → Report. `abort` action from
    ParsePromptNode short-circuits to None (no further nodes)."""
    parse = ParsePromptNode()
    detect = DetectTypeNode()
    journal = JournalNode()
    route = RouteNode()
    dedup = DedupNode()
    write = WriteNode()
    report = ReportNode()
    flow = _flow.AsyncFlow(parse)
    flow.add_successor(parse, "default", detect)
    flow.add_successor(detect, "default", journal)
    flow.add_successor(journal, "default", route)
    flow.add_successor(route, "default", dedup)
    flow.add_successor(dedup, "default", write)
    flow.add_successor(write, "default", report)
    return flow


async def capture_async(
    text: str,
    *,
    type_hint: Optional[str] = None,
    confidence: Optional[float] = None,
    tier_hint: Optional[str] = None,
    subject: Optional[str] = None,
    cwd: Optional[Path] = None,
    cfg: Optional["_brain.Config"] = None,
    brain_root_override: Optional[Path] = None,
    project_memory_root_override: Optional[Path] = None,
) -> dict:
    """Run the capture flow and return the report."""
    cfg = cfg or _brain.Config.load()
    store: dict = {
        "text": text,
        "type_hint": type_hint,
        "confidence": confidence,
        "tier_hint": tier_hint,
        "subject": subject,
        "cwd": cwd or Path.cwd(),
        "cfg": cfg,
        "brain_root": brain_root_override or _brain.brain_root(),
        "project_memory_root": project_memory_root_override or _brain.project_memory_root(cwd),
    }
    await build_capture_flow().run_async(store)
    if "error" in store:
        return {"error": store["error"]}
    return store.get("report") or {}


def capture(text: str, **kwargs) -> dict:
    """Sync wrapper around capture_async."""
    return asyncio.run(capture_async(text, **kwargs))


# ─── Status ──────────────────────────────────────────────────────────


def status() -> dict:
    """Brain stats — count files per directory."""
    root = _brain.brain_root()
    out: dict = {"brain_root": str(root)}
    if not root.is_dir():
        out["error"] = "brain root does not exist"
        return out
    for sub in ("Notes", "Journal", "Projects", "People", "Areas", "Inbox"):
        p = root / sub
        if p.is_dir():
            out[sub] = sum(1 for _ in p.rglob("*.md"))
        else:
            out[sub] = 0
    persona = root / "Persona.md"
    out["persona_present"] = persona.is_file()
    return out


# ─── CLI ─────────────────────────────────────────────────────────────


def _cmd_capture(args) -> int:
    confidence = float(args.confidence) if args.confidence is not None else None
    result = capture(
        text=args.text,
        type_hint=args.type,
        confidence=confidence,
        tier_hint=args.tier,
        subject=args.subject,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if "error" not in result else 1


def _cmd_detect(args) -> int:
    cfg = _brain.Config.load()
    t = _brain.detect_type(args.text, cfg)
    print(json.dumps({"type": t}, indent=2))
    return 0


def _cmd_path(args) -> int:
    out = {
        "brain_root": str(_brain.brain_root()),
        "project_memory_root": str(_brain.project_memory_root()),
        "domain_dir": str(_brain._DOMAIN_DIR),
    }
    print(json.dumps(out, indent=2))
    return 0


def _cmd_status(args) -> int:
    print(json.dumps(status(), indent=2))
    return 0


# ─── block-level addressing — zero-roundtrip memory edits ────────────


def _resolve_memory_file(arg: str) -> "Path":
    """Resolve a --file arg to a real Markdown file.

    Tries (in order): literal path → brain root → auto-memory dir.
    First hit wins. Returns the un-resolved literal path if no hit
    (caller emits the not-found error).

    Short-name examples:
      ``Persona.md`` → ~/.claude/.kaizen/brain/Persona.md
      ``MEMORY.md`` → ~/.claude/projects/<slug>/memory/MEMORY.md
      ``Notes/pref-x.md`` → ~/.claude/.kaizen/brain/Notes/pref-x.md
    """
    from pathlib import Path as _P
    p = _P(arg)
    if p.is_file():
        return p
    # Try brain root
    try:
        bp = _brain.brain_root() / arg
        if bp.is_file():
            return bp
    except Exception:
        pass
    # Try auto-memory dir (better_memory helper)
    try:
        sys.path.insert(0, str(_P(__file__).resolve().parent))
        import better_memory as _bm
        mp = _bm._default_memory_dir() / arg
        if mp.is_file():
            return mp
    except Exception:
        pass
    return p


def _file_not_found_msg(arg: str, verb: str) -> str:
    """Diagnostic listing the resolution attempts."""
    from pathlib import Path as _P
    attempts = [str(_P(arg))]
    try:
        attempts.append(str(_brain.brain_root() / arg))
    except Exception:
        pass
    try:
        sys.path.insert(0, str(_P(__file__).resolve().parent))
        import better_memory as _bm
        attempts.append(str(_bm._default_memory_dir() / arg))
    except Exception:
        pass
    return (f"brain {verb}: file not found: {arg}\n"
            f"  searched (brain root + auto-memory):\n"
            + "\n".join(f"    - {a}" for a in attempts) + "\n")


def _cmd_blocks(args) -> int:
    """List addressable blocks in a Markdown file."""
    import _brain_blocks as _bb
    fp = _resolve_memory_file(args.file)
    if not fp.is_file():
        sys.stderr.write(_file_not_found_msg(args.file, "blocks"))
        return 2
    blocks = _bb.parse_blocks(fp.read_text(encoding="utf-8"))
    if args.json:
        print(json.dumps({"file": str(fp), "blocks": blocks}, indent=2))
    else:
        print(f"brain blocks: {fp}")
        for b in blocks:
            indent = "  " * max(0, b["level"] - 1)
            n_lines = b["end"] - b["start"]
            print(f"  {b['start']:>4}+{n_lines:<3}  {indent}{b['path']}")
    return 0


def _cmd_show(args) -> int:
    """Extract one block (no whole-file Read)."""
    import _brain_blocks as _bb
    fp = _resolve_memory_file(args.file)
    if not fp.is_file():
        sys.stderr.write(_file_not_found_msg(args.file, "show"))
        return 2
    text = fp.read_text(encoding="utf-8")
    body = _bb.extract_block(text, args.block)
    if body is None:
        sys.stderr.write(f"brain show: block not found: {args.block!r}\n")
        return 1
    if args.json:
        print(json.dumps({"file": str(fp), "block": args.block,
                           "body": body}, indent=2))
    else:
        print(body)
    return 0


def _cmd_edit(args) -> int:
    """Atomic in-place edit of a single block. Replace or append."""
    import _brain_blocks as _bb
    fp = _resolve_memory_file(args.file)
    if not fp.is_file():
        sys.stderr.write(_file_not_found_msg(args.file, "edit"))
        return 2
    if not (args.replace or args.append):
        sys.stderr.write("brain edit: --replace OR --append required\n")
        return 1
    text = fp.read_text(encoding="utf-8")
    try:
        if args.replace is not None:
            new_text = _bb.replace_block(text, args.block, args.replace)
        else:
            new_text = _bb.append_to_list_block(text, args.block, args.append)
    except KeyError as e:
        sys.stderr.write(f"brain edit: {e}\n")
        return 1
    tmp = fp.with_suffix(fp.suffix + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(fp)
    if args.json:
        print(json.dumps({"file": str(fp), "block": args.block,
                           "op": "replace" if args.replace else "append"},
                          indent=2))
    else:
        op = "replaced" if args.replace else "appended"
        print(f"brain edit: {op} block {args.block!r} in {fp}")
    return 0


# ─── Persona semantic verbs (Phase A — Gap 3) ────────────────────────


def _persona_path() -> "Path":
    """Resolve Persona.md via the short-name resolver."""
    return _resolve_memory_file("Persona.md")


def _block_contains_line(text: str, block_path: str, needle: str) -> bool:
    """True iff ``needle`` appears verbatim inside the block body."""
    import _brain_blocks as _bb
    body = _bb.extract_block(text, block_path)
    return body is not None and needle in body


def _ensure_block(text: str, heading: str, level: int = 2) -> str:
    """Return text with ``## {heading}`` appended if missing. Idempotent."""
    import _brain_blocks as _bb
    if _bb.extract_block(text, heading) is not None:
        return text
    sep = "" if text.endswith("\n") else "\n"
    return f"{text}{sep}\n{'#' * level} {heading}\n\n"


def _atomic_write_persona(persona_path: "Path", new_text: str) -> None:
    """Tempfile-then-rename. Same shape as _cmd_edit's writer."""
    tmp = persona_path.with_suffix(persona_path.suffix + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(persona_path)


def _cmd_log_evidence(args) -> int:
    """Append a quote / observation to Persona's Evidence Log block.

    Auto-prefixes [YYYY-MM-DD] when the input doesn't start with `[`.
    Idempotent: skips if the exact line already exists.
    Auto-seeds the Evidence Log block if absent.
    """
    import _brain_blocks as _bb
    persona = _persona_path()
    if not persona.is_file():
        sys.stderr.write(f"brain log-evidence: Persona not found at {persona}\n")
        return 2

    text = persona.read_text(encoding="utf-8")
    raw = (args.text or "").strip()
    if not raw:
        sys.stderr.write("brain log-evidence: empty text\n")
        return 1

    # Prefix today's date unless the text already starts with [YYYY-...]
    if raw.startswith("["):
        line_body = raw
    else:
        from datetime import date
        line_body = f"[{date.today().isoformat()}] {raw}"

    full_line = f"- {line_body}"
    text = _ensure_block(text, "Evidence Log", level=2)
    if _block_contains_line(text, "Evidence Log", full_line):
        print(f"brain log-evidence: already present (skip): {line_body[:60]}…")
        return 0
    new_text = _bb.append_to_list_block(text, "Evidence Log", full_line)
    _atomic_write_persona(persona, new_text)
    print(f"brain log-evidence: appended → {persona}")
    return 0


def _cmd_new_directive(args) -> int:
    """Append a new directive to Persona's Directives block.

    Every directive must link a Note (via --note Notes/<slug>). Idempotent
    on exact text match. Atomic.
    """
    import _brain_blocks as _bb
    persona = _persona_path()
    if not persona.is_file():
        sys.stderr.write(f"brain new-directive: Persona not found at {persona}\n")
        return 2
    rule = (args.text or "").strip().rstrip(".")
    if not rule:
        sys.stderr.write("brain new-directive: empty rule text\n")
        return 1
    if not args.note:
        sys.stderr.write("brain new-directive: --note <Notes/slug> is required "
                          "(every directive must link a Note)\n")
        return 1
    note_ref = args.note.strip()
    full_line = f"- **{rule}.** See [[{note_ref}]]."

    text = persona.read_text(encoding="utf-8")
    text = _ensure_block(text, "Directives", level=2)
    if _block_contains_line(text, "Directives", full_line):
        print(f"brain new-directive: already present (skip): {rule[:60]}…")
        return 0
    new_text = _bb.append_to_list_block(text, "Directives", full_line)
    _atomic_write_persona(persona, new_text)
    print(f"brain new-directive: appended → {persona}")
    return 0


def _cmd_promote_belief(args) -> int:
    """Append a new entry to Persona's Top Beliefs block.

    Auto-assigns the next sequential rank. Normalizes ``Notes/pref-x`` →
    ``Notes/pref-x.md`` (Top Beliefs convention). Idempotent: a Note
    already in Top Beliefs is reported but not duplicated.
    """
    import re as _re
    import _brain_blocks as _bb
    persona = _persona_path()
    if not persona.is_file():
        sys.stderr.write(f"brain promote-belief: Persona not found at {persona}\n")
        return 2
    note = (args.note or "").strip()
    if not note:
        sys.stderr.write("brain promote-belief: <note> ref required (e.g. Notes/pref-x)\n")
        return 1
    # Normalize: accept "pref-x" / "pref-x.md" / "Notes/pref-x" / "Notes/pref-x.md"
    if not note.startswith("Notes/"):
        note = "Notes/" + note
    if not note.endswith(".md"):
        note = note + ".md"

    text = persona.read_text(encoding="utf-8")
    text = _ensure_block(text, "Top Beliefs", level=2)
    body = _bb.extract_block(text, "Top Beliefs") or ""

    # Idempotency: skip if note already in Top Beliefs
    if f"[[{note}]]" in body:
        print(f"brain promote-belief: {note} already promoted (skip)")
        return 0

    # Find max existing rank
    max_rank = 0
    for m in _re.finditer(r"^(\d+)\.\s+\[\[", body, _re.M):
        max_rank = max(max_rank, int(m.group(1)))
    next_rank = max_rank + 1

    meta = []
    if args.conf is not None:
        meta.append(f"conf={args.conf}")
    if args.sources is not None:
        meta.append(f"sources={args.sources}")
    if args.freshness:
        meta.append(f"freshness={args.freshness}")
    tail = (" — " + " ".join(meta)) if meta else ""
    full_line = f"{next_rank}. [[{note}]]{tail}"

    new_text = _bb.append_to_list_block(text, "Top Beliefs", full_line)
    _atomic_write_persona(persona, new_text)
    print(f"brain promote-belief: rank {next_rank} → {note}")
    return 0


# ─── auto-load pin management ────────────────────────────────────────


def _cmd_pin(args) -> int:
    """Pin a Note into the daemon-built auto-load.md."""
    import auto_load as _al
    _al.add_pin(args.note)
    print(f"brain pin: pinned {args.note} (pins now: "
          f"{len(_al.load_pins())})")
    return 0


def _cmd_unpin(args) -> int:
    """Remove a Note from the pin list (idempotent)."""
    import auto_load as _al
    _al.remove_pin(args.note)
    print(f"brain unpin: unpinned {args.note} (pins now: "
          f"{len(_al.load_pins())})")
    return 0


def _cmd_list_pins(args) -> int:
    """Print the current pin list."""
    import auto_load as _al
    pins = _al.load_pins()
    if args.json:
        print(json.dumps({"data": {"pins": pins, "count": len(pins)}}))
    else:
        if not pins:
            print("brain pins: (none)")
        else:
            print(f"brain pins: {len(pins)} pinned")
            for p in pins:
                print(f"  - {p}")
    return 0


# ─── Starter seeding (onboarding) ────────────────────────────────────


# PARA subdirs every starter is expected to populate (created as empty
# dirs even when the starter doesn't ship files for them — gives the
# brain hooks a place to write into on day 1).
_PARA_SUBDIRS = (
    "Inbox", "Journal", "Projects", "People", "Areas",
    "Resources", "Tasks", "Templates", "Archive",
)


def _starters_dir():
    """Path to the bundled `assets/starters/` directory."""
    from pathlib import Path as _P
    here = _P(__file__).resolve()
    # plugins/kaizen/scripts/brain/brain.py  →  plugins/kaizen/
    plugin_root = here.parents[2]
    return plugin_root / "assets" / "starters"


def list_starters() -> list[str]:
    """Names of every shipped starter (alphabetical)."""
    d = _starters_dir()
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_dir())


def _seed_starter(name: str, dst: Path, *, force: bool = False) -> int:
    """Copy `assets/starters/<name>/` into `dst`. Returns exit code."""
    import shutil
    import datetime as _dt
    src = _starters_dir() / name
    if not src.is_dir():
        avail = ", ".join(list_starters()) or "(none)"
        sys.stderr.write(
            f"[kaizen-brain seed] starter '{name}' not found.\n"
            f"  available: {avail}\n"
        )
        return 1
    if dst.exists() and any(dst.iterdir()) and not force:
        sys.stderr.write(
            f"[kaizen-brain seed] {dst} is not empty.\n"
            "  refuse to overwrite without --force\n"
        )
        return 2
    today = _dt.date.today().isoformat()
    # Copy every file, substituting {{today}} placeholder in text files.
    # `Notes/`, `Persona.md`, etc. are textual; binary safety isn't a
    # concern (starters are markdown only).
    for src_path in src.rglob("*"):
        if not src_path.is_file():
            continue
        rel = src_path.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        text = src_path.read_text(encoding="utf-8")
        text = text.replace("{{today}}", today)
        target.write_text(text, encoding="utf-8")
    # Always create the PARA subdirs (some starters don't ship files for
    # all of them; the brain capture/hook flow needs them to exist).
    for sub in _PARA_SUBDIRS:
        (dst / sub).mkdir(parents=True, exist_ok=True)
    print(f"[kaizen-brain seed] ✓ seeded '{name}' → {dst}", file=sys.stderr)
    return 0


def cmd_seed(args) -> int:
    """Seed the brain at KAIZEN_BRAIN_DIR from a bundled starter."""
    # Special: `seed list` is implemented as a sentinel `starter=list`.
    if args.starter == "list":
        for s in list_starters():
            print(s)
        return 0
    import _paths as _p
    return _seed_starter(args.starter, _p.BRAIN_DIR, force=args.force)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-brain",
        description="Capture / classify / route thoughts into the kaizen Second Brain.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("capture", help="capture text into the brain")
    sc.add_argument("text", help="thought to capture")
    sc.add_argument("--type", choices=["world-fact", "belief", "observation", "experience"],
                    help="override auto-detected type")
    sc.add_argument("--confidence", type=float, help="belief confidence (0.0-1.0)")
    sc.add_argument("--tier", choices=["brain", "project"], help="force tier")
    sc.add_argument("--subject", help="entity name (Person / Project / Area)")
    sc.set_defaults(func=_cmd_capture)

    sd = sub.add_parser("detect", help="show inferred type without writing")
    sd.add_argument("text", help="text to classify")
    sd.set_defaults(func=_cmd_detect)

    sp = sub.add_parser("path", help="print resolved paths")
    sp.set_defaults(func=_cmd_path)

    ss = sub.add_parser("status", help="brain stats")
    ss.set_defaults(func=_cmd_status)

    # ─── block-level zero-roundtrip memory edits ─────────────────────
    sb = sub.add_parser("blocks",
                          help="list addressable blocks (heading-paths) in a Markdown file")
    sb.add_argument("--file", required=True, help="Markdown file path")
    sb.add_argument("--json", action="store_true")
    sb.set_defaults(func=_cmd_blocks)

    sh = sub.add_parser("show",
                          help="extract one block by heading-path "
                               "(zero whole-file Read)")
    sh.add_argument("--file", required=True, help="Markdown file path")
    sh.add_argument("--block", required=True,
                     help="block path (e.g. 'Top Beliefs' or 'Document/Top Beliefs')")
    sh.add_argument("--json", action="store_true")
    sh.set_defaults(func=_cmd_show)

    se = sub.add_parser("edit",
                          help="atomic in-place block edit. Use --replace "
                               "for full-block swap, --append for list-item add.")
    se.add_argument("--file", required=True, help="Markdown file path")
    se.add_argument("--block", required=True, help="block path")
    se.add_argument("--replace", default=None,
                     help="new full block body (replaces lines from heading "
                          "to next sibling-or-shallower heading)")
    se.add_argument("--append", default=None,
                     help="single list-item line to append at end of block "
                          "(caller provides marker e.g. `- foo` or `4. bar`)")
    se.add_argument("--json", action="store_true")
    se.set_defaults(func=_cmd_edit)

    # Persona semantic verbs — thin shortcuts over edit + _brain_blocks.
    le = sub.add_parser("log-evidence",
                         help="append a quote to Persona's Evidence Log (auto-dates)")
    le.add_argument("text", help="the quote / observation; [YYYY-MM-DD] auto-prefixed if missing")
    le.set_defaults(func=_cmd_log_evidence)

    nd = sub.add_parser("new-directive",
                         help="append a directive to Persona's Directives (requires --note)")
    nd.add_argument("text", help="the rule body (trailing `.` and ` See [[X]].` added)")
    nd.add_argument("--note", required=False,
                     help="Notes/<slug> — the brain Note backing the rule")
    nd.set_defaults(func=_cmd_new_directive)

    pb = sub.add_parser("promote-belief",
                         help="append a Note to Persona's Top Beliefs (auto-ranks)")
    pb.add_argument("note", help="Notes/<slug>[.md] — the Note to promote")
    pb.add_argument("--conf", type=float, default=None, help="confidence (e.g. 0.85)")
    pb.add_argument("--sources", type=int, default=None, help="evidence count")
    pb.add_argument("--freshness", default=None,
                     help="freshness tag (stable / fresh / aging)")
    pb.set_defaults(func=_cmd_promote_belief)

    # Pin management for auto-load.md.
    pn = sub.add_parser("pin", help="pin a Note into ~/.claude/.kaizen/auto-load.md")
    pn.add_argument("note", help="note ref, e.g. Notes/pref-x")
    pn.set_defaults(func=_cmd_pin)

    up = sub.add_parser("unpin", help="unpin a Note from auto-load.md")
    up.add_argument("note", help="note ref, e.g. Notes/pref-x")
    up.set_defaults(func=_cmd_unpin)

    lp = sub.add_parser("list-pins", help="list currently pinned Notes")
    lp.add_argument("--json", action="store_true")
    lp.set_defaults(func=_cmd_list_pins)

    # Onboarding: seed the brain from a curated starter.
    ssd = sub.add_parser("seed",
                          help="bootstrap a working brain from a bundled "
                          "starter (assets/starters/<name>/)")
    ssd.add_argument("starter", default="default", nargs="?",
                      help="starter name (default: 'default'). Use 'list' "
                           "to list available starters.")
    ssd.add_argument("--force", action="store_true",
                      help="overwrite an existing non-empty brain")
    ssd.add_argument("--json", action="store_true",
                      help="(reserved for future envelope output)")
    ssd.set_defaults(func=cmd_seed)

    # ─── Consolidated sub-CLIs (CONSOL-3, v1.40+) ────────────────────
    # `kaizen-brain audit | evolve | index | promote | migrate` delegate
    # to the existing brain_<verb>.py modules' main(). Each module
    # declares `# consolidated-cli-parent: brain` so the iron-law's
    # bin-wrapper-per-cli check is satisfied by kaizen-brain alone.
    # This folds 5 separate bin wrappers into one user-facing command
    # while keeping the module + test boundaries intact.
    for verb, module_name, help_text in (
        ("audit",   "brain_audit",
         "session-end discovery — drafts → Inbox/"),
        ("evolve",  "brain_evolve",
         "consolidation + freshness + Persona promotion"),
        ("index",   "build_index",
         "SQLite + sentence-transformers index over Notes"),
        ("promote", "brain_promote",
         "project-memory → brain promotion flow"),
        ("migrate", "brain_migrate",
         "relocate brain dir (v1.38 migration tool)"),
    ):
        _sp = sub.add_parser(verb, help=help_text, add_help=False)
        # All-args passthrough — the underlying module's argparse owns
        # the flag surface. `add_help=False` prevents argparse from
        # eating `-h`/`--help` here so the child sees it.
        _sp.add_argument("rest", nargs=argparse.REMAINDER)
        _sp.set_defaults(_consol_module=module_name)

    args = p.parse_args(argv)
    if getattr(args, "_consol_module", None):
        # Dispatch to the consolidated sub-CLI's main(argv).
        import importlib
        mod = importlib.import_module(args._consol_module)
        return mod.main(args.rest)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
