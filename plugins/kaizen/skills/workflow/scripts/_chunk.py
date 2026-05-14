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
# E1 — Model-aware asymmetric prefix detection.
#
# Different embedding models expect different query/passage markers:
#   nomic-embed*       query="search_query: "        passage="search_document: "
#   bge-*              query="Represent this..."     passage=""
#   e5-*               query="query: "               passage="passage: "
#   jina-embed*        query=""                      passage=""
#   gte-qwen*          query="Instruct: ...\nQuery:" passage=""
#   minilm / generic   nomic-compatible (tolerated by most)
#
# DEFAULT_QUERY_PREFIX / DEFAULT_PASSAGE_PREFIX = nomic family (most common
# in kaizen's stack — used by `all-MiniLM-L6-v2` defaults). The legacy
# module-level constants `QUERY_PREFIX` / `PASSAGE_PREFIX` alias to these
# for back-compat with callers (embed-rerank MCP, ad-hoc importers).

_BGE_QUERY = "Represent this sentence for searching relevant passages: "
_E5_QUERY = "query: "
_E5_PASSAGE = "passage: "
_GTE_QWEN_QUERY = (
    "Instruct: Given a query, retrieve passages that answer it\nQuery: "
)
_NOMIC_QUERY = "search_query: "
_NOMIC_PASSAGE = "search_document: "

MODEL_PREFIXES: dict[str, tuple[str, str]] = {
    "nomic":    (_NOMIC_QUERY, _NOMIC_PASSAGE),
    "bge":      (_BGE_QUERY, ""),
    "e5":       (_E5_QUERY, _E5_PASSAGE),
    "jina":     ("", ""),
    "gte-qwen": (_GTE_QWEN_QUERY, ""),
    "generic":  (_NOMIC_QUERY, _NOMIC_PASSAGE),  # safe default for unknown
}

# Back-compat aliases — default-model (nomic) prefixes.
QUERY_PREFIX = _NOMIC_QUERY
PASSAGE_PREFIX = _NOMIC_PASSAGE


def detect_model_family(model: str) -> str:
    """Substring-match the model name against known embedding families.

    Returns one of the MODEL_PREFIXES keys. Empty/unknown models map to
    'generic' (which currently uses nomic-style prefixes — the most
    widely tolerated default)."""
    if not model:
        return "generic"
    m = model.lower()
    if "nomic" in m or "minilm" in m or "mxbai" in m:
        return "nomic"  # minilm + mxbai tolerate nomic prefixes
    if "bge" in m:
        return "bge"
    if "gte-qwen" in m or ("qwen" in m and "embed" in m):
        return "gte-qwen"
    if "e5" in m:
        return "e5"
    if "jina" in m:
        return "jina"
    return "generic"


def prefixes_for_model(model: str) -> tuple[str, str]:
    """Return (query_prefix, passage_prefix) for the model. Tuple shape
    is stable; an empty string indicates "no prefix for this slot"."""
    return MODEL_PREFIXES[detect_model_family(model)]


def apply_query_prefix(text: str, model: str = "") -> str:
    """Prepend the model's query prefix. Idempotent: if `text` already
    starts with any known query prefix, it is returned unchanged.

    Empty prefix (e.g. jina) means no transformation."""
    q_pref, _ = prefixes_for_model(model)
    if not q_pref:
        return text
    # Idempotence guard — already-prefixed text passes through. Check
    # against ALL known query prefixes so cross-model batches don't
    # double-prefix.
    for q, _ in MODEL_PREFIXES.values():
        if q and text.startswith(q):
            return text
    return q_pref + text


def apply_passage_prefix(text: str, model: str = "") -> str:
    """Prepend the model's passage prefix. Same idempotence rules as
    apply_query_prefix."""
    _, p_pref = prefixes_for_model(model)
    if not p_pref:
        return text
    for _, p in MODEL_PREFIXES.values():
        if p and text.startswith(p):
            return text
    return p_pref + text


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
    """Prepend metadata + the model-aware passage prefix.

    Order: model's passage prefix first (if non-empty — see E1 family
    detection), then the metadata lines, then the original text.
    Idempotent: already-prefixed text passes through unchanged.

    `model=""` uses the nomic-family default (PASSAGE_PREFIX) for
    back-compat with pre-E1 callers."""
    # Idempotence — check ALL known passage prefixes (cross-model safe)
    for _, p in MODEL_PREFIXES.values():
        if p and text.startswith(p):
            return text
    _, p_pref = prefixes_for_model(model)
    meta = build_metadata_prefix(
        path=path, language=language, kind=kind, symbol=symbol
    )
    return p_pref + meta + text


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
