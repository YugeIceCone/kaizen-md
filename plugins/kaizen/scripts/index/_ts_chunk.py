"""kaizen ts-chunk — tree-sitter universal symbol chunker (roadmap O8 Phase 4).

Generalizes the O2 Python-AST chunker to any language with a
tree-sitter grammar (~30 languages via the ``tree_sitter_languages``
wheel). Each top-level function / class / method / struct / trait
becomes one chunk; the module prologue is the first chunk.

## Design discipline

This module DOES NOT replace ``_ast_chunk.chunk_python_by_symbol`` —
Python continues to use stdlib ``ast`` (no extra dep; 100 % accurate;
proven in production). Tree-sitter handles everything else:

  Python  → stdlib ``ast``      (via _ast_chunk)
  others  → tree-sitter         (this module)
  no-grammar / parse-fail → sentence-boundary chunker (existing
                                 ``_chunk.chunk_text`` fallback)

## Dep: tree_sitter_languages (~50 MB wheel)

Heavy. Lazy-loaded; cached after first call. When the import fails
(common case in minimal envs), every function returns ``[]`` and the
indexer falls back to sentence-boundary chunking — same graceful
degradation pattern as ``_sparse`` / ``_colbert``.

## Symbol detection heuristic

Tree-sitter node types differ per language but follow predictable
patterns. We classify a node as a "definition" when its type:

  - ends with ``_definition``, ``_declaration``, or ``_item``, OR
  - is one of an explicit per-language list (rare; the heuristic
    catches most cases without an enumeration).

This catches: function_definition, class_declaration, method_declaration,
function_item, impl_item, struct_item, enum_item, trait_item,
function_declaration, type_declaration, … across the 18+ languages
the wheel ships.

Names come from the first ``identifier`` / ``type_identifier`` /
``name``-shaped child. Anonymous functions get ``"<anonymous>"``.
"""

from __future__ import annotations

import sys
from typing import Optional

# Reuse _ast_chunk's SymbolChunk so callers can switch backends without
# unpacking different shapes — see chunk_record in onboard_index.py.
from _ast_chunk import SymbolChunk  # type: ignore  # noqa: E402

# ─── Language name normalization ─────────────────────────────────────
#
# kaizen's lang detection (in onboard_index.detect_language) uses a
# mix of common names + extensions. tree-sitter-languages expects
# canonical short names. Map kaizen → ts here.

_LANG_TO_TS = {
    "rust": "rust",
    "go": "go",
    "javascript": "javascript",
    "js": "javascript",
    "typescript": "typescript",
    "ts": "typescript",
    "tsx": "tsx",
    "jsx": "javascript",
    "c": "c",
    "c++": "cpp",
    "cpp": "cpp",
    "java": "java",
    "kotlin": "kotlin",
    "scala": "scala",
    "swift": "swift",
    "csharp": "c_sharp",
    "c_sharp": "c_sharp",
    "cs": "c_sharp",
    "php": "php",
    "ruby": "ruby",
    "rb": "ruby",
    "lua": "lua",
    "bash": "bash",
    "sh": "bash",
    "sql": "sql",
    "html": "html",
    "css": "css",
    # python — handled by _ast_chunk; here only for completeness
    "python": "python",
}

# Node-type substrings that we treat as "this is a definition we want
# to chunk on." Substring match keeps the heuristic compact across
# languages without enumerating every grammar.
_DEFINITION_HINTS = (
    "function",
    "method",
    "class",
    "struct",
    "trait",
    "impl",
    "enum",
    "interface",
    "module",
    "type_alias",
)

# Suffixes that further qualify a definition — used to avoid matching
# expressions / calls that happen to contain the words above.
_DEFINITION_SUFFIXES = (
    "_definition",
    "_declaration",
    "_item",
    "_specifier",
)

# ─── Lazy loader ──────────────────────────────────────────────────────

_ts_parsers: dict[str, object] = {}
_load_attempted = False
_ts_get_parser = None  # captured from the package import

def _resolve_ts_lang(language: str) -> Optional[str]:
    """Map a kaizen language label to a tree-sitter grammar name."""
    if not language:
        return None
    return _LANG_TO_TS.get(language.lower())

