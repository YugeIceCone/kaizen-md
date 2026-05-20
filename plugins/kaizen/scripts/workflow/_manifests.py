"""Multi-language manifest hygiene — roadmap X3.

Generalizes the existing shodan `xtask manifests` (Cargo-only) to a
4-language audit chain: Cargo.toml + package.json + pyproject.toml +
go.mod. Per-language adapter pattern; shared orchestrator.

## Scope

  audit:     list every detected manifest + its dep list (read-only)
  unused:    heuristic per-language unused-dep detection

The full `promote` operation (workspace ↔ package-version reconciliation)
is Cargo-specific and stays in shodan's xtask for now — out of scope
for the generalized Python version.

## Adapter API

Each language adapter is a class with:
  detect(root: Path) -> list[Path]      # find manifest files
  parse(path: Path) -> Manifest         # extract deps + metadata
  unused(manifest, source_tree) -> [Dep]  # heuristic unused detection

## Source-tree scanning for unused detection

Per-language heuristic. Not a true static analyzer — pure-text grep over
.rs / .py / .ts / .js / .go files. False positives possible but cheap.
"""
from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import Iterable

# ─── Data ────────────────────────────────────────────────────────────

@dataclasses.dataclass
class Dep:
    name: str
    version: str = ""
    kind: str = ""  # "dev", "build", "optional", etc.

@dataclasses.dataclass
class Manifest:
    language: str
    path: str
    deps: list[Dep]

# ─── TOML loading (stdlib) ───────────────────────────────────────────

def _load_toml(path: Path) -> dict | None:
    """Stdlib tomllib (Python 3.11+). Returns None on parse failure
    or missing file."""
    try:
        import tomllib
    except ImportError:
        # Fallback: minimal-no-op parse via toml-style line scan.
        return _toml_fallback_parse(path)
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return None

def _toml_fallback_parse(path: Path) -> dict:
    """Bare-bones fallback when tomllib is unavailable (Python <3.11).
    Just finds top-level table markers; sufficient for our adapter use."""
    out: dict = {}
    if not path.is_file():
        return out
    current = None
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("[") and s.endswith("]"):
            key = s[1:-1]
            parts = key.split(".")
            d = out
            for p in parts[:-1]:
                d = d.setdefault(p, {})
            current = d.setdefault(parts[-1], {})
            continue
        if "=" in s and isinstance(current, dict):
            k, _, v = s.partition("=")
            current[k.strip()] = v.strip().strip('"').strip("'")
    return out

# ─── Per-language adapters ───────────────────────────────────────────

class CargoAdapter:
    LANGUAGE = "rust"
    MANIFEST = "Cargo.toml"

    def detect(self, root: Path) -> list[Path]:
        manifests = []
        for p in root.rglob("Cargo.toml"):
            # Skip vendored / target dirs
            sp = str(p)
            if "/target/" in sp or "/vendor/" in sp:
                continue
            manifests.append(p)
        return sorted(manifests)

    def parse(self, path: Path) -> Manifest | None:
        data = _load_toml(path)
        if data is None:
            return None
        deps: list[Dep] = []
        for table, kind in [
            ("dependencies", ""),
            ("dev-dependencies", "dev"),
            ("build-dependencies", "build"),
        ]:
            d = data.get(table, {})
            if not isinstance(d, dict):
                continue
            for name, spec in d.items():
                version = ""
                if isinstance(spec, str):
                    version = spec
                elif isinstance(spec, dict):
                    version = str(spec.get("version", "")) if spec.get("version") else ""
                deps.append(Dep(name=name, version=version, kind=kind))
        # workspace.dependencies (root manifests)
        ws = data.get("workspace", {})
        if isinstance(ws, dict):
            wsd = ws.get("dependencies", {})
            if isinstance(wsd, dict):
                for name, spec in wsd.items():
                    version = ""
                    if isinstance(spec, str):
                        version = spec
                    elif isinstance(spec, dict):
                        version = str(spec.get("version", "")) if spec.get("version") else ""
                    deps.append(Dep(name=name, version=version, kind="workspace"))
        return Manifest(language=self.LANGUAGE, path=str(path), deps=deps)

    def used_in_source(self, dep_name: str, source_files: list[Path]) -> bool:
        # Rust: `use <name>::` or `<name>::` or extern crate
        # Crate names with `-` become `_` in Rust source.
        rust_name = dep_name.replace("-", "_")
        patterns = [
            re.compile(rf"\buse\s+{re.escape(rust_name)}\b"),
            re.compile(rf"\bextern\s+crate\s+{re.escape(rust_name)}\b"),
            re.compile(rf"\b{re.escape(rust_name)}::"),
        ]
        return _search_files(source_files, patterns)

