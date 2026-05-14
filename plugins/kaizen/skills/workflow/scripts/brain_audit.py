"""kaizen brain audit — end-of-session discovery audit flow.

Implements the ``pref-session-discovery-log`` directive: at end-of-
session, scan recent activity for non-obvious learnings that haven't
been captured yet, classify them, and surface for user approval.

The audit DOES NOT auto-write to brain. It produces a candidate list
+ optional Inbox draft entries. The user decides what to land via
``kaizen-brain capture <text>`` or by tick-confirming the candidates.

PocketFlow shape::

   ScanSourcesNode → ExtractCandidatesNode → ClassifyNode → InboxNode → ReportNode

Sources scanned (most recent N items each):

  - Project-memory inbox notes (~/.claude/.kaizen/inbox/)
  - Recent git commits in cwd (last 10)
  - Project's auto-memory drafts (memory/_draft_*.md if present)
  - Conversation hint files (.kaizen/loop.state.md captures)

This is a HEURISTIC pass — it surfaces candidates, doesn't decide for
the user. The agent or user reviews + decides what to capture.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _brain  # noqa: E402
import flow as _flow  # noqa: E402


# ─── Source readers ──────────────────────────────────────────────────


def _read_inbox_items(brain_root: Path, limit: int = 20) -> list[dict]:
    """Read pending inbox items if the kaizen inbox is configured.

    Each inbox file is JSON; we serialize the parsed object back to
    a string for text-extraction (the JSON itself often carries
    quoted strings + decisions worth capturing)."""
    inbox = Path("~/.claude/.kaizen/inbox").expanduser().resolve()
    items = []
    if inbox.is_dir():
        for p in sorted(inbox.glob("*.json"), reverse=True)[:limit]:
            try:
                raw = p.read_text(encoding="utf-8")
                # Pretty-print the JSON so quoted strings survive,
                # then cap to a sane length.
                try:
                    text = json.dumps(json.loads(raw), indent=2)[:2000]
                except (json.JSONDecodeError, TypeError):
                    text = raw[:2000]
                items.append({
                    "source": str(p),
                    "kind": "inbox",
                    "text": text,
                })
            except OSError:
                continue
    return items


def _read_recent_commits(repo: Path, limit: int = 10) -> list[dict]:
    """Last N commit subjects + bodies from cwd's git repo."""
    if not (repo / ".git").exists():
        return []
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "log", f"-{limit}", "--format=%H%n%B%x00"],
            capture_output=True, text=True, check=True, timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    items = []
    for entry in out.stdout.split("\0"):
        entry = entry.strip()
        if not entry:
            continue
        lines = entry.split("\n", 1)
        sha = lines[0][:12]
        body = lines[1] if len(lines) > 1 else ""
        items.append({
            "source": f"git:{sha}",
            "kind": "commit",
            "text": body,
        })
    return items


def _read_project_memory_drafts(cwd: Path) -> list[dict]:
    """Look for memory/_draft_*.md files in this session's project."""
    pm = _brain.project_memory_root(cwd)
    if not pm.is_dir():
        return []
    items = []
    for p in sorted(pm.glob("_draft_*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        items.append({
            "source": str(p),
            "kind": "draft",
            "text": text[:2000],
        })
    return items


def _read_loop_state(cwd: Path) -> list[dict]:
    """The ralph-loop captures completed items in .kaizen/loop.state.md.
    Each completed item is a candidate to surface."""
    p = cwd / ".kaizen" / "loop.state.md"
    if not p.is_file():
        return []
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    items = []
    # Heuristic: each "- desc: ..." in the JSON body is an entry
    for m in re.finditer(r'"desc"\s*:\s*"([^"]+)"', text):
        items.append({
            "source": str(p),
            "kind": "loop",
            "text": m.group(1),
        })
    return items


# ─── Candidate extraction ────────────────────────────────────────────


# Quote-shaped patterns that signal "this is a user statement worth capturing"
_QUOTE_PATTERNS = [
    re.compile(r'"([^"]{20,500})"'),     # double-quoted
    re.compile(r"'([^']{20,500})'"),    # single-quoted
    re.compile(r"^>\s*(.{20,500})$", re.MULTILINE),  # markdown blockquote
]

