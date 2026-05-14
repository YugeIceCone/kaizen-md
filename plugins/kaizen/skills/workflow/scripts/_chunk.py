"""kaizen chunker — sentence-boundary chunking for RAG (v1.27.0+).

Ported from Onyx's `backend/onyx/indexing/chunker.py` chunking discipline,
minus the chonkie dep (we use pure-Python regex sentence splitting).

## Design choices (mirrored from Onyx)

- **512-token cap** (`DEFAULT_TOKEN_CAP`) — matches Onyx's
  `DOC_EMBEDDING_CONTEXT_SIZE`. Most embedding models cap input around
  here; nomic-embed-v2 supports 8K but quality is best at ~512.
- **Zero overlap** (`DEFAULT_OVERLAP = 0`) — Onyx's `CHUNK_OVERLAP = 0`,
  with explicit code comment: "we need a clean combination of chunks
  and it is unclear if overlaps actually help quality at all."
- **Char-offset `source_links`** — each chunk carries its
  `(char_start, char_end)` back to the source document, exactly like
  Onyx's `Chunk.source_links: dict[int, str]`. We simplify to a
  per-chunk pair (the kaizen use case has one document per chunk).
- **Sentence-aware** — split on `[.!?]\\s+` plus double-newlines (a
  strong boundary in code + docs). Respect a small abbreviation list
  to reduce false-positive splits.

## Why not chonkie / tiktoken?

Stdlib-only by policy. Char-based token approximation (1 token ≈ 4
chars for English) is the same heuristic OpenAI uses for rough sizing.
For an exact count, install tiktoken and set
`KAIZEN_CHUNK_TOKENIZER=tiktoken` (TODO — not wired yet).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

# ─── Tunables (env-overridable in _cfg if we want later) ──────────────

DEFAULT_TOKEN_CAP = 512  # Onyx's DOC_EMBEDDING_CONTEXT_SIZE
DEFAULT_OVERLAP = 0       # Onyx's CHUNK_OVERLAP
CHARS_PER_TOKEN = 4       # rough English heuristic

# Boundary patterns: sentence terminator + whitespace OR a paragraph
# break (double newline). Capturing nothing — just locating end positions.
_BOUNDARY = re.compile(r"(?:[.!?]\s+|\n{2,})")

# Words that look like sentence-ends but aren't.
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "inc", "ltd", "co", "corp",
    "etc", "e.g", "i.e", "vs", "fig", "st", "ave", "jr", "sr",
}


@dataclass(frozen=True)
class Chunk:
    """A semantic unit of text with char-offset back to the source.

    The `(char_start, char_end)` pair is the citation handle: at
    answer-render time you can `source[chunk.char_start:chunk.char_end]`
    or compute file:line from the offset."""
    text: str
    char_start: int
    char_end: int
    chunk_idx: int  # 0..N-1 within the source document


# ─── Sentence splitter ───────────────────────────────────────────────


def _is_false_boundary(text: str, end_pos: int) -> bool:
    """Was the last 'word' before end_pos an abbreviation?

    Cheap check: walk back to the previous whitespace, lowercase, strip
    trailing punctuation, compare against the abbreviation set."""
    # end_pos points just past a [.!?]\s+ boundary; the [.!?] is at end_pos-2 or earlier
    # Walk back to find the start of the word containing the period.
    i = end_pos - 1
    while i > 0 and not text[i - 1].isspace():
        i -= 1
    word = text[i:end_pos].rstrip()
    word = word.rstrip(".!?")  # the punctuation that triggered the match
    return word.lower() in _ABBREVIATIONS


# ─── Chunker ─────────────────────────────────────────────────────────


def chunk_text(
    text: str,
    max_tokens: int = DEFAULT_TOKEN_CAP,
    overlap_tokens: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Split `text` into chunks of at most `max_tokens` tokens.

    Sentence boundaries are preferred breakpoints; if a sentence pushes
    the current chunk past the cap, the chunk flushes at the last good
    boundary. Single sentences longer than the cap are emitted as their
    own chunk (no mid-sentence splitting — semantic unit preserved).

    Returns [] for empty / whitespace-only input.
    """
    if not text or not text.strip():
        return []

    max_chars = max_tokens * CHARS_PER_TOKEN

    # Tiny doc: one chunk.
    if len(text) <= max_chars:
        return [Chunk(text=text.strip(), char_start=0,
                      char_end=len(text), chunk_idx=0)]

    # Collect sentence-end positions.
    boundaries: list[int] = [0]
    for m in _BOUNDARY.finditer(text):
        end = m.end()
        # Filter false boundaries from abbreviations.
        if _is_false_boundary(text, m.start() + 1):
            continue
        boundaries.append(end)
    if boundaries[-1] != len(text):
        boundaries.append(len(text))

    # Greedy packing: walk boundaries, flush when current chunk would
    # exceed max_chars.
    chunks: list[Chunk] = []
    chunk_start = 0
    last_safe_break = 0
    for b in boundaries[1:]:
        if b - chunk_start > max_chars:
            # Flush at the last safe boundary, or at b if no boundary
            # has been seen yet (single mega-sentence).
            end = last_safe_break if last_safe_break > chunk_start else b
            chunk_body = text[chunk_start:end]
            stripped = chunk_body.strip()
            if stripped:
                chunks.append(Chunk(
                    text=stripped,
                    char_start=chunk_start,
                    char_end=end,
                    chunk_idx=len(chunks),
                ))
            chunk_start = end
        last_safe_break = b

    # Tail.
    if chunk_start < len(text):
        tail = text[chunk_start:]
        stripped = tail.strip()
        if stripped:
            chunks.append(Chunk(
                text=stripped,
                char_start=chunk_start,
                char_end=len(text),
                chunk_idx=len(chunks),
            ))

    return chunks