class PackageJsonAdapter:
    LANGUAGE = "javascript"
    MANIFEST = "package.json"

    def detect(self, root: Path) -> list[Path]:
        return sorted(
            p for p in root.rglob("package.json")
            if "/node_modules/" not in str(p)
        )

    def parse(self, path: Path) -> Manifest | None:
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        deps: list[Dep] = []
        for key, kind in [
            ("dependencies", ""),
            ("devDependencies", "dev"),
            ("peerDependencies", "peer"),
            ("optionalDependencies", "optional"),
        ]:
            entries = data.get(key, {})
            if not isinstance(entries, dict):
                continue
            for name, version in entries.items():
                deps.append(Dep(name=name, version=str(version), kind=kind))
        return Manifest(language=self.LANGUAGE, path=str(path), deps=deps)

    def used_in_source(self, dep_name: str, source_files: list[Path]) -> bool:
        # import / require — quote-bounded so substring deps don't match
        esc = re.escape(dep_name)
        patterns = [
            re.compile(rf"""require\s*\(\s*['"]{esc}(?:/|['"])"""),
            re.compile(rf"""from\s+['"]{esc}(?:/|['"])"""),
            re.compile(rf"""import\s+['"]{esc}(?:/|['"])"""),
        ]
        return _search_files(source_files, patterns)

class PyprojectAdapter:
    LANGUAGE = "python"
    MANIFEST = "pyproject.toml"

    def detect(self, root: Path) -> list[Path]:
        return sorted(p for p in root.rglob("pyproject.toml")
                       if "/.venv/" not in str(p) and "/venv/" not in str(p))

    def parse(self, path: Path) -> Manifest | None:
        data = _load_toml(path)
        if data is None:
            return None
        deps: list[Dep] = []
        # PEP 621: [project] dependencies
        proj = data.get("project", {})
        if isinstance(proj, dict):
            for d in proj.get("dependencies", []) or []:
                if isinstance(d, str):
                    name, version = _parse_pep508(d)
                    deps.append(Dep(name=name, version=version))
            opt = proj.get("optional-dependencies", {})
            if isinstance(opt, dict):
                for group, group_deps in opt.items():
                    if not isinstance(group_deps, list):
                        continue
                    for d in group_deps:
                        if isinstance(d, str):
                            name, version = _parse_pep508(d)
                            deps.append(Dep(name=name, version=version, kind=f"optional:{group}"))
        # Poetry: [tool.poetry.dependencies]
        poetry = data.get("tool", {}).get("poetry", {})
        if isinstance(poetry, dict):
            for table, kind in [
                ("dependencies", ""),
                ("dev-dependencies", "dev"),
            ]:
                pd = poetry.get(table, {})
                if not isinstance(pd, dict):
                    continue
                for name, spec in pd.items():
                    if name == "python":
                        continue
                    version = spec if isinstance(spec, str) else str(spec.get("version", ""))
                    deps.append(Dep(name=name, version=version, kind=kind))
        return Manifest(language=self.LANGUAGE, path=str(path), deps=deps)

    def used_in_source(self, dep_name: str, source_files: list[Path]) -> bool:
        py_name = dep_name.replace("-", "_")
        patterns = [
            re.compile(rf"^\s*import\s+{re.escape(py_name)}\b", re.MULTILINE),
            re.compile(rf"^\s*from\s+{re.escape(py_name)}(\.|$|\s)", re.MULTILINE),
        ]
        return _search_files(source_files, patterns)

class GoModAdapter:
    LANGUAGE = "go"
    MANIFEST = "go.mod"

    def detect(self, root: Path) -> list[Path]:
        return sorted(p for p in root.rglob("go.mod")
                       if "/vendor/" not in str(p))

    def parse(self, path: Path) -> Manifest | None:
        try:
            text = path.read_text()
        except OSError:
            return None
        deps: list[Dep] = []
        # Both block-form `require (...)` and line-form `require <name> <version>`
        block_re = re.compile(r"require\s*\(([^)]*)\)", re.DOTALL)
        line_re = re.compile(r"^\s*([^\s]+)\s+([^\s]+)(?:\s+//\s*indirect)?\s*$",
                             re.MULTILINE)
        # block form
        for m in block_re.finditer(text):
            for lm in line_re.finditer(m.group(1)):
                deps.append(Dep(name=lm.group(1), version=lm.group(2)))
        # also single-line require
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("require ") and "(" not in s:
                parts = s[len("require "):].split()
                if len(parts) >= 2:
                    deps.append(Dep(name=parts[0], version=parts[1]))
        return Manifest(language=self.LANGUAGE, path=str(path), deps=deps)

    def used_in_source(self, dep_name: str, source_files: list[Path]) -> bool:
        # Go: `import "<dep_name>"` (or grouped imports)
        esc = re.escape(dep_name)
        patterns = [re.compile(rf'"\s*{esc}["/]')]
        return _search_files(source_files, patterns)