# Phrases that signal explicit-capture intent
_CAPTURE_PHRASES = [
    "remember this",
    "save this",
    "for the record",
    "going forward",
    "from now on",
    "user prefers",
    "always X",
    "never Y",
    "we decided",
    "the rule is",
]


def _extract_candidates_from_text(text: str, source: str, kind: str) -> list[dict]:
    """Pull quote-shaped + phrase-marker spans out of free text."""
    out = []
    seen: set[str] = set()
    for pat in _QUOTE_PATTERNS:
        for m in pat.finditer(text):
            quote = m.group(1).strip()
            if not quote or quote in seen:
                continue
            seen.add(quote)
            out.append({
                "source": source,
                "kind": f"{kind}/quote",
                "text": quote,
            })
    for phrase in _CAPTURE_PHRASES:
        if phrase.lower() not in text.lower():
            continue
        # Surface the surrounding sentence
        m = re.search(rf"[^.\n]*{re.escape(phrase)}[^.\n]*[.\n]?", text, re.IGNORECASE)
        if m:
            span = m.group(0).strip()
            if span and span not in seen:
                seen.add(span)
                out.append({
                    "source": source,
                    "kind": f"{kind}/phrase",
                    "text": span[:500],
                })
    return out


# ─── Flow nodes ──────────────────────────────────────────────────────


class ScanSourcesNode(_flow.AsyncNode):
    """Pull recent text from multiple sources into one list."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "cwd": store.get("cwd") or Path.cwd(),
            "brain_root": store["brain_root"],
            "limit_commits": store.get("limit_commits", 10),
            "limit_inbox": store.get("limit_inbox", 20),
        }

    async def exec_async(self, prep: dict) -> list[dict]:
        sources: list[dict] = []
        sources.extend(_read_inbox_items(prep["brain_root"], prep["limit_inbox"]))
        sources.extend(_read_recent_commits(prep["cwd"], prep["limit_commits"]))
        sources.extend(_read_project_memory_drafts(prep["cwd"]))
        sources.extend(_read_loop_state(prep["cwd"]))
        return sources

    async def post_async(self, store: dict, _prep, sources: list) -> str:
        store["sources"] = sources
        return "default"


class ExtractCandidatesNode(_flow.AsyncNode):
    """Pull quote + phrase candidates out of each source's text."""

    async def prep_async(self, store: dict) -> list:
        return store.get("sources") or []

    async def exec_async(self, sources: list) -> list:
        cands = []
        for s in sources:
            cands.extend(_extract_candidates_from_text(
                s.get("text") or "", s["source"], s["kind"],
            ))
        return cands

    async def post_async(self, store: dict, _prep, candidates: list) -> str:
        store["candidates"] = candidates
        return "default"


class ClassifyNode(_flow.AsyncNode):
    """Apply _brain.detect_type to each candidate."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "candidates": store.get("candidates") or [],
            "cfg": store["cfg"],
        }

    async def exec_async(self, prep: dict) -> list:
        out = []
        for c in prep["candidates"]:
            type_name = _brain.detect_type(c["text"], prep["cfg"])
            out.append({**c, "type": type_name})
        return out

    async def post_async(self, store: dict, _prep, classified: list) -> str:
        store["classified"] = classified
        return "default"


class InboxNode(_flow.AsyncNode):
    """Write each candidate to the brain Inbox as a draft for review.

    Each candidate becomes a file at ``brain/Inbox/draft-<slug>.md``.
    The user can review the Inbox and either run ``kaizen-brain
    capture <text>`` or delete drafts they don't want."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "classified": store.get("classified") or [],
            "brain_root": store["brain_root"],
            "apply": store.get("apply", False),
        }

    async def exec_async(self, prep: dict) -> list:
        if not prep["apply"]:
            return []
        written = []
        inbox_dir = prep["brain_root"] / "Inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        today = dt.date.today().isoformat()
        # Dedup against existing inbox entries by quote text
        existing_texts: set[str] = set()
        for f in inbox_dir.glob("draft-*.md"):
            try:
                existing_texts.add(f.read_text(encoding="utf-8")[:500])
            except OSError:
                continue
        for c in prep["classified"]:
            slug = _brain.slugify(c["text"][:80])
            dest = inbox_dir / f"draft-{today}-{slug}.md"
            if dest.is_file():
                continue
            body_marker = c["text"][:500]
            if any(body_marker in et for et in existing_texts):
                continue
            content = (
                f"---\n"
                f"name: {c['text'][:80]}\n"
                f"description: {c['text'][:200]}\n"
                f"type: {c['type']}\n"
                f"source: {c['source']}\n"
                f"kind: {c['kind']}\n"
                f"created: {today}\n"
                f"---\n\n"
                f"# Draft candidate\n\n"
                f'> "{c["text"]}"\n\n'
                f"Source: `{c['source']}` ({c['kind']})\n\n"
                f"To capture, run:\n"
                f"```bash\n"
                f"kaizen-brain capture \"{c['text'][:200].replace(chr(10), ' ').replace(chr(34), chr(39))}\""
                f"{' --type ' + c['type'] if c['type'] != 'world-fact' else ''}\n"
                f"```\n"
            )
            dest.write_text(content, encoding="utf-8")
            written.append(str(dest))
        return written

    async def post_async(self, store: dict, _prep, written: list) -> str:
        store["inbox_writes"] = written
        return "default"


