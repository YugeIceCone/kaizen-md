#!/usr/bin/env python3
"""kaizen detect-stack — mechanical stack detection → .agents/stack-context.md.

Scripted counterpart to the agent-instructional `kaizen:detect-stack`
skill. Walks the cwd / project root, reads the first matching manifest
+ counts file extensions + scans CI configs + checks for convention
files. Writes `.agents/stack-context.md` in the same shape the skill
documents.

Mechanical only — no LLM calls. Stays fast (~100ms on a mid-size repo)
so the SessionStart hook can fire it inline.

## Subcommands

  scan [--out <path>] [--force]   — detect + write the artifact
  show                             — print existing artifact (or fail)
  path                             — print resolved output path
  stale [--max-days N]             — exit 0 if fresh, 1 if missing/stale

## Output

`<project-root>/.agents/stack-context.md` — the artifact path is
fixed per the kaizen:detect-stack skill spec.

## Refresh policy

`scan` skips work when the artifact exists + is <30 days old (per the
skill's "When to Re-Run" section). `--force` overrides.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Optional


# ─── Detection tables ────────────────────────────────────────────────


# extension → (language, weight-multiplier)
# Weight lets us discount build-output files vs source.
_EXT_LANG: dict[str, str] = {
    ".rs": "Rust",
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".go": "Go",
    ".swift": "Swift",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".cs": "C#",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".elm": "Elm",
    ".cpp": "C++",
    ".cc": "C++",
    ".c": "C",
    ".h": "C/C++ header",
    ".hpp": "C++ header",
    ".php": "PHP",
    ".scala": "Scala",
    ".clj": "Clojure",
    ".hs": "Haskell",
    ".ml": "OCaml",
}

# Skip dirs entirely
_SKIP_DIRS: set[str] = {
    "node_modules", ".git", "target", "dist", "build", "__pycache__",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
    ".next", ".nuxt", "coverage", "vendor", ".gradle", ".idea",
    ".vscode", "out", "bin", "obj", "Pods", "DerivedData",
}

# manifest → (language, parse_fn_name)
_MANIFEST_TO_LANG: list[tuple[str, str]] = [
    ("Cargo.toml",       "Rust"),
    ("package.json",     "JavaScript/TypeScript"),
    ("go.mod",           "Go"),
    ("pyproject.toml",   "Python"),
    ("requirements.txt", "Python"),
    ("Gemfile",          "Ruby"),
    ("Package.swift",    "Swift"),
    ("mix.exs",          "Elixir"),
    ("build.gradle",     "Java/Kotlin"),
    ("build.gradle.kts", "Kotlin"),
    ("pom.xml",          "Java"),
    ("composer.json",    "PHP"),
    ("CMakeLists.txt",   "C/C++"),
    ("Makefile",         "C/C++ (Makefile)"),
]

_CI_PATHS: list[tuple[str, str]] = [
    (".github/workflows",   "GitHub Actions"),
    (".gitlab-ci.yml",      "GitLab CI"),
    (".circleci/config.yml", "CircleCI"),
    ("azure-pipelines.yml", "Azure Pipelines"),
    ("Jenkinsfile",         "Jenkins"),
    (".drone.yml",          "Drone"),
    ("bitbucket-pipelines.yml", "Bitbucket Pipelines"),
]

_CONV_FILES: list[str] = [
    "CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md", "README.md",
    ".editorconfig", ".pre-commit-config.yaml",
]


# ─── Project root + output paths ─────────────────────────────────────


def _project_root(start: Optional[Path] = None) -> Path:
    """Walk up looking for any manifest or `.git`. Falls back to cwd."""
    cwd = (start or Path.cwd()).resolve()
    markers = {".git", ".kaizen", "Cargo.toml", "package.json", "go.mod",
                "pyproject.toml", "Gemfile", "Package.swift", "mix.exs",
                "build.gradle", "pom.xml", "composer.json"}
    for d in [cwd, *cwd.parents]:
        if any((d / m).exists() for m in markers):
            return d
    return cwd


def _output_path(root: Optional[Path] = None) -> Path:
    return (root or _project_root()) / ".agents" / "stack-context.md"


# ─── Walkers + counters ──────────────────────────────────────────────


def _count_languages(root: Path, max_files: int = 5000) -> Counter:
    """Walk source files, count by language. Bounded to keep <100ms."""
    counts: Counter = Counter()
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext in _EXT_LANG:
                counts[_EXT_LANG[ext]] += 1
                n += 1
                if n >= max_files:
                    return counts
    return counts


def _find_manifests(root: Path) -> list[tuple[str, str, Path]]:
    """Return (manifest_name, language_label, path) for each shipped."""
    out = []
    for name, lang in _MANIFEST_TO_LANG:
        p = root / name
        if p.is_file():
            out.append((name, lang, p))
    return out


def _detect_ci(root: Path) -> list[str]:
    """Return list of detected CI systems."""
    out = []
    for rel, label in _CI_PATHS:
        p = root / rel
        if p.exists():
            out.append(label)
    return out


def _convention_files_present(root: Path) -> list[str]:
    return [n for n in _CONV_FILES if (root / n).is_file()]


# ─── Framework + build/test/lint sniffing ────────────────────────────


def _read_safe(p: Path, max_kb: int = 64) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")[:max_kb * 1024]
    except OSError:
        return ""


def _sniff_rust(cargo_toml: str) -> dict:
    """Heuristic-grep Cargo.toml for framework + version info."""
    out: dict = {"build": "cargo", "test": "cargo test"}
    # edition
    m = re.search(r'^edition\s*=\s*"(\d{4})"', cargo_toml, re.MULTILINE)
    if m:
        out["edition"] = m.group(1)
    # well-known crates → framework label
    fw: list[str] = []
    for crate in ("axum", "actix-web", "rocket", "warp", "tokio",
                   "diesel", "sqlx", "sea-orm", "rusqlite", "ort",
                   "anyhow", "thiserror"):
        if re.search(rf'\b{re.escape(crate)}\s*=', cargo_toml):
            fw.append(crate)
    if fw:
        out["frameworks"] = fw[:5]
    # rust-toolchain / clippy.toml hints
    return out


def _sniff_pyproject(text: str) -> dict:
    out: dict = {"build": "uv|poetry|hatch (parse pyproject)", "test": "pytest"}
    if re.search(r'\bpytest\b', text):
        out["test"] = "pytest"
    if re.search(r'\b(ruff|black|flake8)\b', text):
        out["lint"] = re.findall(r'\b(ruff|black|flake8|mypy)\b', text)[:3]
    fw = []
    for pkg in ("django", "flask", "fastapi", "starlette", "sqlalchemy",
                  "pydantic", "httpx"):
        if re.search(rf'\b{pkg}\b', text, re.IGNORECASE):
            fw.append(pkg)
    if fw:
        out["frameworks"] = fw[:5]
    return out


def _sniff_pkg_json(text: str) -> dict:
    out: dict = {"build": "npm/yarn/pnpm", "test": "npm test"}
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return out
    deps = {**data.get("dependencies", {}),
            **data.get("devDependencies", {})}
    fw: list[str] = []
    for pkg in ("react", "next", "svelte", "vue", "express", "fastify",
                  "prisma", "trpc", "tailwindcss", "vite"):
        if pkg in deps:
            fw.append(f"{pkg}@{deps[pkg]}")
    if fw:
        out["frameworks"] = fw[:5]
    if "scripts" in data and "test" in data["scripts"]:
        out["test"] = data["scripts"]["test"]
    return out


def _sniff_go_mod(text: str) -> dict:
    out: dict = {"build": "go build", "test": "go test ./..."}
    m = re.search(r'^go\s+(\S+)', text, re.MULTILINE)
    if m:
        out["go_version"] = m.group(1)
    fw = []
    for pkg in ("gin", "echo", "fiber", "chi", "sqlc"):
        if re.search(rf'\b{pkg}\b', text):
            fw.append(pkg)
    if fw:
        out["frameworks"] = fw[:5]
    return out


_SNIFFERS = {
    "Cargo.toml":     _sniff_rust,
    "pyproject.toml": _sniff_pyproject,
    "package.json":   _sniff_pkg_json,
    "go.mod":         _sniff_go_mod,
}


# ─── Render ──────────────────────────────────────────────────────────


def _render(root: Path, lang_counts: Counter, manifests: list,
             ci: list[str], conventions: list[str],
             sniffed: dict) -> str:
    primary = lang_counts.most_common(1)[0][0] if lang_counts else "Unknown"
    secondary = [(l, n) for l, n in lang_counts.most_common(4) if l != primary]

    lines = ["# Stack Context", ""]
    lines.append(f"Generated: {_dt.date.today().isoformat()}")
    lines.append("")
    lines.append("## Stack")
    lines.append(f"- **Language**: {primary}"
                 + (f" (Edition {sniffed.get('edition')})" if sniffed.get('edition')
                    else (f" (v{sniffed.get('go_version')})" if sniffed.get('go_version')
                          else "")))
    if sniffed.get("frameworks"):
        lines.append(f"- **Framework**: {', '.join(sniffed['frameworks'])}")
    if sniffed.get("build"):
        lines.append(f"- **Build**: `{sniffed['build']}`")
    if sniffed.get("test"):
        lines.append(f"- **Test**: `{sniffed['test']}`")
    if sniffed.get("lint"):
        lints = sniffed["lint"] if isinstance(sniffed["lint"], list) else [sniffed["lint"]]
        lines.append(f"- **Lint**: {', '.join(lints)} [CI gate: {('yes' if ci else 'unknown')}]")
    lines.append("")

    if secondary:
        lines.append("## Secondary Languages")
        for l, n in secondary:
            lines.append(f"- {l} ({n} files)")
        lines.append("")

    lines.append("## Detected manifests")
    for name, lang, _ in manifests:
        lines.append(f"- `{name}` → {lang}")
    lines.append("")

    if ci:
        lines.append("## CI Systems")
        for c in ci:
            lines.append(f"- {c}")
        lines.append("")

    if conventions:
        lines.append("## Convention files present")
        for c in conventions:
            lines.append(f"- `{c}`")
        lines.append("")

    lines.append(("---\n"
                  "Mechanically generated by `kaizen-detect-stack scan`. "
                  "For nuanced conventions/CI-gate analysis, load the "
                  "`kaizen:detect-stack` skill and let the agent enrich this file."))
    return "\n".join(lines) + "\n"


# ─── Stale check ─────────────────────────────────────────────────────


def _is_stale(p: Path, max_days: int = 30) -> bool:
    if not p.is_file():
        return True
    age_days = (_dt.datetime.now().timestamp() - p.stat().st_mtime) / 86400
    return age_days > max_days


# ─── Commands ────────────────────────────────────────────────────────


def cmd_scan(args) -> int:
    root = _project_root()
    out_path = Path(args.out) if args.out else _output_path(root)

    if not args.force and not _is_stale(out_path, max_days=args.max_days):
        if args.json:
            print(json.dumps({"skipped": True, "path": str(out_path),
                                "reason": "fresh"}))
        else:
            print(f"[detect-stack] skipped — {out_path} is fresh "
                  f"(< {args.max_days} days). Use --force to regenerate.")
        return 0

    lang_counts = _count_languages(root)
    manifests = _find_manifests(root)
    ci = _detect_ci(root)
    conventions = _convention_files_present(root)

    sniffed: dict = {}
    for name, _, path in manifests:
        if name in _SNIFFERS:
            sniffed.update(_SNIFFERS[name](_read_safe(path)))
            break  # first matching manifest wins (per the skill spec)

    body = _render(root, lang_counts, manifests, ci, conventions, sniffed)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")

    if args.json:
        print(json.dumps({
            "path":      str(out_path),
            "bytes":     len(body),
            "primary":   lang_counts.most_common(1)[0][0] if lang_counts else None,
            "manifests": [m[0] for m in manifests],
            "ci":        ci,
        }))
    else:
        print(f"[detect-stack] wrote {out_path} ({len(body)} bytes)")
    return 0


def cmd_show(args) -> int:
    p = _output_path()
    if not p.is_file():
        sys.stderr.write(f"[detect-stack] no artifact at {p} — run scan first\n")
        return 1
    print(p.read_text(encoding="utf-8"), end="")
    return 0


def cmd_path(args) -> int:
    print(_output_path())
    return 0


def cmd_stale(args) -> int:
    p = _output_path()
    return 1 if _is_stale(p, max_days=args.max_days) else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kaizen-detect-stack",
                                 description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("scan", help="detect + write .agents/stack-context.md")
    sc.add_argument("--out", default=None,
                     help="override output path (default: <root>/.agents/stack-context.md)")
    sc.add_argument("--force", action="store_true",
                     help="regenerate even when fresh")
    sc.add_argument("--max-days", type=int, default=30,
                     help="freshness window (default 30)")
    sc.add_argument("--json", action="store_true")
    sc.set_defaults(func=cmd_scan)

    sh = sub.add_parser("show", help="print existing artifact")
    sh.set_defaults(func=cmd_show)

    ph = sub.add_parser("path", help="print resolved output path")
    ph.set_defaults(func=cmd_path)

    st = sub.add_parser("stale", help="exit 1 if missing/stale, 0 if fresh")
    st.add_argument("--max-days", type=int, default=30)
    st.set_defaults(func=cmd_stale)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