ADAPTERS: list = [
    CargoAdapter(),
    PackageJsonAdapter(),
    PyprojectAdapter(),
    GoModAdapter(),
]

# ─── Helpers ─────────────────────────────────────────────────────────

def _parse_pep508(spec: str) -> tuple[str, str]:
    """Parse 'name[extra]>=1.0' → ('name', '>=1.0'). Best-effort."""
    s = spec.strip()
    # Strip extras
    bracket = s.find("[")
    if bracket >= 0:
        end = s.find("]", bracket)
        if end > bracket:
            s = s[:bracket] + s[end + 1:]
    # Find first version operator
    for op in (">=", "<=", "==", "!=", "~=", ">", "<"):
        if op in s:
            name, _, ver = s.partition(op)
            return name.strip(), op + ver.strip()
    return s.strip(), ""

def _search_files(files: Iterable[Path], patterns: list[re.Pattern]) -> bool:
    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        for pat in patterns:
            if pat.search(text):
                return True
    return False

SOURCE_EXTS = {
    "rust": (".rs",),
    "python": (".py",),
    "javascript": (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"),
    "go": (".go",),
}

def _source_files_for(language: str, root: Path) -> list[Path]:
    exts = SOURCE_EXTS.get(language, ())
    out: list[Path] = []
    skip_dirs = {"target", "node_modules", "vendor", ".venv", "venv",
                 ".git", "__pycache__", "dist", "build"}
    for ext in exts:
        for p in root.rglob(f"*{ext}"):
            if any(part in skip_dirs for part in p.parts):
                continue
            out.append(p)
    return out

# ─── Orchestrator ────────────────────────────────────────────────────

def audit(root: Path) -> dict:
    """Audit every manifest under `root`. Returns
    {languages, manifests: [Manifest], total_deps}."""
    manifests: list[Manifest] = []
    langs_found: set[str] = set()
    for adapter in ADAPTERS:
        for mp in adapter.detect(root):
            m = adapter.parse(mp)
            if m is None:
                continue
            manifests.append(m)
            langs_found.add(adapter.LANGUAGE)
    total = sum(len(m.deps) for m in manifests)
    return {
        "root": str(root),
        "languages": sorted(langs_found),
        "manifests": manifests,
        "total_deps": total,
    }

def unused(root: Path) -> dict:
    """Detect heuristically-unused deps across all manifests. Returns
    {root, unused: [{language, manifest, dep_name}, ...]}.

    Heuristic: a dep is "unused" iff no source-tree file contains an
    import/require/use mention. Cheap pure-text grep. False positives
    possible (deps used only at build time, via macros, etc.) — treat
    output as a cleanup-candidate list, not gospel."""
    findings: list[dict] = []
    for adapter in ADAPTERS:
        for mp in adapter.detect(root):
            m = adapter.parse(mp)
            if m is None:
                continue
            source_files = _source_files_for(adapter.LANGUAGE, root)
            for dep in m.deps:
                # Skip non-import-able kinds: workspace, peer
                if dep.kind in ("workspace", "peer"):
                    continue
                if not adapter.used_in_source(dep.name, source_files):
                    findings.append({
                        "language": adapter.LANGUAGE,
                        "manifest": m.path,
                        "dep_name": dep.name,
                        "version": dep.version,
                        "kind": dep.kind,
                    })
    return {"root": str(root), "unused": findings, "count": len(findings)}

def languages_present(root: Path) -> list[str]:
    found = set()
    for adapter in ADAPTERS:
        if adapter.detect(root):
            found.add(adapter.LANGUAGE)
    return sorted(found)

def format_audit(result: dict) -> str:
    lines = [f"root: {result['root']}",
             f"languages: {', '.join(result['languages']) or '(none)'}",
             ""]
    for m in result["manifests"]:
        lines.append(f"  {m.language:<11} {m.path}  ({len(m.deps)} deps)")
    lines.append("")
    lines.append(f"total deps across {len(result['manifests'])} manifests: "
                 f"{result['total_deps']}")
    return "\n".join(lines)

def format_unused(result: dict) -> str:
    if not result["unused"]:
        return f"no unused deps detected in {result['root']}"
    lines = [f"unused deps in {result['root']}:"]
    for f in result["unused"]:
        kind = f" [{f['kind']}]" if f['kind'] else ""
        lines.append(f"  {f['language']:<11} {f['dep_name']} ({f['version']}){kind}")
        lines.append(f"    in {f['manifest']}")
    lines.append("")
    lines.append(f"{result['count']} candidate(s) — verify before removing")
    return "\n".join(lines)
