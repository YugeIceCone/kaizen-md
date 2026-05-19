"""kaizen smart file-level summary — roadmap O5 (Phase 3 polish).

Replaces the prior ``cleaned[:SNIPPET_MAX]`` (first 2 KB verbatim) with
a denser semantic summary: top-level imports, function / method /
class signatures, and the first line of each docstring. Same byte
budget; ~10x the symbol density for file-level embedding + display.

## Output shape

::

    imports: os, sys, json, ...

    def foo(x: int) -> str:
        \"\"\"First line of foo's docstring.\"\"\"

    def bar(y):

    class MyClass(Base):
        \"\"\"First line of MyClass's docstring.\"\"\"
        def method1(self, a):
        def method2(self):

The first docstring line follows each signature (PEP 257 short form);
the rest of the docstring is dropped to keep the summary terse. When
no docstring is present, just the bare signature is emitted.

## Language coverage

  Python  →  stdlib ``ast`` walk (100 % accurate)
  Other   →  tree-sitter symbol chunks (first line of each definition)
  Neither →  first ``max_chars`` of the cleaned text (legacy behavior)

The graceful fallback chain mirrors the chunker stack landed in
O2 / O8 — Python is authoritative, tree-sitter handles the rest when
the wheel is installed, and the legacy snippet-truncation catches
everything else.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — cross-cluster sibs still at legacy or shimmed there.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "workflow" / "scripts"))


# ─── Python summarizer (stdlib ast) ──────────────────────────────────


def _first_docstring_line(node: ast.AST) -> str:
    """Return the first line of the node's docstring, or ''."""
    if not isinstance(
        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)
    ):
        return ""
    doc = ast.get_docstring(node, clean=False)
    if not doc:
        return ""
    first = doc.strip().split("\n", 1)[0].strip()
    return first


def _python_signature(node: ast.AST) -> str:
    """Render a function/class signature *header* only — no body.

    Functions: ``def name(args) -> Return:``
    Async fns: ``async def name(args) -> Return:``
    Classes:   ``class Name(Base, ...):``

    Uses ``ast.unparse`` for the args + return type because hand-
    rolling argument rendering would re-implement a substantial
    subset of Python's call syntax. Available in Python 3.9+;
    kaizen's runtime baseline is 3.10+."""
    if isinstance(node, ast.AsyncFunctionDef):
        try:
            args = ast.unparse(node.args)
        except (AttributeError, ValueError):
            args = "..."
        ret = ""
        if node.returns is not None:
            try:
                ret = f" -> {ast.unparse(node.returns)}"
            except (AttributeError, ValueError):
                ret = ""
        return f"async def {node.name}({args}){ret}:"
    if isinstance(node, ast.FunctionDef):
        try:
            args = ast.unparse(node.args)
        except (AttributeError, ValueError):
            args = "..."
        ret = ""
        if node.returns is not None:
            try:
                ret = f" -> {ast.unparse(node.returns)}"
            except (AttributeError, ValueError):
                ret = ""
        return f"def {node.name}({args}){ret}:"
    if isinstance(node, ast.ClassDef):
        bases = []
        for b in node.bases:
            try:
                bases.append(ast.unparse(b))
            except (AttributeError, ValueError):
                continue
        base_clause = f"({', '.join(bases)})" if bases else ""
        return f"class {node.name}{base_clause}:"
    return ""


def _python_imports(tree: ast.Module) -> list[str]:
    """Collect import module names from the top of a module.

    ``import os, sys``         → ['os', 'sys']
    ``from pathlib import P``  → ['pathlib']
    ``from . import x``        → []   (relative imports omitted — module
                                       name is the empty string)
    Stops at the first non-import top-level statement so we don't
    walk into function bodies looking for inline imports."""
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    out.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.append(node.module.split(".")[0])
        else:
            break
    # De-dup while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for name in out:
        if name not in seen:
            seen.add(name)
            uniq.append(name)
    return uniq