class ReportNode(_flow.AsyncNode):
    async def prep_async(self, store: dict) -> None:
        return None

    async def exec_async(self, _prep) -> None:
        return None

    async def post_async(self, store: dict, _prep, _exec) -> str:
        store["report"] = {
            "sources_scanned": len(store.get("sources") or []),
            "candidates": store.get("classified") or [],
            "total_candidates": len(store.get("classified") or []),
            "inbox_writes": store.get("inbox_writes") or [],
        }
        return "default"


def build_audit_flow() -> _flow.AsyncFlow:
    scan = ScanSourcesNode()
    extract = ExtractCandidatesNode()
    classify = ClassifyNode()
    inbox = InboxNode()
    report = ReportNode()
    f = _flow.AsyncFlow(scan)
    f.add_successor(scan, "default", extract)
    f.add_successor(extract, "default", classify)
    f.add_successor(classify, "default", inbox)
    f.add_successor(inbox, "default", report)
    return f


def audit(
    *,
    cwd: Optional[Path] = None,
    apply: bool = False,
    brain_root: Optional[Path] = None,
    limit_commits: int = 10,
    limit_inbox: int = 20,
) -> dict:
    return asyncio.run(_audit_async(
        cwd=cwd, apply=apply, brain_root=brain_root,
        limit_commits=limit_commits, limit_inbox=limit_inbox,
    ))


async def _audit_async(**kwargs) -> dict:
    store: dict = {
        "cwd": kwargs.get("cwd") or Path.cwd(),
        "apply": kwargs.get("apply", False),
        "brain_root": kwargs.get("brain_root") or _brain.brain_root(),
        "cfg": _brain.Config.load(),
        "limit_commits": kwargs.get("limit_commits", 10),
        "limit_inbox": kwargs.get("limit_inbox", 20),
    }
    await build_audit_flow().run_async(store)
    return store.get("report") or {}


# ─── CLI ─────────────────────────────────────────────────────────────


def _cmd_run(args) -> int:
    report = audit(
        apply=args.apply,
        limit_commits=args.limit_commits,
        limit_inbox=args.limit_inbox,
    )
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0
    print(f"[kaizen-brain-audit] {report['total_candidates']} candidate(s) "
          f"from {report['sources_scanned']} source(s)")
    print()
    for c in report["candidates"][:30]:
        print(f"  [{c['type']:<12}] {c['text'][:120]}")
        print(f"    via {c['kind']:<14} {c['source']}")
        print()
    if args.apply and report.get("inbox_writes"):
        print(f"wrote {len(report['inbox_writes'])} Inbox draft(s):")
        for w in report["inbox_writes"]:
            print(f"  - {w}")
    elif not args.apply:
        print("dry-run — re-run with --apply to write Inbox drafts.")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-brain-audit",
        description="End-of-session discovery audit — surface "
                    "non-obvious learnings worth capturing.",
    )
    p.add_argument("--apply", action="store_true",
                   help="write each candidate as a draft in brain/Inbox/")
    p.add_argument("--limit-commits", type=int, default=10)
    p.add_argument("--limit-inbox", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_run)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