def _get_parser(ts_lang: str):
    """Lazy-load a tree-sitter parser for the named grammar. Returns
    ``None`` when the package can't be imported or the grammar is
    unknown.

    Tries ``tree_sitter_languages`` first (older, smaller wheel); falls
    back to ``tree_sitter_language_pack`` (newer fork with more
    grammars) when available. Either is fine — we only call
    ``get_parser(name)`` on whichever loaded."""
    global _load_attempted, _ts_get_parser
    if not _load_attempted:
        _load_attempted = True
        try:
            from tree_sitter_languages import get_parser as _gp  # type: ignore
            _ts_get_parser = _gp
        except ImportError:
            try:
                from tree_sitter_language_pack import get_parser as _gp  # type: ignore
                _ts_get_parser = _gp
            except ImportError:
                _ts_get_parser = None
    if _ts_get_parser is None:
        return None
    if ts_lang in _ts_parsers:
        return _ts_parsers[ts_lang]
    try:
        parser = _ts_get_parser(ts_lang)
    except Exception as e:
        sys.stderr.write(
            f"kaizen ts-chunk: failed to load parser for {ts_lang}: "
            f"{type(e).__name__}: {e}\n"
        )
        _ts_parsers[ts_lang] = None  # type: ignore
        return None
    _ts_parsers[ts_lang] = parser
    return parser

def reset_cache() -> None:
    """Clear the cached parser map. Used by tests."""
    global _ts_parsers, _load_attempted, _ts_get_parser
    _ts_parsers = {}
    _load_attempted = False
    _ts_get_parser = None

def is_available() -> bool:
    """Returns True iff at least one tree-sitter package is importable.

    Cheap probe — does NOT require any grammar to load successfully."""
    global _load_attempted
    if not _load_attempted:
        # Trigger the import-attempt without resolving a specific lang.
        _get_parser("__probe__")
    return _ts_get_parser is not None

# ─── Node classification ─────────────────────────────────────────────

def _is_definition_node(node_type: str) -> bool:
    """Heuristic: does this node type represent a chunk-worthy
    definition? Matches names like 'function_definition',
    'class_declaration', 'function_item', 'impl_item' across the
    18+ grammars supported by the languages wheels."""
    if not node_type:
        return False
    lower = node_type.lower()
    if any(lower.endswith(sfx) for sfx in _DEFINITION_SUFFIXES):
        return True
    # Some grammars use bare type names (e.g. ruby's 'method', 'class')
    return any(hint == lower for hint in _DEFINITION_HINTS)

def _extract_symbol_name(node) -> str:
    """Walk a definition node's children to find its name. Looks for
    the first identifier / type_identifier / name node. Returns
    ``'<anonymous>'`` when none found (e.g. lambda / arrow fn)."""
    for child in node.children:
        ct = (child.type or "").lower()
        if ct in {"identifier", "type_identifier", "name", "constant"}:
            try:
                return child.text.decode("utf-8", errors="replace")
            except (AttributeError, UnicodeDecodeError):
                return "<anonymous>"
    # Recurse one level — many grammars wrap the name in a parent node
    # (e.g. JS `function_declaration → name → identifier`).
    for child in node.children:
        for grand in child.children:
            gt = (grand.type or "").lower()
            if gt in {"identifier", "type_identifier", "name", "constant"}:
                try:
                    return grand.text.decode("utf-8", errors="replace")
                except (AttributeError, UnicodeDecodeError):
                    return "<anonymous>"
    return "<anonymous>"

# ─── Public chunker ──────────────────────────────────────────────────

