#!/usr/bin/env python3
"""kaizen docs_gen — generic workspace documentation generator.

Stdlib-only. Matches shodan's `cargo xtask docs --json` shape but
language-agnostic: detects Rust (Cargo.toml), JS/TS (package.json),
Go (go.mod), and Python (pyproject.toml) packages anywhere under the
workspace root and emits one `.md` + one `.json` per package.

Output dir defaults to `docs/crates/` (shodan's convention). Each
emitted JSON record:

    {
      "schema_version": 1,
      "kind": "kaizen.docs",
      "name": "shodan-core",
      "path": "crates/core",
      "language": "rust",
      "version": "0.1.0",
      "loc": { "src": 1234, "test": 200, "total": 1434 },
      "files": { "src": 28, "test": 5, "total": 33 },
      "deps": ["shodan-port-x"],
      "dev_deps": ["criterion"],
      "public_api": {
        "fn": 42, "struct": 8, "trait": 3, "enum": 2,
        "names": ["build_registry", "Context", "Node", ...]
      },
      "scanned_at": "2026-05-11T22:50:12Z"
    }

The companion `.md` is a human-readable summary derived from the same
data.

## Usage

    docs_gen.py scan [--root .] [--output docs/crates/] [--format both]
    docs_gen.py detect [--root .]      # list detected packages, no write
    docs_gen.py one <pkg_dir> [--format both]   # single package
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional


try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover — only on older Python
    tomllib = None  # type: ignore[assignment]


SCHEMA_VERSION = 1
KIND = "kaizen.docs"


# ─── Language detection ──────────────────────────────────────────────


LANG_MARKERS: dict[str, str] = {
    "Cargo.toml": "rust",
    "package.json": "js",
    "go.mod": "go",
    "pyproject.toml": "python",
}


def detect_packages(root: Path) -> list[tuple[Path, str]]:
    """Return [(package_dir, language)] for every detected package.

    Skips common ignore dirs (target/, node_modules/, .git/, vendor/,
    dist/, build/, .venv/).
    """
    SKIP = {"target", "node_modules", ".git", "vendor", "dist", "build",
            ".venv", "venv", "__pycache__", ".kaizen", ".workflow",
            ".claude", ".idea"}
    found: list[tuple[Path, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip dirs in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP and not d.startswith(".")]
        for marker, lang in LANG_MARKERS.items():
            if marker in filenames:
                found.append((Path(dirpath), lang))
                break  # one marker per dir wins
    return found


# ─── LOC + file counts ───────────────────────────────────────────────


LANG_EXTS: dict[str, list[str]] = {
    "rust": [".rs"],
    "js": [".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"],
    "go": [".go"],
    "python": [".py"],
}


def is_test_file(path: Path, language: str) -> bool:
    name = path.name
    if language == "rust":
        return "test" in path.parts or name.endswith("_test.rs")
    if language == "js":
        return ".test." in name or ".spec." in name or "__tests__" in path.parts
    if language == "go":
        return name.endswith("_test.go")
    if language == "python":
        return name.startswith("test_") or name.endswith("_test.py") or "tests" in path.parts
    return False


def count_loc(pkg_dir: Path, language: str) -> tuple[dict, dict]:
    """Return (loc, files) dicts. LOC = non-blank, non-comment-only lines."""
    src_loc = test_loc = 0
    src_files = test_files = 0
    exts = LANG_EXTS.get(language, [])
    for path in pkg_dir.rglob("*"):
        if not path.is_file() or path.suffix not in exts:
            continue
        # Skip if inside a nested package (would double-count workspace members)
        if any(p in {"target", "node_modules", "vendor", "dist", "build"}
               for p in path.relative_to(pkg_dir).parts):
            continue
        try:
            lines = path.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        loc = sum(1 for l in lines if l.strip() and not l.strip().startswith(("//", "#")))
        if is_test_file(path, language):
            test_loc += loc
            test_files += 1
        else:
            src_loc += loc
            src_files += 1
    loc = {"src": src_loc, "test": test_loc, "total": src_loc + test_loc}
    files = {"src": src_files, "test": test_files, "total": src_files + test_files}
    return loc, files


# ─── Manifest parsing ────────────────────────────────────────────────


def _coerce_version(v) -> str:
    """Workspace-inherited Cargo versions are dicts like {'workspace': True}."""
    if isinstance(v, str):
        return v
    if isinstance(v, dict) and v.get("workspace"):
        return "workspace"
    return "0.0.0"


def parse_rust(pkg_dir: Path) -> dict:
    cargo = pkg_dir / "Cargo.toml"
    if tomllib:
        try:
            data = tomllib.loads(cargo.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            return {}
        pkg = data.get("package", {})
        return {
            "name": pkg.get("name", pkg_dir.name),
            "version": _coerce_version(pkg.get("version", "0.0.0")),
            "deps": sorted(data.get("dependencies", {}).keys()),
            "dev_deps": sorted(data.get("dev-dependencies", {}).keys()),
        }
    # Fallback: regex (older Python — rare)
    text = cargo.read_text(errors="ignore")
    name_m = re.search(r'^name\s*=\s*"([^"]+)"', text, re.MULTILINE)
    ver_m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return {
        "name": name_m.group(1) if name_m else pkg_dir.name,
        "version": ver_m.group(1) if ver_m else "0.0.0",
        "deps": [],
        "dev_deps": [],
    }


def parse_js(pkg_dir: Path) -> dict:
    pj = pkg_dir / "package.json"
    try:
        data = json.loads(pj.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        "name": data.get("name", pkg_dir.name),
        "version": data.get("version", "0.0.0"),
        "deps": sorted(data.get("dependencies", {}).keys()),
        "dev_deps": sorted(data.get("devDependencies", {}).keys()),
    }


def parse_go(pkg_dir: Path) -> dict:
    gm = pkg_dir / "go.mod"
    try:
        text = gm.read_text()
    except OSError:
        return {}
    module_m = re.search(r"^module\s+(\S+)", text, re.MULTILINE)
    deps = re.findall(r"^\s*(\S+/\S+)\s+v\S+", text, re.MULTILINE)
    return {
        "name": module_m.group(1).split("/")[-1] if module_m else pkg_dir.name,
        "version": "0.0.0",
        "deps": sorted(set(deps)),
        "dev_deps": [],
    }


def parse_python(pkg_dir: Path) -> dict:
    pp = pkg_dir / "pyproject.toml"
    if tomllib:
        try:
            data = tomllib.loads(pp.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            return {}
    else:
        data = {}
    project = data.get("project", {})
    return {
        "name": project.get("name", pkg_dir.name),
        "version": project.get("version", "0.0.0"),
        "deps": project.get("dependencies", []),
        "dev_deps": project.get("optional-dependencies", {}).get("dev", []),
    }


PARSERS = {"rust": parse_rust, "js": parse_js, "go": parse_go, "python": parse_python}


# ─── Public API surface (heuristic) ──────────────────────────────────


API_PATTERNS: dict[str, list[tuple[str, re.Pattern]]] = {
    "rust": [
        ("fn",     re.compile(r"^\s*pub\s+(?:async\s+|unsafe\s+|const\s+)*fn\s+(\w+)", re.MULTILINE)),
        ("struct", re.compile(r"^\s*pub\s+struct\s+(\w+)", re.MULTILINE)),
        ("trait",  re.compile(r"^\s*pub\s+(?:unsafe\s+)?trait\s+(\w+)", re.MULTILINE)),
        ("enum",   re.compile(r"^\s*pub\s+enum\s+(\w+)", re.MULTILINE)),
    ],
    "js": [
        ("fn",     re.compile(r"^\s*export\s+(?:async\s+)?function\s+(\w+)", re.MULTILINE)),
        ("class",  re.compile(r"^\s*export\s+class\s+(\w+)", re.MULTILINE)),
        ("const",  re.compile(r"^\s*export\s+const\s+(\w+)", re.MULTILINE)),
    ],
    "go": [
        ("fn",     re.compile(r"^func\s+(?:\(\w+\s+\*?\w+\)\s+)?([A-Z]\w*)", re.MULTILINE)),
        ("struct", re.compile(r"^type\s+([A-Z]\w*)\s+struct", re.MULTILINE)),
        ("interface", re.compile(r"^type\s+([A-Z]\w*)\s+interface", re.MULTILINE)),
    ],
    "python": [
        ("fn",     re.compile(r"^def\s+([a-z]\w*)", re.MULTILINE)),
        ("class",  re.compile(r"^class\s+(\w+)", re.MULTILINE)),
    ],
}


def public_api(pkg_dir: Path, language: str) -> dict:
    out: dict = {"names": []}
    patterns = API_PATTERNS.get(language, [])
    counts = {kind: 0 for kind, _ in patterns}
    for path in pkg_dir.rglob("*"):
        if not path.is_file() or path.suffix not in LANG_EXTS.get(language, []):
            continue
        if is_test_file(path, language):
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for kind, pattern in patterns:
            for m in pattern.finditer(text):
                counts[kind] += 1
                if len(out["names"]) < 30:  # cap to keep JSON small
                    out["names"].append(m.group(1))
    out.update(counts)
    out["names"] = sorted(set(out["names"]))
    return out


# ─── Per-package record ──────────────────────────────────────────────


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def scan_package(pkg_dir: Path, language: str, workspace_root: Path) -> dict:
    rel_path = str(pkg_dir.relative_to(workspace_root))
    parser = PARSERS.get(language)
    manifest = parser(pkg_dir) if parser else {}
    loc, files = count_loc(pkg_dir, language)
    api = public_api(pkg_dir, language)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "name": manifest.get("name", pkg_dir.name),
        "path": rel_path,
        "language": language,
        "version": manifest.get("version", "0.0.0"),
        "loc": loc,
        "files": files,
        "deps": manifest.get("deps", []),
        "dev_deps": manifest.get("dev_deps", []),
        "public_api": api,
        "scanned_at": now_iso(),
    }


# ─── Markdown emission ───────────────────────────────────────────────


def render_md(record: dict) -> str:
    name = record["name"]
    path = record["path"]
    lang = record["language"]
    ver = record["version"]
    loc = record["loc"]
    files = record["files"]
    api = record["public_api"]
    deps = record["deps"]
    dev_deps = record["dev_deps"]
    api_count = sum(v for k, v in api.items() if isinstance(v, int))
    lines = [
        f"# {name}",
        "",
        f"**Path**: `{path}` · **Language**: {lang} · **Version**: {ver}",
        f"**LOC**: {loc['src']} src + {loc['test']} test = {loc['total']} total",
        f"**Files**: {files['src']} src + {files['test']} test = {files['total']} total",
        "",
        "## Public API surface",
        "",
    ]
    api_lines = []
    for k in ("fn", "struct", "trait", "enum", "class", "const", "interface"):
        if k in api and api[k]:
            api_lines.append(f"- **{k}**: {api[k]}")
    lines.extend(api_lines if api_lines else ["_(none detected)_"])
    if api.get("names"):
        lines.append("")
        lines.append("Sample names: " + ", ".join(f"`{n}`" for n in api["names"][:12]))
    if deps:
        lines.extend(["", "## Dependencies", ""] + [f"- `{d}`" for d in deps])
    if dev_deps:
        lines.extend(["", "## Dev dependencies", ""] + [f"- `{d}`" for d in dev_deps])
    lines.extend(["", f"_Scanned {record['scanned_at']} by kaizen docs_gen._", ""])
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────


def cmd_detect(args):
    root = Path(args.root).resolve()
    packages = detect_packages(root)
    for pkg_dir, lang in packages:
        print(f"{lang}\t{pkg_dir.relative_to(root)}")
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
    written = []
    for pkg_dir, lang in packages:
        record = scan_package(pkg_dir, lang, root)
        if args.format in ("json", "both"):
            jp = out_dir / f"{record['name']}.json"
            jp.write_text(json.dumps(record, indent=2) + "\n")
            written.append(str(jp.relative_to(root)))
        if args.format in ("md", "both"):
            mp = out_dir / f"{record['name']}.md"
            mp.write_text(render_md(record))
            written.append(str(mp.relative_to(root)))
    print(f"wrote {len(written)} files to {out_dir.relative_to(root)}/")
    if args.verbose:
        for w in written:
            print(f"  - {w}")


def cmd_one(args):
    pkg_dir = Path(args.pkg).resolve()
    if not pkg_dir.is_dir():
        sys.exit(f"not a directory: {pkg_dir}")
    # Detect this package's language
    lang: Optional[str] = None
    for marker, candidate in LANG_MARKERS.items():
        if (pkg_dir / marker).exists():
            lang = candidate
            break
    if not lang:
        sys.exit(f"no recognised manifest in {pkg_dir}")
    workspace_root = pkg_dir
    # Walk up to find workspace root (any parent with a marker)
    cur = pkg_dir.parent
    while cur != cur.parent:
        if any((cur / m).exists() for m in LANG_MARKERS):
            workspace_root = cur
        cur = cur.parent
    record = scan_package(pkg_dir, lang, workspace_root)
    if args.format == "json":
        print(json.dumps(record, indent=2))
    elif args.format == "md":
        print(render_md(record))
    else:  # both
        print(render_md(record))
        print("\n---\n")
        print(json.dumps(record, indent=2))


def main():
    p = argparse.ArgumentParser(prog="docs_gen.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pd = sub.add_parser("detect", help="list detected packages")
    pd.add_argument("--root", default=".")
    pd.set_defaults(func=cmd_detect)

    ps = sub.add_parser("scan", help="scan + emit docs for all packages")
    ps.add_argument("--root", default=".")
    ps.add_argument("--output", default="docs/crates/")
    ps.add_argument("--format", choices=["json", "md", "both"], default="both")
    ps.add_argument("-v", "--verbose", action="store_true")
    ps.set_defaults(func=cmd_scan)

    po = sub.add_parser("one", help="scan one package, print to stdout")
    po.add_argument("pkg")
    po.add_argument("--format", choices=["json", "md", "both"], default="both")
    po.set_defaults(func=cmd_one)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
