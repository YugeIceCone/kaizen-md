#!/usr/bin/env python3
"""kaizen docs_gen — comprehensive per-package documentation generator.

Stdlib-only. Ports shodan's `cargo xtask docs` Rust pipeline
(`crates/database/src/codebase/{analyzer,generator,model}.rs`) into
Python with multi-language support — currently Rust + Python; the
JS/Go stubs from v1 are preserved for back-compat but use the v1
(thin) renderer.

## Output shape (matches shodan/docs/crates/*.md)

For Rust + Python packages, each `<NAME>.md` carries:

  1. Header   `# crates/<rel>/ — <package-name> Reference`
  2. Status   LOC / file count / test-attribute count, scope, update rule
  3. § 1      "What X is" — package description or crate-level doc-comment
  4. § 2      Files — tree with per-file LOC + module-doc one-liner
  5. § 3      Public API at a glance — tables of Traits / Structs / Enums /
              Functions / Async-fns / Macros / Consts / Type-aliases
              (Name | File | Signature columns, full signatures)
  6. § 4      File-by-file reference — module doc, public items list,
              test count, LOC/blank/comment stats per file
  7. § 5      Dependencies — `[dependencies]` + `[dev-dependencies]` tables
              (Dep | Source | Features)
  8. § 6      Crate-root re-exports (Rust only)
  9. § 7      Test inventory — File | Tests table
 10. § 8      Recent commits touching this package (git log --oneline)
 11. § 9      "What X is not" — placeholder for curated DON'T list

The companion `<NAME>.json` is the same data in the structured shape
`scan_package()` produces; consumers like onboard's structural index
can ingest it directly.

## Usage

    docs_gen.py scan [--root .] [--output docs/crates/] [--format both]
    docs_gen.py detect [--root .]      # list detected packages
    docs_gen.py one <pkg_dir> [--format both]   # single package
"""

from __future__ import annotations

import argparse
import dataclasses as dc
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover — only on older Python
    tomllib = None  # type: ignore[assignment]


SCHEMA_VERSION = 2
KIND = "kaizen.docs"


# ─── Model (mirrors shodan's codebase::model) ────────────────────────


@dc.dataclass
class BinTarget:
    name: str
    path: Optional[str] = None


@dc.dataclass
class FeatureFlag:
    name: str
    deps: str  # right-hand side, single line


@dc.dataclass
class Dependency:
    name: str
    source: str  # "workspace" | 'version = "1.0"' | raw rhs
    features: Optional[str] = None


@dc.dataclass
class ItemSummary:
    """Public item declared in a source file."""
    kind: str       # struct | enum | trait | fn | async_fn | const | type_alias | macro | class | py_fn
    name: str
    signature: str  # single-line excerpt, best-effort


@dc.dataclass
class FileProfile:
    path: str               # relative to package root, posix-style
    loc: int
    blank_lines: int
    comment_lines: int
    module_doc: Optional[str]   # paragraph-stitched first block
    items: list[ItemSummary] = dc.field(default_factory=list)
    tests: int = 0


@dc.dataclass
class CommitRef:
    sha: str
    subject: str


@dc.dataclass
class CrateProfile:
    name: str                       # path-derived identifier
    relative_path: str
    package_name: str
    language: str                   # "rust" | "python" | "js" | "go"
    package_description: Optional[str] = None
    edition: Optional[str] = None
    version: Optional[str] = None
    authors: Optional[str] = None
    bins: list[BinTarget] = dc.field(default_factory=list)
    features: list[FeatureFlag] = dc.field(default_factory=list)
    dependencies: list[Dependency] = dc.field(default_factory=list)
    dev_dependencies: list[Dependency] = dc.field(default_factory=list)
    lints: list[str] = dc.field(default_factory=list)
    re_exports: list[str] = dc.field(default_factory=list)
    crate_doc: Optional[str] = None
    files: list[FileProfile] = dc.field(default_factory=list)
    total_loc: int = 0
    total_blank_lines: int = 0
    total_comment_lines: int = 0
    total_tests: int = 0
    recent_commits: list[CommitRef] = dc.field(default_factory=list)
    scanned_at: str = ""

    def to_json(self) -> dict:
        d = dc.asdict(self)
        d["schema_version"] = SCHEMA_VERSION
        d["kind"] = KIND
        return d


# ─── Language detection ──────────────────────────────────────────────


LANG_MARKERS: dict[str, str] = {
    "Cargo.toml": "rust",
    "package.json": "js",
    "go.mod": "go",
    "pyproject.toml": "python",
}

LANG_EXTS: dict[str, list[str]] = {
    "rust": [".rs"],
    "js": [".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"],
    "go": [".go"],
    "python": [".py", ".pyi"],
}

SKIP_DIRS = {"target", "node_modules", ".git", "vendor", "dist", "build",
             ".venv", "venv", "__pycache__", ".kaizen", ".workflow",
             ".claude", ".idea", ".pytest_cache", ".mypy_cache"}