def chunk_source_by_symbol(
    source: str,
    language: str,
    *,
    max_chars: int = 4000,
) -> list[SymbolChunk]:
    """Universal symbol-aware chunker. Returns ``[]`` when:

      - language unmapped (no tree-sitter grammar known), OR
      - tree_sitter_languages / tree_sitter_language_pack absent, OR
      - parsing fails / produces no top-level definitions.

    Callers should fall back to the generic sentence-boundary chunker
    on empty return — same contract as ``_ast_chunk.chunk_python_by_symbol``.

    Per-symbol chunks include a 'module' chunk for the prologue
    (everything before the first definition) when non-empty.

    max_chars is a SOFT cap — definitions longer than that are still
    emitted as a single chunk (splitting at sub-statement boundaries
    is grammar-specific; we accept the larger chunk over fragmenting
    semantically meaningful units)."""
    ts_lang = _resolve_ts_lang(language)
    if ts_lang is None or ts_lang == "python":
        # Python handled by _ast_chunk; everything else needs ts.
        return []
    parser = _get_parser(ts_lang)
    if parser is None:
        return []
    src_bytes = source.encode("utf-8")
    try:
        tree = parser.parse(src_bytes)
    except Exception:
        return []
    root = tree.root_node
    if root is None or root.child_count == 0:
        return []

    # Collect top-level definitions (one level of nesting — children of
    # the root only; methods inside a class go with the class).
    defs = [c for c in root.children if _is_definition_node(c.type)]
    if not defs:
        return []

    chunks: list[SymbolChunk] = []
    chunk_idx = 0

    # Module prologue: bytes 0 .. first_def.start_byte
    first_def_start = defs[0].start_byte
    if first_def_start > 0:
        prologue_text = src_bytes[:first_def_start].decode(
            "utf-8", errors="replace"
        )
        if prologue_text.strip():
            chunks.append(SymbolChunk(
                text=prologue_text,
                char_start=0,
                char_end=first_def_start,
                chunk_idx=chunk_idx,
                symbol_name="<module>",
                kind="module",
            ))
            chunk_idx += 1

    # One chunk per top-level definition.
    for node in defs:
        start, end = node.start_byte, node.end_byte
        text = src_bytes[start:end].decode("utf-8", errors="replace")
        if not text.strip():
            continue
        name = _extract_symbol_name(node)
        kind = _classify_kind(node.type)
        chunks.append(SymbolChunk(
            text=text,
            char_start=start,
            char_end=end,
            chunk_idx=chunk_idx,
            symbol_name=name,
            kind=kind,
        ))
        chunk_idx += 1

    return chunks

def _classify_kind(node_type: str) -> str:
    """Bucket a tree-sitter node type into one of:
    'function' | 'method' | 'class' | 'struct' | 'trait' | 'impl' |
    'enum' | 'interface' | 'module' | 'block'. Falls back to 'block'."""
    if not node_type:
        return "block"
    lower = node_type.lower()
    for label in (
        "function", "method", "class", "struct", "trait", "impl",
        "enum", "interface", "module",
    ):
        if label in lower:
            return label if label != "impl" else "impl"
    return "block"

# ─── CLI inspector ────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        description="Inspect kaizen tree-sitter chunker output."
    )
    p.add_argument("file", help="source file to chunk")
    p.add_argument(
        "--language",
        help="override language (default: derived from extension)",
    )
    args = p.parse_args()
    from pathlib import Path
    path = Path(args.file)
    if not path.is_file():
        sys.exit(f"not a file: {path}")
    source = path.read_text(encoding="utf-8", errors="replace")
    language = args.language
    if language is None:
        ext = path.suffix.lstrip(".")
        # Mapping copied from onboard_index.detect_language for the
        # common cases; CLI users can pass --language to override.
        language = {
            "rs": "rust", "go": "go", "js": "javascript", "ts": "typescript",
            "py": "python", "rb": "ruby", "java": "java",
        }.get(ext, ext)
    if not is_available():
        sys.exit(
            "kaizen-ts-chunk: tree_sitter_languages required.\n"
            "  pip install --user tree_sitter_languages\n"
            "or\n"
            "  pip install --user tree_sitter_language_pack\n"
        )
    chunks = chunk_source_by_symbol(source, language)
    if not chunks:
        print(f"no chunks produced for {path} (lang={language})")
        sys.exit(0)
    for c in chunks:
        print(f"  [{c.chunk_idx}] {c.kind} {c.symbol_name} "
              f"({c.char_start}..{c.char_end}, {len(c.text)}b)")
