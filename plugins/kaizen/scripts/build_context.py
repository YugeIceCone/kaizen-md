"""kaizen build_context — capture-context builder.

Port of upstream build-context.js. Builds the capture-routing context
that user_prompt.py injects into Claude via UserPromptSubmit when a
brain-dump keyword is detected.

Reads the plugin's default REMEMBER.md.template plus the user's
REMEMBER.md (brain root + cwd) and merges them per-section:
- Sections matching a default name APPEND to the default.
- Sections named "Override: <name>" REPLACE the matching default.
- Sections that don't match any default pass through as user-extras.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import sys
from pathlib import Path

_OVERRIDE_PREFIX_RE = re.compile(r"^override:\s*", re.IGNORECASE)
_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)

def parse_sections(text: str) -> list[dict]:
    """Parse ``## Section Name`` blocks. Returns ordered list of
    ``{name, content}`` dicts. Content excludes header + is trimmed."""
    if not text:
        return []
    sections: list[dict] = []
    matches = list(_HEADER_RE.finditer(text))
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        sections.append({"name": name, "content": content})
    return sections

def _read_safe(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""

def _normalize(name: str) -> str:
    return name.lower().strip()

def merge_sections(plugin_sections: list[dict],
                   user_sections: list[dict]) -> tuple[list[dict], list[dict]]:
    """Merge plugin defaults with user sections.

    Returns ``(merged, extras)`` — merged preserves plugin-section
    order; extras are user sections not matching any default.
    """
    plugin_by_name = {_normalize(s["name"]): s for s in plugin_sections}
    appends: dict[str, list[str]] = {}
    overrides: dict[str, str] = {}
    extras: list[dict] = []

    for u in user_sections:
        override_match = _OVERRIDE_PREFIX_RE.match(u["name"])
        if override_match:
            target = _OVERRIDE_PREFIX_RE.sub("", u["name"]).strip()
            key = _normalize(target)
            if key in plugin_by_name:
                overrides[key] = u["content"]
            else:
                extras.append({"name": target, "content": u["content"]})
            continue
        key = _normalize(u["name"])
        if key in plugin_by_name:
            appends.setdefault(key, []).append(u["content"])
        else:
            extras.append({"name": u["name"], "content": u["content"]})

    merged: list[dict] = []
    for s in plugin_sections:
        key = _normalize(s["name"])
        if key in overrides:
            merged.append({
                "name": s["name"],
                "content": overrides[key],
                "source": "override",
            })
            continue
        ap = appends.get(key)
        if ap:
            blocks = [b for b in [s["content"], *ap] if b]
            merged.append({
                "name": s["name"],
                "content": "\n\n".join(blocks),
                "source": "append",
            })
            continue
        merged.append({
            "name": s["name"],
            "content": s["content"],
            "source": "default",
        })
    return merged, extras

def render_sections(sections: list[dict]) -> str:
    """Render a list of ``{name, content}`` dicts as concatenated
    ``## Name\\n<content>`` blocks. Drops empty content."""
    out_blocks: list[str] = []
    for s in sections:
        content = (s.get("content") or "").strip()
        if not content:
            continue
        out_blocks.append(f"## {s['name']}\n{content}")
    return "\n\n".join(out_blocks)

def build_capture_context(
    brain: Path,
    plugin_root: Path,
    cwd: Path | None = None,
    today: str | None = None,
) -> str:
    """Build the full capture-context payload for UserPromptSubmit.

    Composed of: header + brain index summary + merged REMEMBER.md
    rulebook + any extra user sections. The brain index summary is
    a best-effort stat — when build_index/_brain is unavailable, falls
    back to a placeholder.
    """
    date_str = today or _dt.date.today().isoformat()
    cwd = cwd or Path.cwd()

    # Brain index summary (best-effort — falls back gracefully).
    # Primary: brain_md_index (markdown entity inventory; mirrors upstream
    # build-index.js::formatCompact). Better for capture routing because
    # the LLM gets actual entity names (People / Projects / Areas / Notes)
    # to attach captures to. Fallback: build_index semantic stats — kept
    # as a graceful-degradation path when brain_md_index can't load.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent / "brain"))
        from brain_md_index import format_compact as _fmt_compact
        compact_index = _fmt_compact(brain)
    except Exception:  # noqa: BLE001
        try:
            from build_index import do_stats as _do_stats
            stats = _do_stats()
            compact_index = (
                f"BRAIN INDEX ({brain})\n"
                f"  total notes: {stats.get('total', 0)}\n"
                f"  by type: {stats.get('by_type', {})}"
            )
        except Exception:  # noqa: BLE001
            compact_index = f"BRAIN INDEX ({brain})\n(index unavailable)"

    # Plugin defaults — REMEMBER.md.template (or REMEMBER.md if present)
    plugin_rulebook_path = plugin_root / "REMEMBER.md"
    if not plugin_rulebook_path.is_file():
        plugin_rulebook_path = plugin_root / "REMEMBER.md.template"
    plugin_text = _read_safe(plugin_rulebook_path).replace("{{TODAY}}", date_str)
    plugin_sections = parse_sections(plugin_text)

    # User REMEMBER.md(s) — brain root + cwd, dedupe by resolved path.
    seen = {(plugin_rulebook_path).resolve()}
    user_texts: list[str] = []
    for candidate in (brain / "REMEMBER.md", cwd / "REMEMBER.md"):
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        t = _read_safe(resolved)
        if t:
            user_texts.append(t)
    user_sections: list[dict] = []
    for t in user_texts:
        user_sections.extend(parse_sections(t))

    merged, extras = merge_sections(plugin_sections, user_sections)
    rulebook = render_sections(merged)
    extras_block = (
        f"\n\n## User-defined sections (no matching default)\n\n"
        f"{render_sections(extras)}"
    ) if extras else ""

    header = (
        f"BRAIN DUMP — capture routing rulebook. "
        f"Brain: {brain}. Today: {date_str}."
    )
    return f"{header}\n\n{compact_index}\n\n{rulebook}{extras_block}\n"

__all__ = [
    "parse_sections",
    "merge_sections",
    "render_sections",
    "build_capture_context",
]
