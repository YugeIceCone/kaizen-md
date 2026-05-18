#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "tree-sitter>=0.23",
#   "tree-sitter-rust>=0.23",
#   "tree-sitter-python>=0.23",
# ]
# ///
"""Tree-sitter slot extractor for kaizen-tokens.

T3 — pure-fn (file path + bytes + language) → ordered Slot list:

  Slot 0 = whole-body              (kind="body", name=None, parent="")
  Slot 1 = file path string        (kind="path", name=None, parent="")
  Slot 2..N = AST top-level items in source order
             (Rust: function_item, struct_item; Python: function_definition,
              class_definition; Python class methods nest one level for V32
              parent_qualifier)

Inline-body cap = 4096 bytes; anything larger gets `body=None` and callers
read by byte offsets at fetch time (V8 / spec).

The PEP-723 header mirrors `_token_db.py` so this script runs under
`uv run --script` with all 3 grammars pre-installed. Downstream consumers
(T4 CLI dispatcher, T5 MCP server, T6 watcher) import this module from
inside the same uv venv.

Private helper (underscore-prefixed) — exempt from `bin-wrapper-per-cli`
iron-law. Pure helpers (`is_extractable`, `normalize_lf`, `detect_language`)
are stdlib-only so callers without the uv venv can still import them; only
`extract_slots` needs tree-sitter.

Spec: docs/2026-05-18-positional-token-schema-design.md (V21/V22/V23/V32/V49).
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional

from _token_db import Slot

__all__ = [
    "is_extractable",
    "normalize_lf",
    "detect_language",
    "extract_slots",
]


# ─── Exclusions (V21/V22) ────────────────────────────────────────────

_EXCLUDED_DIR_RE = re.compile(
    r"(^|/)(target|node_modules|\.venv|__pycache__|dist|build|\.git|"
    r"\.cargo|\.cache)(/|$)"
)
_EXCLUDED_FILE_RE = re.compile(r"\.(swp|tmp|bak|pyc)$|~$")


def is_extractable(path: Path) -> bool:
    """V21/V22: skip build outputs, VCS metadata, swap/backup files."""
    s = str(path)
    if _EXCLUDED_DIR_RE.search(s):
        return False
    if _EXCLUDED_FILE_RE.search(s):
        return False
    return True


# ─── Line-ending normalization (V23) ─────────────────────────────────


def normalize_lf(data: bytes) -> bytes:
    r"""Replace \r\n with \n. Stabilizes content_hash across Windows checkouts."""
    return data.replace(b"\r\n", b"\n")


# ─── Language detection ──────────────────────────────────────────────

_LANG_BY_EXT = {".rs": "rust", ".py": "python"}


def detect_language(path: Path) -> Optional[str]:
    """Phase 1: Rust + Python only. Returns None for unknown extensions."""
    return _LANG_BY_EXT.get(path.suffix)


# ─── Grammar loaders (lazy — first call pays the import cost) ────────

_PARSER_CACHE: dict = {}


def _get_parser(language: str):
    """Lazy-build + cache a tree-sitter Parser for `language`.

    Tree-sitter imports happen ONLY when actually invoked, so the pure-
    helper test path stays stdlib-clean.
    """
    if language in _PARSER_CACHE:
        return _PARSER_CACHE[language]
    import tree_sitter
    if language == "rust":
        import tree_sitter_rust
        lang = tree_sitter.Language(tree_sitter_rust.language())
    elif language == "python":
        import tree_sitter_python
        lang = tree_sitter.Language(tree_sitter_python.language())
    else:
        return None
    parser = tree_sitter.Parser(lang)
    _PARSER_CACHE[language] = parser
    return parser


# ─── Slot extraction ─────────────────────────────────────────────────

_INLINE_BODY_CAP = 4096


def _hash_hex(data: bytes) -> str:
    """Phase 1: sha256[:32] (blake3 wheel deferred — see _token_db.py)."""
    return hashlib.sha256(data).hexdigest()[:32]


def extract_slots(
    path: Path, body: bytes, language: Optional[str],
) -> list[Slot]:
    """Pure fn: file body → ordered slot list.

    Slot 0 = whole file body (normalized for hash, raw for offsets).
    Slot 1 = file path string as utf-8 bytes.
    Slots 2..N = AST top-level items in source order (per language).
    V49 fallback: when `language is None` or grammar missing, returns
    just slots 0 + 1.
    """
    out: list[Slot] = []

    # Slot 0 — whole body
    body_norm = normalize_lf(body)
    out.append(Slot(
        slot=0, kind="body", name=None, parent="",
        byte_start=0, byte_end=len(body),
        body=body_norm if len(body_norm) < _INLINE_BODY_CAP else None,
        content_hash=_hash_hex(body_norm),
    ))

    # Slot 1 — file path
    path_bytes = str(path).encode("utf-8")
    out.append(Slot(
        slot=1, kind="path", name=None, parent="",
        byte_start=0, byte_end=len(path_bytes),
        body=path_bytes,
        content_hash=_hash_hex(path_bytes),
    ))

    # V49 — no grammar → body + path only
    parser = _get_parser(language) if language else None
    if parser is None:
        return out

    tree = parser.parse(body)
    root = tree.root_node
    slot_idx = 2

    if language == "rust":
        for node in root.children:
            kind, name, parent = _rust_node_meta(node, body)
            if kind:
                snippet = body[node.start_byte:node.end_byte]
                out.append(Slot(
                    slot=slot_idx, kind=kind, name=name, parent=parent,
                    byte_start=node.start_byte, byte_end=node.end_byte,
                    body=snippet if len(snippet) < _INLINE_BODY_CAP else None,
                    content_hash=_hash_hex(snippet),
                ))
                slot_idx += 1

    elif language == "python":
        for node in root.children:
            kind, name, parent = _py_node_meta(node, body, parent="")
            if kind:
                snippet = body[node.start_byte:node.end_byte]
                out.append(Slot(
                    slot=slot_idx, kind=kind, name=name, parent=parent,
                    byte_start=node.start_byte, byte_end=node.end_byte,
                    body=snippet if len(snippet) < _INLINE_BODY_CAP else None,
                    content_hash=_hash_hex(snippet),
                ))
                slot_idx += 1
            # V32 — recurse into class body for methods (parent_qualifier)
            if node.type == "class_definition":
                cname = _py_identifier(node, body) or ""
                for child in (n for n in node.children if n.type == "block"):
                    for inner in child.children:
                        ik, iname, _ = _py_node_meta(inner, body, parent=cname)
                        if ik:
                            snippet = body[inner.start_byte:inner.end_byte]
                            out.append(Slot(
                                slot=slot_idx, kind=ik, name=iname,
                                parent=cname,
                                byte_start=inner.start_byte,
                                byte_end=inner.end_byte,
                                body=snippet if len(snippet) < _INLINE_BODY_CAP else None,
                                content_hash=_hash_hex(snippet),
                            ))
                            slot_idx += 1

    return out


# ─── Per-language node meta extractors ───────────────────────────────


def _rust_node_meta(
    node, body: bytes,
) -> tuple[Optional[str], Optional[str], str]:
    """Rust: function_item → fn; struct_item → struct; /// → comment."""
    if node.type == "function_item":
        return ("fn", _rust_identifier(node, body), "")
    if node.type == "struct_item":
        return ("struct", _rust_identifier(node, body), "")
    if node.type == "impl_item":
        # impl method extraction deferred — phase 1 keeps it simple
        return (None, None, "")
    if (
        node.type == "line_comment"
        and body[node.start_byte:node.start_byte + 3] == b"///"
    ):
        return ("comment", None, "")
    return (None, None, "")