def detect_packages(root: Path) -> list[tuple[Path, str]]:
    """Return [(package_dir, language)] for every detected package."""
    found: list[tuple[Path, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for marker, lang in LANG_MARKERS.items():
            if marker in filenames:
                # For Rust, the marker is required to declare [package] (not workspace-only).
                if marker == "Cargo.toml" and not _cargo_has_package(Path(dirpath) / marker):
                    continue
                found.append((Path(dirpath), lang))
                break
    found.sort(key=lambda t: t[0].as_posix())
    return found


def _cargo_has_package(cargo_path: Path) -> bool:
    try:
        text = cargo_path.read_text(errors="ignore")
    except OSError:
        return False
    return bool(re.search(r"(?m)^\s*\[package\]\s*$", text))


# ─── Per-language file analyzer ──────────────────────────────────────


# Rust item regex — ports analyzer.rs:item_regex().
_RUST_ITEM = re.compile(
    r"(?m)^[ \t]*pub(?:\([^)]*\))?\s+(?P<async>async\s+)?"
    r"(?P<kind>struct|enum|trait|fn|const|type)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)[^;\n]*"
)
_RUST_MACRO = re.compile(r"(?m)^\s*macro_rules!\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
_RUST_TEST_ATTR = re.compile(r"(?m)^[ \t]*#\[(tokio::test|test|test_log::test)")
_RUST_PUB_USE = re.compile(r"(?m)^\s*pub use ([^;]+);")

# Python item regex — `def`, `async def`, `class`. Indentation matters in
# Python: top-level only is what's "public" in the docs sense; nested
# methods of a class are listed under the class via the file ref pass.
_PY_DEF = re.compile(
    r"(?m)^(?P<async>async\s+)?def\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)[^:\n]*"
)
_PY_CLASS = re.compile(r"(?m)^class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:\([^)]*\))?\s*:")
_PY_TYPE_ALIAS = re.compile(
    r"(?m)^(?P<name>[A-Z][A-Za-z0-9_]*)\s*(?::\s*TypeAlias\s*)?=\s*"
    r"(?:Union|Optional|List|Dict|Tuple|Callable|[A-Z]\w*\[|str\s*\||int\s*\|)"
)
_PY_TEST_DEF = re.compile(r"(?m)^(?:async\s+)?def\s+test_[A-Za-z_][A-Za-z0-9_]*\s*\(")


def analyze_rust_file(abs_path: Path, rel: str) -> FileProfile:
    try:
        text = abs_path.read_text(errors="ignore")
    except OSError:
        return FileProfile(path=rel, loc=0, blank_lines=0, comment_lines=0, module_doc=None)
    lines = text.splitlines()
    total = len(lines)
    blank = sum(1 for l in lines if not l.strip())
    comment = sum(
        1 for l in lines
        if (s := l.lstrip()).startswith("//") or s.startswith("/*") or s.startswith("*")
    )
    module_doc = _extract_rust_module_doc(text)
    items = _extract_rust_items(text)
    tests = len(_RUST_TEST_ATTR.findall(text))
    return FileProfile(
        path=rel, loc=total, blank_lines=blank, comment_lines=comment,
        module_doc=module_doc, items=items, tests=tests,
    )


def _extract_rust_module_doc(src: str) -> Optional[str]:
    """Port of analyzer.rs:extract_module_doc — first `//!` paragraph."""
    out: list[str] = []
    started = False
    for raw in src.splitlines():
        line = raw.lstrip()
        if not started and (line.startswith("#!") or not line):
            continue
        if line.startswith("//!"):
            started = True
            body = line[3:].lstrip()
            if not body:
                if out:
                    break
                continue
            out.append(body)
        elif started:
            break
    return " ".join(out) if out else None


def _extract_rust_items(src: str) -> list[ItemSummary]:
    """Port of analyzer.rs:extract_items + macro pass."""
    items: list[ItemSummary] = []
    for m in _RUST_ITEM.finditer(src):
        kind_word = m.group("kind") or ""
        async_marker = m.group("async") or ""
        name = m.group("name") or ""
        if not name:
            continue
        kind = {
            "struct": "struct",
            "enum": "enum",
            "trait": "trait",
            "const": "const",
            "type": "type_alias",
        }.get(kind_word)
        if kind is None and kind_word == "fn":
            kind = "async_fn" if async_marker else "fn"
        if kind is None:
            continue
        sig = m.group(0).splitlines()[0].rstrip().rstrip("{").rstrip()
        items.append(ItemSummary(kind=kind, name=name, signature=sig))
    for m in _RUST_MACRO.finditer(src):
        name = m.group("name") or ""
        if name:
            items.append(ItemSummary(kind="macro", name=name, signature=f"macro_rules! {name}"))
    # Dedupe by (kind, name); keep first signature seen.
    seen: dict[tuple[str, str], ItemSummary] = {}
    for it in items:
        seen.setdefault((it.kind, it.name), it)
    return list(seen.values())


def analyze_python_file(abs_path: Path, rel: str) -> FileProfile:
    try:
        text = abs_path.read_text(errors="ignore")
    except OSError:
        return FileProfile(path=rel, loc=0, blank_lines=0, comment_lines=0, module_doc=None)
    lines = text.splitlines()
    total = len(lines)
    blank = sum(1 for l in lines if not l.strip())
    comment = sum(1 for l in lines if l.lstrip().startswith("#"))
    module_doc = _extract_python_module_doc(text)
    items = _extract_python_items(text)
    tests = len(_PY_TEST_DEF.findall(text))
    return FileProfile(
        path=rel, loc=total, blank_lines=blank, comment_lines=comment,
        module_doc=module_doc, items=items, tests=tests,
    )


def _extract_python_module_doc(src: str) -> Optional[str]:
    """Pull the module-level docstring's first paragraph. Triple-double
    or triple-single quotes. Skips leading `#` comments + blank lines +
    `from __future__` imports."""
    lines = src.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].lstrip()
        if not s or s.startswith("#") or s.startswith("from __future__"):
            i += 1
            continue
        break
    if i >= len(lines):
        return None
    line = lines[i].lstrip()
    for quote in ('"""', "'''"):
        if not line.startswith(quote):
            continue
        # Single-line docstring case.
        rest = line[3:]
        if rest.endswith(quote) and len(rest) > 2:
            return rest[:-3].strip() or None
        # Multi-line: collect until closing quote.
        out: list[str] = []
        if rest:
            out.append(rest)
        for j in range(i + 1, len(lines)):
            l = lines[j]
            if quote in l:
                out.append(l[: l.index(quote)])
                break
            out.append(l)
        para: list[str] = []
        for entry in out:
            entry = entry.strip()
            if not entry:
                if para:
                    break
                continue
            para.append(entry)
        return " ".join(para) if para else None
    return None


def _extract_python_items(src: str) -> list[ItemSummary]:
    """Top-level `def` / `async def` / `class` only — nested methods are
    listed under their containing class via the file ref pass."""
    items: list[ItemSummary] = []
    for raw_match in _PY_DEF.finditer(src):
        # Verify this is a top-level def: line starts at column 0.
        start = raw_match.start()
        line_start = src.rfind("\n", 0, start) + 1
        if start != line_start:
            continue
        async_marker = raw_match.group("async") or ""
        name = raw_match.group("name") or ""
        if not name:
            continue
        if name.startswith("_") and not name.startswith("__"):
            continue  # skip _private
        sig = raw_match.group(0).splitlines()[0].rstrip(":").rstrip()
        kind = "async_fn" if async_marker else "fn"
        items.append(ItemSummary(kind=kind, name=name, signature=sig))
    for raw_match in _PY_CLASS.finditer(src):
        start = raw_match.start()
        line_start = src.rfind("\n", 0, start) + 1
        if start != line_start:
            continue
        name = raw_match.group("name") or ""
        if not name or (name.startswith("_") and not name.startswith("__")):
            continue
        sig = raw_match.group(0).rstrip(":").rstrip()
        items.append(ItemSummary(kind="class", name=name, signature=sig))
    seen: dict[tuple[str, str], ItemSummary] = {}
    for it in items:
        seen.setdefault((it.kind, it.name), it)
    return list(seen.values())


def _extract_rust_reexports(file: Path) -> list[str]:
    try:
        text = file.read_text(errors="ignore")
    except OSError:
        return []
    out = sorted(set(
        " ".join(m.group(1).split()) for m in _RUST_PUB_USE.finditer(text)
    ))
    return out


# ─── Manifest parsers ────────────────────────────────────────────────


@dc.dataclass
class _PackageMeta:
    name: str
    description: Optional[str] = None
    edition: Optional[str] = None
    version: Optional[str] = None
    authors: Optional[str] = None


def _capture_quoted(section: str, key: str) -> Optional[str]:
    m = re.search(rf'(?m)^\s*{re.escape(key)}\s*=\s*"([^"]+)"', section)
    return m.group(1) if m else None


def _capture_value(section: str, key: str) -> Optional[str]:
    inh = re.search(rf"(?m)^\s*{re.escape(key)}\.workspace\s*=\s*true", section)
    if inh:
        return "workspace"
    m = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*(.+?)\s*$", section)
    if not m:
        return None
    return m.group(1).strip('"')


def _extract_toml_section(toml_text: str, name: str) -> Optional[str]:
    """Body of `[<name>]` until the next `[…]` header. Returns None if absent."""
    header_pat = re.compile(r"^\[([^\]]+)\]")
    in_section = False
    buf: list[str] = []
    for line in toml_text.splitlines():
        t = line.strip()
        m = header_pat.match(t)
        if m:
            in_section = m.group(1) == name
            continue
        if in_section:
            buf.append(line)
    return "\n".join(buf) if buf else None


def parse_rust_manifest(pkg_dir: Path) -> tuple[_PackageMeta, list[BinTarget], list[FeatureFlag],
                                                 list[Dependency], list[Dependency], list[str]]:
    cargo = pkg_dir / "Cargo.toml"
    try:
        text = cargo.read_text(errors="ignore")
    except OSError:
        return _PackageMeta(name=pkg_dir.name), [], [], [], [], []
    pkg_section = _extract_toml_section(text, "package") or ""
    meta = _PackageMeta(
        name=_capture_quoted(pkg_section, "name") or pkg_dir.name,
        description=_capture_quoted(pkg_section, "description"),
        edition=_capture_value(pkg_section, "edition"),
        version=_capture_value(pkg_section, "version"),
        authors=_capture_value(pkg_section, "authors"),
    )
    bins = _parse_bin_targets(text)
    features = _parse_features(text)
    deps = _parse_dep_table(text, "dependencies")
    dev_deps = _parse_dep_table(text, "dev-dependencies")
    lints: list[str] = []
    if re.search(r"\[lints\][^\[]*workspace\s*=\s*true", text, re.DOTALL):
        lints.append("workspace = true")
    return meta, bins, features, deps, dev_deps, lints


def _parse_bin_targets(toml_text: str) -> list[BinTarget]:
    out: list[BinTarget] = []
    in_bin = False
    buf: list[str] = []
    for line in toml_text.splitlines():
        t = line.strip()
        is_header = t.startswith("[")
        if is_header:
            if in_bin:
                _push_bin("\n".join(buf), out)
                buf = []
            in_bin = t == "[[bin]]"
            continue
        if in_bin:
            buf.append(line)
    if in_bin:
        _push_bin("\n".join(buf), out)
    return out


def _push_bin(body: str, out: list[BinTarget]) -> None:
    name = _capture_quoted(body, "name") or ""
    path = _capture_quoted(body, "path")
    if name:
        out.append(BinTarget(name=name, path=path))


def _parse_features(toml_text: str) -> list[FeatureFlag]:
    section = _extract_toml_section(toml_text, "features")
    if not section:
        return []
    pat = re.compile(r"(?m)^\s*([A-Za-z0-9_-]+)\s*=\s*(\[[^\]]*\])")
    return [
        FeatureFlag(name=m.group(1), deps=m.group(2).replace("\n", " ").strip())
        for m in pat.finditer(section)
    ]


def _parse_dep_rhs(rhs: str) -> tuple[str, Optional[str]]:
    rhs = rhs.strip()
    if rhs.startswith('"'):
        return f"version = {rhs}", None
    if rhs.startswith("{"):
        workspace = "workspace = true" in rhs
        ver_m = re.search(r'version\s*=\s*"([^"]+)"', rhs)
        feat_m = re.search(r"features\s*=\s*\[([^\]]+)\]", rhs)
        features = None
        if feat_m:
            features = ", ".join(
                s.strip().strip('"') for s in feat_m.group(1).split(",") if s.strip()
            )
        source = "workspace" if workspace else (
            f'version = "{ver_m.group(1)}"' if ver_m else rhs
        )
        return source, features
    return rhs, None


def _parse_dep_table(toml_text: str, section: str) -> list[Dependency]:
    """Port of analyzer.rs:parse_dep_table — handles direct, workspace,
    and `[<section>.<name>]` styles."""
    out: list[Dependency] = []
    in_section = False
    current_table: Optional[str] = None
    header_pat = re.compile(r"^\[([^\]]+)\]")
    direct_pat = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*=\s*(.*)$")
    workspace_pat = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\.workspace\s*=\s*true")
    for raw in toml_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = header_pat.match(line)
        if m:
            current_table = m.group(1)
            in_section = (
                current_table == section
                or current_table.startswith(f"{section}.")
            )
            continue
        if not in_section:
            continue
        if current_table and current_table.startswith(f"{section}."):
            name = current_table[len(f"{section}."):]
            src, feats = _parse_dep_rhs(line)
            _upsert_dep(out, name, src, feats)
            continue
        wm = workspace_pat.match(line)
        if wm:
            out.append(Dependency(name=wm.group(1), source="workspace"))
            continue
        dm = direct_pat.match(line)
        if dm:
            name = dm.group(1)
            src, feats = _parse_dep_rhs(dm.group(2))
            out.append(Dependency(name=name, source=src, features=feats))
    out.sort(key=lambda d: d.name)
    deduped: list[Dependency] = []
    for d in out:
        if deduped and deduped[-1].name == d.name:
            continue
        deduped.append(d)
    return deduped


def _upsert_dep(out: list[Dependency], name: str, source: str, features: Optional[str]) -> None:
    for d in out:
        if d.name == name:
            d.source = source
            d.features = features
            return
    out.append(Dependency(name=name, source=source, features=features))


def parse_python_manifest(pkg_dir: Path) -> tuple[_PackageMeta, list[Dependency], list[Dependency]]:
    pp = pkg_dir / "pyproject.toml"
    if not tomllib:
        return _PackageMeta(name=pkg_dir.name), [], []
    try:
        data = tomllib.loads(pp.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return _PackageMeta(name=pkg_dir.name), [], []
    project = data.get("project", {})
    meta = _PackageMeta(
        name=project.get("name", pkg_dir.name),
        description=project.get("description"),
        version=project.get("version"),
    )
    deps = [Dependency(name=_dep_name(d), source=d) for d in project.get("dependencies", [])]
    dev_deps = [
        Dependency(name=_dep_name(d), source=d)
        for d in project.get("optional-dependencies", {}).get("dev", [])
    ]
    return meta, deps, dev_deps


def _dep_name(spec: str) -> str:
    """Strip version specifier from a PEP 508 spec ('foo>=1.0' → 'foo')."""
    return re.split(r"[\s<>=!~;,\[]", spec, maxsplit=1)[0].strip()


# ─── Git log ─────────────────────────────────────────────────────────


def git_log_for_path(workspace_root: Path, pkg_dir: Path, limit: int = 8) -> list[CommitRef]:
    try:
        rel = str(pkg_dir.relative_to(workspace_root))
    except ValueError:
        rel = str(pkg_dir)
    try:
        out = subprocess.check_output(
            ["git", "-C", str(workspace_root), "log", f"-{limit}", "--oneline",
             "--no-merges", "--", rel],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return []
    commits: list[CommitRef] = []
    for line in out.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 1:
            continue
        commits.append(CommitRef(sha=parts[0], subject=parts[1]))
    return commits


# ─── Per-package scan ────────────────────────────────────────────────


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _crate_name_from_path(rel: Path) -> str:
    """Path-derived identifier; nested layouts use `-` as separator
    (`port/tools/agent` → `tools-agent`). Workspace-root packages
    keep their leaf name."""
    parts = rel.parts
    if len(parts) >= 2 and parts[0] in ("crates", "port"):
        return "-".join(parts[1:])
    return "-".join(parts)


def _iter_source_files(pkg_dir: Path, language: str) -> list[Path]:
    """Source files for this package — src/ + sibling examples/benches/tests/.
    Skip nested package roots (so a workspace member doesn't double-count)."""
    exts = LANG_EXTS.get(language, [])
    out: list[Path] = []
    candidates: list[Path] = []
    if language == "rust":
        for sub in ("src", "examples", "benches", "tests"):
            d = pkg_dir / sub
            if d.is_dir():
                candidates.extend(p for p in d.rglob("*") if p.is_file())
    elif language == "python":
        # Python packages live alongside pyproject.toml; walk one level minus skip-dirs.
        for p in pkg_dir.rglob("*"):
            if not p.is_file():
                continue
            if any(part in SKIP_DIRS or part.startswith(".") for part in p.relative_to(pkg_dir).parts):
                continue
            candidates.append(p)
    else:
        # Fallback: rglob with skip-dir filter.
        for p in pkg_dir.rglob("*"):
            if not p.is_file():
                continue
            if any(part in SKIP_DIRS for part in p.relative_to(pkg_dir).parts):
                continue
            candidates.append(p)
    for p in candidates:
        if p.suffix in exts:
            out.append(p)
    return out


def analyze_package(pkg_dir: Path, language: str, workspace_root: Path) -> CrateProfile:
    try:
        rel_path = pkg_dir.relative_to(workspace_root).as_posix()
    except ValueError:
        rel_path = pkg_dir.as_posix()
    name = _crate_name_from_path(Path(rel_path))
    # Match shodan's convention: relative_path is relative to scan_root
    # (crates/ or port/), NOT the workspace root. Renderer prepends the
    # scan root via header_root; without this strip we get `crates/crates/foo`.
    for scan_prefix in ("crates/", "port/"):
        if rel_path.startswith(scan_prefix):
            rel_path = rel_path[len(scan_prefix):]
            break
    profile = CrateProfile(
        name=name, relative_path=rel_path, package_name=pkg_dir.name, language=language,
        scanned_at=now_iso(),
    )
    if language == "rust":
        meta, bins, features, deps, dev_deps, lints = parse_rust_manifest(pkg_dir)
        profile.package_name = meta.name
        profile.package_description = meta.description
        profile.edition = meta.edition
        profile.version = meta.version
        profile.authors = meta.authors
        profile.bins = bins
        profile.features = features
        profile.dependencies = deps
        profile.dev_dependencies = dev_deps
        profile.lints = lints
    elif language == "python":
        meta, deps, dev_deps = parse_python_manifest(pkg_dir)
        profile.package_name = meta.name
        profile.package_description = meta.description
        profile.version = meta.version
        profile.dependencies = deps
        profile.dev_dependencies = dev_deps
    # File-by-file analysis.
    files: list[FileProfile] = []
    for fp in _iter_source_files(pkg_dir, language):
        rel = fp.relative_to(pkg_dir).as_posix()
        if language == "rust":
            files.append(analyze_rust_file(fp, rel))
        elif language == "python":
            files.append(analyze_python_file(fp, rel))
        else:
            # No deep analyzer yet for js/go; record LOC + filename only.
            try:
                lines = fp.read_text(errors="ignore").splitlines()
            except OSError:
                continue
            files.append(FileProfile(
                path=rel, loc=len(lines),
                blank_lines=sum(1 for l in lines if not l.strip()),
                comment_lines=0, module_doc=None,
            ))
    files.sort(key=lambda f: f.path)
    profile.files = files
    profile.total_loc = sum(f.loc for f in files)
    profile.total_blank_lines = sum(f.blank_lines for f in files)
    profile.total_comment_lines = sum(f.comment_lines for f in files)
    profile.total_tests = sum(f.tests for f in files)
    # Crate doc + re-exports come from lib.rs / main.rs (Rust)
    # or __init__.py (Python).
    if language == "rust":
        entry = next(
            (f for f in files if f.path in ("src/lib.rs", "src/main.rs")), None
        )
        if entry:
            profile.crate_doc = entry.module_doc
            profile.re_exports = _extract_rust_reexports(pkg_dir / entry.path)
    elif language == "python":
        entry = next((f for f in files if f.path.endswith("__init__.py")), None)
        if entry:
            profile.crate_doc = entry.module_doc
    profile.recent_commits = git_log_for_path(workspace_root, pkg_dir, limit=8)
    return profile


# ─── Markdown renderer (mirrors shodan's generator.rs) ───────────────


def render_md(p: CrateProfile, port: bool = False) -> str:
    parts: list[str] = []
    header_root = "port" if port else "crates"
    parts.append(f"# `{header_root}/{p.relative_path}/` — `{p.package_name}` Reference")
    parts.append("")
    parts.append(_render_status_block(p, header_root, port))
    parts.append("")
    parts.append(_render_what_it_is(p))
    parts.append("")
    parts.append(_render_file_tree(p, header_root))
    parts.append("")
    parts.append(_render_public_api(p))
    parts.append("")
    parts.append(_render_file_reference(p))
    parts.append("")
    parts.append(_render_dependencies(p))
    parts.append("")
    parts.append(_render_re_exports(p))
    parts.append("")
    parts.append(_render_test_inventory(p))
    parts.append("")
    parts.append(_render_recent_commits(p))
    parts.append("")
    parts.append(_render_what_it_is_not(p))
    parts.append("")
    parts.append("---")
    parts.append("")
    flag = " --port" if port else ""
    parts.append(f"*Generated by `kaizen docs_gen scan{flag}`. Re-run after refactors.*")
    parts.append("")
    return "\n".join(parts)


def _render_status_block(p: CrateProfile, header_root: str, port: bool) -> str:
    flag = " --port" if port else ""
    return (
        f"> **Scope.** Comprehensive file-by-file reference for the "
        f"`{p.package_name}` crate. Pairs with `AGENTS.md` § \"Crate Scope Rules → "
        f"`{header_root}/{p.relative_path}`\" (DO/DON'T contract).\n"
        f">\n"
        f"> **Status.** {p.total_loc} LOC across {len(p.files)} files. "
        f"~{p.total_tests} test attribute(s) detected.\n"
        f">\n"
        f"> **Update rule.** When the code disagrees with this doc, the code "
        f"wins — re-run `kaizen docs_gen scan{flag}` to regenerate. "
        f"Hand-edits will be overwritten."
    )


def _render_what_it_is(p: CrateProfile) -> str:
    lines = [f"## 1. What `{p.package_name}` is", ""]
    if p.package_description:
        lines.append(p.package_description)
    elif p.crate_doc:
        lines.append(p.crate_doc)
    else:
        lines.append("_(No `Cargo.toml`/`pyproject.toml` description or crate-level doc-comment available.)_")
    if p.crate_doc and p.package_description and p.crate_doc != p.package_description:
        lines.append("")
        lines.append(f"**Crate doc-comment:** {p.crate_doc}")
    return "\n".join(lines)


def _render_what_it_is_not(p: CrateProfile) -> str:
    return (
        f"## 9. What `{p.package_name}` is *not*\n\n"
        f"_(No curated DON'T list — see `AGENTS.md` § \"Crate Scope Rules\" for "
        f"cross-crate boundaries.)_"
    )


def _truncate_one_line(s: str, max_chars: int = 100) -> str:
    one = re.sub(r"\s+", " ", s).strip()
    return one if len(one) <= max_chars else one[:max_chars] + "…"


def _render_file_tree(p: CrateProfile, header_root: str) -> str:
    lines = ["## 2. Files", "", "```", f"{header_root}/{p.relative_path}/"]
    for f in p.files:
        comment = _truncate_one_line(f.module_doc, 100) if f.module_doc else ""
        suffix = f" — {comment}" if comment else ""
        lines.append(f"├── {f.path:<40}  ({f.loc} LOC){suffix}")
    lines.append("```")
    lines.append("")
    lines.append(f"**Total: {p.total_loc} LOC across {len(p.files)} files.**")
    return "\n".join(lines)


_KIND_LABELS: list[tuple[str, str]] = [
    ("trait", "Traits"),
    ("struct", "Structs"),
    ("class", "Classes"),
    ("enum", "Enums"),
    ("fn", "Functions"),
    ("async_fn", "Async functions"),
    ("macro", "Macros"),
    ("const", "Constants"),
    ("type_alias", "Type aliases"),
]


def _escape_pipe(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def _render_public_api(p: CrateProfile) -> str:
    lines = [
        "## 3. Public API at a glance", "",
        "Aggregated public items per file (best-effort regex extraction).", "",
    ]
    rendered_any = False
    for kind, label in _KIND_LABELS:
        rows: list[tuple[str, ItemSummary]] = [
            (f.path, it) for f in p.files for it in f.items if it.kind == kind
        ]
        if not rows:
            continue
        rendered_any = True
        lines.append(f"### {label} ({len(rows)})")
        lines.append("")
        lines.append("| Name | File | Signature |")
        lines.append("|---|---|---|")
        for path, it in rows:
            lines.append(f"| `{it.name}` | `{path}` | `{_escape_pipe(it.signature)}` |")
        lines.append("")
    if not rendered_any:
        lines.append("_(No public items detected.)_")
    return "\n".join(lines).rstrip()


def _render_file_reference(p: CrateProfile) -> str:
    lines = ["## 4. File-by-file reference", ""]
    kind_label = {
        "fn": "fn", "async_fn": "async fn", "struct": "struct", "enum": "enum",
        "trait": "trait", "const": "const", "type_alias": "type alias",
        "macro": "macro", "class": "class",
    }
    for f in p.files:
        lines.append(f"### `{f.path}` — {f.loc} LOC")
        lines.append("")
        if f.module_doc:
            lines.append(f.module_doc)
            lines.append("")
        if f.items:
            lines.append(f"**Public items ({len(f.items)}):**")
            lines.append("")
            for it in f.items:
                label = kind_label.get(it.kind, it.kind)
                lines.append(f"- {label} **`{it.name}`** — `{_escape_pipe(it.signature)}`")
            lines.append("")
        if f.tests:
            lines.append(f"_{f.tests} test attribute(s) in this file._")
            lines.append("")
        if f.loc:
            blank_pct = (f.blank_lines * 100) // f.loc
            comment_pct = (f.comment_lines * 100) // f.loc
        else:
            blank_pct = comment_pct = 0
        lines.append(
            f"<sub>{f.loc} LOC · {f.blank_lines} blank ({blank_pct}%) · "
            f"{f.comment_lines} comment ({comment_pct}%)</sub>"
        )
        lines.append("")
    return "\n".join(lines).rstrip()


def _render_dependencies(p: CrateProfile) -> str:
    heading = {
        "rust": "## 5. Cargo dependencies",
        "python": "## 5. Python dependencies",
    }.get(p.language, "## 5. Dependencies")
    lines = [heading, ""]
    if not p.dependencies and not p.dev_dependencies:
        lines.append("_None._")
        return "\n".join(lines)
    section_label = "`[dependencies]`" if p.language == "rust" else "`dependencies`"
    dev_label = "`[dev-dependencies]`" if p.language == "rust" else "`optional-dependencies.dev`"
    lines.append(f"### {section_label}")
    lines.append("")
    if p.dependencies:
        lines.append("| Dep | Source | Features |")
        lines.append("|---|---|---|")
        for d in p.dependencies:
            feats = d.features if d.features else "—"
            lines.append(f"| `{d.name}` | `{d.source}` | {feats} |")
    else:
        lines.append("_None._")
    if p.dev_dependencies:
        lines.append("")
        lines.append(f"### {dev_label}")
        lines.append("")
        lines.append("| Dep | Source | Features |")
        lines.append("|---|---|---|")
        for d in p.dev_dependencies:
            feats = d.features if d.features else "—"
            lines.append(f"| `{d.name}` | `{d.source}` | {feats} |")
    if p.features:
        lines.append("")
        lines.append("### Features")
        lines.append("")
        for f in p.features:
            lines.append(f"- `{f.name}` = `{f.deps}`")
    if p.bins:
        lines.append("")
        lines.append("### Binaries")
        lines.append("")
        for b in p.bins:
            path_suffix = f" (path: `{b.path}`)" if b.path else ""
            lines.append(f"- `{b.name}`{path_suffix}")
    if p.lints:
        lines.append("")
        lines.append("### `[lints]`")
        lines.append("")
        for l in p.lints:
            lines.append(f"- `{l}`")
    return "\n".join(lines).rstrip()


def _render_re_exports(p: CrateProfile) -> str:
    lines = ["## 6. Crate-root re-exports", ""]
    if not p.re_exports:
        lines.append("_None detected at the crate root._")
        return "\n".join(lines)
    for r in p.re_exports:
        lines.append(f"- `pub use {r};`")
    return "\n".join(lines)


def _render_test_inventory(p: CrateProfile) -> str:
    with_tests = [f for f in p.files if f.tests > 0]
    if not with_tests:
        return (
            "## 7. Test inventory\n\n"
            "_No `#[test]`/`#[tokio::test]`/`def test_*` attributes detected._"
        )
    lines = ["## 7. Test inventory", "", "| File | Tests |", "|---|---|"]
    for f in with_tests:
        lines.append(f"| `{f.path}` | {f.tests} |")
    lines.append("")
    lines.append(f"**Total: {p.total_tests} test attribute(s).**")
    return "\n".join(lines)


def _render_recent_commits(p: CrateProfile) -> str:
    noun = "crate" if p.language == "rust" else "package"
    lines = [f"## 8. Recent commits touching this {noun}", ""]
    if not p.recent_commits:
        lines.append("_(No git history available.)_")
        return "\n".join(lines)
    for c in p.recent_commits:
        lines.append(f"- `{c.sha}` — {c.subject}")
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────


def _pretty(p: Path, root: Path) -> str:
    """Return p relative to root if possible, absolute otherwise."""
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def cmd_detect(args):
    root = Path(args.root).resolve()
    packages = detect_packages(root)
    for pkg_dir, lang in packages:
        try:
            rel = pkg_dir.relative_to(root)
        except ValueError:
            rel = pkg_dir
        print(f"{lang}\t{rel}")
    if not packages:
        print("(no packages detected)", file=sys.stderr)
        sys.exit(1)


def cmd_scan(args):
    root = Path(args.root).resolve()
    out_dir = Path(args.output)
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    packages = detect_packages(root)
    if not packages:
        print("(no packages detected)", file=sys.stderr)
        sys.exit(1)
    only = set(args.only.split(",")) if getattr(args, "only", None) else None
    written: list[str] = []
    for pkg_dir, lang in packages:
        if only and pkg_dir.name not in only:
            continue
        profile = analyze_package(pkg_dir, lang, root)
        # Filename = path-derived `name` uppercased (matches shodan
        # convention: crates/cli/ → CLI.md, crates/retrieval/ → RETRIEVAL.md,
        # crates/shodan-docs/ → SHODAN_DOCS.md). package_name (manifest-
        # declared) goes in the header instead.
        stem = profile.name.replace("-", "_").upper()
        if args.format in ("json", "both"):
            jp = out_dir / f"{stem}.json"
            jp.write_text(json.dumps(profile.to_json(), indent=2) + "\n")
            written.append(_pretty(jp, root))
        if args.format in ("md", "both"):
            mp = out_dir / f"{stem}.md"
            mp.write_text(render_md(profile, port=args.port))
            written.append(_pretty(mp, root))
    print(f"wrote {len(written)} files to {_pretty(out_dir, root)}/")
    if args.verbose:
        for w in written:
            print(f"  - {w}")


def cmd_one(args):
    pkg_dir = Path(args.pkg).resolve()
    if not pkg_dir.is_dir():
        sys.exit(f"not a directory: {pkg_dir}")
    lang: Optional[str] = None
    for marker, candidate in LANG_MARKERS.items():
        if (pkg_dir / marker).exists():
            lang = candidate
            break
    if not lang:
        sys.exit(f"no recognised manifest in {pkg_dir}")
    workspace_root = pkg_dir
    cur = pkg_dir.parent
    while cur != cur.parent:
        if any((cur / m).exists() for m in LANG_MARKERS):
            workspace_root = cur
        cur = cur.parent
    profile = analyze_package(pkg_dir, lang, workspace_root)
    if args.format == "json":
        print(json.dumps(profile.to_json(), indent=2))
    elif args.format == "md":
        print(render_md(profile, port=args.port))
    else:  # both
        print(render_md(profile, port=args.port))
        print("\n---\n")
        print(json.dumps(profile.to_json(), indent=2))


def main():
    p = argparse.ArgumentParser(
        prog="docs_gen.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    pd = sub.add_parser("detect", help="list detected packages")
    pd.add_argument("--root", default=".")
    pd.set_defaults(func=cmd_detect)

    ps = sub.add_parser("scan", help="scan + emit docs for all packages")
    ps.add_argument("--root", default=".")
    ps.add_argument("--output", default="docs/crates/")
    ps.add_argument("--format", choices=["json", "md", "both"], default="both")
    ps.add_argument("--only", help="comma-separated package leaf-name list to restrict scan")
    ps.add_argument("--port", action="store_true",
                    help="use `port/` instead of `crates/` in rendered headers")
    ps.add_argument("-v", "--verbose", action="store_true")
    ps.set_defaults(func=cmd_scan)

    po = sub.add_parser("one", help="scan one package, print to stdout")
    po.add_argument("pkg")
    po.add_argument("--format", choices=["json", "md", "both"], default="both")
    po.add_argument("--port", action="store_true")
    po.set_defaults(func=cmd_one)

    args = p.parse_args(sys.argv[1:] or ["detect"])
    args.func(args)


if __name__ == "__main__":
    main()