def chunk_into_dicts(
    text: str,
    max_tokens: int = DEFAULT_TOKEN_CAP,
) -> list[dict]:
    """Convenience: chunk_text but return plain dicts for SQLite-friendly
    storage. Keys: text, char_start, char_end, chunk_idx."""
    return [
        {"text": c.text, "char_start": c.char_start,
         "char_end": c.char_end, "chunk_idx": c.chunk_idx}
        for c in chunk_text(text, max_tokens=max_tokens)
    ]


# ─── Asymmetric prefixes (v1.27.0 borrows Onyx default) ──────────────

# nomic-embed-v2, bge-*, e5-* all benefit from these prefixes — they
# distinguish "I'm encoding a query" from "I'm encoding a passage".
# For models that don't care (MiniLM), the prefix is just extra tokens
# the model ignores; quality regression is minimal.
QUERY_PREFIX = "search_query: "
PASSAGE_PREFIX = "search_document: "


def apply_query_prefix(text: str, model: str = "") -> str:
    """Prepend the asymmetric query prefix if the model is known to
    benefit. Right now: applies unconditionally (nomic/bge/e5 are common
    and others are tolerant)."""
    if text.startswith(QUERY_PREFIX):
        return text
    return QUERY_PREFIX + text


def apply_passage_prefix(text: str, model: str = "") -> str:
    """Same shape for passages."""
    if text.startswith(PASSAGE_PREFIX):
        return text
    return PASSAGE_PREFIX + text


def apply_passage_prefix_batch(texts: Iterable[str], model: str = "") -> list[str]:
    return [apply_passage_prefix(t, model) for t in texts]


# ─── O3 (v1.32) — metadata-rich passage prefix ───────────────────────


def build_metadata_prefix(
    *,
    path: str = "",
    language: str = "",
    kind: str = "",
    symbol: str = "",
) -> str:
    """Build a ~30-token provenance preamble for a passage embedding.

    The embedding model learns associations between the metadata lines
    and the chunk content, which improves both same-file recall ("find
    chunks from x.py") and kind-discrimination ("prefer docstrings for
    why queries"). Empty fields are skipped so the prefix stays compact.

    Shape:
        file: <path>
        language: <lang>
        kind: <code|doc>
        symbol: <name>
        ---
    """
    lines: list[str] = []
    if path:
        lines.append(f"file: {path}")
    if language:
        lines.append(f"language: {language}")
    if kind:
        lines.append(f"kind: {kind}")
    if symbol:
        lines.append(f"symbol: {symbol}")
    if not lines:
        return ""
    return "\n".join(lines) + "\n---\n"


def apply_passage_prefix_with_metadata(
    text: str,
    *,
    path: str = "",
    language: str = "",
    kind: str = "",
    symbol: str = "",
    model: str = "",
) -> str:
    """Prepend metadata + the model-aware search_document: prefix.

    Order: search_document: marker first (so the model sees its asymmetric
    cue immediately), then the metadata lines, then the original text. If
    the input already starts with PASSAGE_PREFIX it is preserved unchanged
    (idempotent re-application)."""
    if text.startswith(PASSAGE_PREFIX):
        return text
    meta = build_metadata_prefix(
        path=path, language=language, kind=kind, symbol=symbol
    )
    return PASSAGE_PREFIX + meta + text


def apply_passage_prefix_batch_with_metadata(
    items: Iterable[dict],
    model: str = "",
) -> list[str]:
    """Batch variant. Each `item` is a chunk dict with keys: text, path,
    language, kind (optional), symbol (optional). Returns the prefixed
    text per item, in input order."""
    return [
        apply_passage_prefix_with_metadata(
            it["text"],
            path=it.get("path", ""),
            language=it.get("language", ""),
            kind=it.get("kind", ""),
            symbol=it.get("symbol", ""),
            model=model,
        )
        for it in items
    ]