def _rust_identifier(node, body: bytes) -> Optional[str]:
    for child in node.children:
        if child.type in ("identifier", "type_identifier"):
            return body[child.start_byte:child.end_byte].decode("utf-8")
    return None


def _py_node_meta(
    node, body: bytes, parent: str,
) -> tuple[Optional[str], Optional[str], str]:
    """Python: function_definition → fn; class_definition → struct."""
    if node.type == "function_definition":
        return ("fn", _py_identifier(node, body), parent)
    if node.type == "class_definition":
        return ("struct", _py_identifier(node, body), parent)
    return (None, None, parent)


def _py_identifier(node, body: bytes) -> Optional[str]:
    for child in node.children:
        if child.type == "identifier":
            return body[child.start_byte:child.end_byte].decode("utf-8")
    return None


# ─── __main__ — JSON-dump probe for cross-venv subprocess tests ──────


def _main_test() -> int:
    """Read {path, body_hex, language} JSON from stdin, run extract_slots,
    dump slot list as JSON to stdout. Used by tests/test_token_extractor.py
    to exercise the tree-sitter path from system-python (uv venv only loads
    when this script is invoked via `uv run --script ... --test`).
    """
    import dataclasses
    import json
    import sys

    payload = json.loads(sys.stdin.read())
    body = bytes.fromhex(payload["body_hex"])
    slots = extract_slots(
        Path(payload["path"]),
        body,
        payload.get("language"),
    )
    # Slot dataclass has a `bytes` field; coerce for JSON.
    serializable = []
    for s in slots:
        d = dataclasses.asdict(s)
        if d["body"] is not None:
            d["body"] = d["body"].hex()
        serializable.append(d)
    print(json.dumps(serializable))
    return 0


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        raise SystemExit(_main_test())
    # Default probe — confirm uv venv has the 3 deps (same as _token_db.py).
    import tree_sitter        # noqa: F401
    import tree_sitter_rust   # noqa: F401
    import tree_sitter_python # noqa: F401
    print("_token_extractor.py: deps OK")