def _python_summary(source: str, max_chars: int) -> str:
    """Build a smart Python summary. Returns '' on parse failure so the
    caller can fall through to the next strategy."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""

    parts: list[str] = []
    imports = _python_imports(tree)
    if imports:
        parts.append(f"imports: {', '.join(imports[:30])}")
        parts.append("")  # blank line

    # Module docstring goes after imports
    mod_doc = _first_docstring_line(tree)
    if mod_doc:
        parts.append(f'"""{mod_doc}"""')
        parts.append("")

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parts.append(_python_signature(node))
            doc = _first_docstring_line(node)
            if doc:
                parts.append(f'    """{doc}"""')
            parts.append("")
        elif isinstance(node, ast.ClassDef):
            parts.append(_python_signature(node))
            doc = _first_docstring_line(node)
            if doc:
                parts.append(f'    """{doc}"""')
            # One indented signature per method (no docstring inside
            # methods — would blow the budget on classes with many
            # documented methods).
            for c in node.body:
                if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    parts.append(f"    {_python_signature(c)}")
            parts.append("")

    out = "\n".join(parts).rstrip() + "\n"
    if len(out) <= max_chars:
        return out
    # Truncate to budget — try to end on a complete line
    cut = out[:max_chars]
    last_nl = cut.rfind("\n")
    if last_nl > max_chars - 200:
        cut = cut[:last_nl] + "\n"
    return cut


# ─── Tree-sitter summarizer (other languages) ────────────────────────


def _ts_summary(source: str, language: str, max_chars: int) -> str:
    """Build a summary via tree-sitter symbol chunks. Returns '' when
    tree-sitter unavailable or no symbols found.

    For each symbol chunk, we emit the first non-blank line (typically
    the signature line). The module-prologue chunk contributes nothing
    here — its content is already captured by the chunker's first
    chunk and would duplicate signal in the summary."""
    try:
        import _ts_chunk
    except ImportError:
        return ""
    chunks = _ts_chunk.chunk_source_by_symbol(source, language)
    if not chunks:
        return ""

    parts: list[str] = []
    for c in chunks:
        if c.kind == "module":
            continue
        first_line = ""
        for line in c.text.split("\n"):
            stripped = line.rstrip()
            if stripped.strip():
                first_line = stripped
                break
        if not first_line:
            continue
        # Pad with a colon hint at end so the line reads like a
        # signature even when the source didn't have one (e.g. Ruby
        # bare 'def foo' is fine; Rust 'fn foo(x: i32) ->' might lose
        # its trailing brace — that's OK for summary purposes).
        parts.append(first_line)

    if not parts:
        return ""

    out = "\n".join(parts) + "\n"
    if len(out) <= max_chars:
        return out
    cut = out[:max_chars]
    last_nl = cut.rfind("\n")
    if last_nl > max_chars - 200:
        cut = cut[:last_nl] + "\n"
    return cut


# ─── Public dispatch ─────────────────────────────────────────────────


def smart_summary(
    source: str,
    language: str,
    fallback_text: str,
    *,
    max_chars: int = 2048,
) -> str:
    """Build the dense file-level summary.

    1. ``language == "python"``  → ``_python_summary``
    2. anything else             → ``_ts_summary``
    3. neither produced output   → ``fallback_text[:max_chars]``

    Returning the fallback verbatim preserves the legacy snippet
    behavior for files / languages we can't summarize structurally,
    so the column is never empty.

    ``fallback_text`` is typically the already-cleaned (comment-
    stripped + whitespace-normalized) source. Caller passes whatever
    they were going to write as the snippet."""
    if source and language == "python":
        out = _python_summary(source, max_chars)
        if out.strip():
            return out
    if source and language and language != "python":
        out = _ts_summary(source, language, max_chars)
        if out.strip():
            return out
    return fallback_text[:max_chars] if fallback_text else ""


# ─── CLI inspector ────────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(
        description="Inspect kaizen smart file-level summary — emit a "
                    "dense signature-bearing summary for one file."
    )
    p.add_argument("file", help="path to source file")
    p.add_argument("--language", help="override language detection")
    p.add_argument("--max-chars", type=int, default=2048)
    args = p.parse_args()
    path = Path(args.file)
    if not path.is_file():
        sys.exit(f"not a file: {path}")
    source = path.read_text(encoding="utf-8", errors="replace")
    language = args.language
    if language is None:
        ext = path.suffix.lstrip(".")
        language = {
            "py": "python", "rs": "rust", "ts": "typescript",
            "js": "javascript", "go": "go", "rb": "ruby", "java": "java",
        }.get(ext, ext)
    out = smart_summary(source, language, source, max_chars=args.max_chars)
    print(out)
    print(f"\n--- summary: {len(out)}B / budget {args.max_chars}B "
          f"(input file: {len(source)}B)", file=sys.stderr)
