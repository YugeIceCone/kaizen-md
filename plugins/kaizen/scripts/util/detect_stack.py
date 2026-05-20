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

# Tool-version pin files. Each entry: (filename, language-tag-or-None).
# When language-tag is set, the file's first non-comment line becomes
# the pinned version for that language.
_VERSION_PIN_FILES: list[tuple[str, Optional[str]]] = [
    ("rust-toolchain",          "rust"),
    ("rust-toolchain.toml",     "rust"),
    (".python-version",         "python"),
    (".nvmrc",                  "node"),
    (".ruby-version",           "ruby"),
    (".tool-versions",          None),   # asdf — multi-language
    ("mise.toml",               None),   # mise — multi-language
]

# Container / IaC presence markers.
_CONTAINER_MARKERS: dict[str, list[str]] = {
    "dockerfile":  ["Dockerfile", "dockerfile"],
    "compose":     ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"],
    "kubernetes":  ["k8s/", "kubernetes/", "kustomization.yaml", "deployment.yaml"],
    "terraform":   ["main.tf", "terraform/"],
}

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

def _output_path_json(root: Optional[Path] = None) -> Path:
    """Primary output — schema-validated JSON. System of record."""
    return (root or _project_root()) / ".agents" / "stack-context.json"

def _output_path_md(root: Optional[Path] = None) -> Path:
    """Derived view — markdown rendered from the JSON. Human-readable
    + back-compat with the original .md-only artifact path."""
    return (root or _project_root()) / ".agents" / "stack-context.md"

# Back-compat shim: tests + callers that used _output_path get the JSON.
def _output_path(root: Optional[Path] = None) -> Path:
    return _output_path_json(root)

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

def _detect_version_pins(root: Path) -> dict:
    """Scan for toolchain-version pin files. Returns the populated
    `version_pins` block from the schema."""
    out: dict = {
        "rust": None, "python": None, "node": None, "ruby": None,
        "tool_versions_files": [],
    }
    for filename, lang_tag in _VERSION_PIN_FILES:
        p = root / filename
        if not p.is_file():
            continue
        out["tool_versions_files"].append(filename)
        if lang_tag is None:
            continue
        # Read first non-comment, non-blank line as the pinned version.
        try:
            for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or line.startswith("//"):
                    continue
                # rust-toolchain.toml has [toolchain]\nchannel="..."
                m = re.search(r'channel\s*=\s*"([^"]+)"', line)
                if m:
                    out[lang_tag] = m.group(1)
                else:
                    out[lang_tag] = line.split()[0]
                break
        except OSError:
            pass
    return out

def _detect_containerization(root: Path) -> dict:
    """Boolean signals for Docker / Compose / K8s / Terraform."""
    out: dict = {}
    for key, markers in _CONTAINER_MARKERS.items():
        out[key] = any((root / m).exists() for m in markers)
    return out

def _detect_workspace(root: Path, manifests: list) -> dict:
    """Detect monorepo / workspace setup. Returns the schema's
    `workspace` block."""
    out: dict = {"is_workspace": False, "kind": None, "member_count": None}

    # Cargo workspace
    cargo = root / "Cargo.toml"
    if cargo.is_file():
        text = _read_safe(cargo)
        if re.search(r'^\[workspace\]', text, re.MULTILINE):
            members = re.findall(r'members\s*=\s*\[([^\]]+)\]', text)
            if members:
                count = len([m for m in re.split(r'[,\s"]+', members[0]) if m])
                out.update({"is_workspace": True, "kind": "cargo",
                             "member_count": count})
                return out
            out.update({"is_workspace": True, "kind": "cargo"})
            return out

    # JS monorepo — pnpm-workspace.yaml / workspaces in package.json
    if (root / "pnpm-workspace.yaml").is_file():
        out.update({"is_workspace": True, "kind": "pnpm"})
        return out
    if (root / "lerna.json").is_file():
        out.update({"is_workspace": True, "kind": "lerna"})
        return out
    if (root / "nx.json").is_file():
        out.update({"is_workspace": True, "kind": "nx"})
        return out
    if (root / "turbo.json").is_file():
        out.update({"is_workspace": True, "kind": "turbo"})
        return out

    pkg_json = root / "package.json"
    if pkg_json.is_file():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            ws = data.get("workspaces")
            if ws:
                count = len(ws) if isinstance(ws, list) else None
                out.update({"is_workspace": True, "kind": "npm",
                             "member_count": count})
        except (json.JSONDecodeError, ValueError, OSError):
            pass

    return out

def _detect_pre_commit(root: Path) -> dict:
    """Parse .pre-commit-config.yaml for hook count."""
    p = root / ".pre-commit-config.yaml"
    if not p.is_file():
        return {"config_present": False, "hook_count": None}

    text = _read_safe(p)
    # Count `- id:` entries (each is a hook). Cheap regex, no PyYAML.
    hook_count = len(re.findall(r'^\s+-\s+id:\s+\S+', text, re.MULTILINE))
    return {"config_present": True, "hook_count": hook_count}

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

def _self_validate(record: dict) -> Optional[str]:
    """Best-effort schema validation in-script. Returns None on pass,
    error string on failure. Skips silently when jsonschema isn't
    installed (graceful-fallback per the iron law)."""
    try:
        import jsonschema
    except ImportError:
        return None
    schema_path = (Path(__file__).resolve().parent.parent.parent
                    / "assets" / "schemas" / "stack-context.schema.json")
    if not schema_path.is_file():
        return None
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(record, schema)
        return None
    except Exception as e:
        return str(e)

def _build_record(root: Path, lang_counts: Counter, manifests: list,
                    ci: list[str], conventions: list[str],
                    sniffed: dict,
                    version_pins: Optional[dict] = None,
                    containerization: Optional[dict] = None,
                    workspace: Optional[dict] = None,
                    pre_commit: Optional[dict] = None) -> dict:
    """Build the schema-validated dict — the system of record. The
    markdown view is derived from this."""
    primary = lang_counts.most_common(1)[0][0] if lang_counts else "Unknown"
    secondary = [(l, n) for l, n in lang_counts.most_common(4) if l != primary]

    lang_version = None
    if sniffed.get("edition"):
        lang_version = f"Edition {sniffed['edition']}"
    elif sniffed.get("go_version"):
        lang_version = f"go {sniffed['go_version']}"

    lint_field = sniffed.get("lint", [])
    if isinstance(lint_field, str):
        lint_field = [lint_field]

    rec = {
        "schema_version": 1,
        "generated":      _dt.date.today().isoformat(),
        "tool":           "kaizen-detect-stack",
        "root":           str(root),
        "stack": {
            "primary_language": primary,
            "language_version": lang_version,
            "frameworks":       sniffed.get("frameworks", []),
            "build_cmd":        sniffed.get("build"),
            "test_cmd":         sniffed.get("test"),
            "lint":             lint_field,
        },
        "secondary_languages": [
            {"language": l, "file_count": n} for l, n in secondary
        ],
        "manifests": [
            {"name": name, "language": lang, "path": str(path)}
            for name, lang, path in manifests
        ],
        "ci_systems":       ci,
        "convention_files": conventions,
    }
    # Optional enrichment blocks — emit only when populated to keep
    # the artifact lean for projects without these signals.
    if version_pins and (any(version_pins.get(k) for k in ("rust", "python", "node", "ruby"))
                          or version_pins.get("tool_versions_files")):
        rec["version_pins"] = version_pins
    if containerization and any(containerization.values()):
        rec["containerization"] = containerization
    if workspace and workspace.get("is_workspace"):
        rec["workspace"] = workspace
    if pre_commit and pre_commit.get("config_present"):
        rec["pre_commit"] = pre_commit
    return rec

def _render_md(rec: dict) -> str:
    """Render the JSON record as markdown — same shape the original
    .md artifact had, for human reading + back-compat with consumers
    that grep .md."""
    s = rec["stack"]
    lines = ["# Stack Context", ""]
    lines.append(f"Generated: {rec['generated']}")
    lines.append("")
    lines.append("## Stack")
    suffix = f" ({s['language_version']})" if s.get("language_version") else ""
    lines.append(f"- **Language**: {s['primary_language']}{suffix}")
    if s.get("frameworks"):
        lines.append(f"- **Framework**: {', '.join(s['frameworks'])}")
    if s.get("build_cmd"):
        lines.append(f"- **Build**: `{s['build_cmd']}`")
    if s.get("test_cmd"):
        lines.append(f"- **Test**: `{s['test_cmd']}`")
    if s.get("lint"):
        ci_gate = "yes" if rec.get("ci_systems") else "unknown"
        lines.append(f"- **Lint**: {', '.join(s['lint'])} [CI gate: {ci_gate}]")
    lines.append("")

    if rec.get("secondary_languages"):
        lines.append("## Secondary Languages")
        for sl in rec["secondary_languages"]:
            lines.append(f"- {sl['language']} ({sl['file_count']} files)")
        lines.append("")

    if rec.get("manifests"):
        lines.append("## Detected manifests")
        for m in rec["manifests"]:
            lines.append(f"- `{m['name']}` → {m['language']}")
        lines.append("")

    if rec.get("ci_systems"):
        lines.append("## CI Systems")
        for c in rec["ci_systems"]:
            lines.append(f"- {c}")
        lines.append("")

    if rec.get("convention_files"):
        lines.append("## Convention files present")
        for c in rec["convention_files"]:
            lines.append(f"- `{c}`")
        lines.append("")

    lines.append(("---\n"
                  "Mechanically generated by `kaizen-detect-stack scan`. "
                  "Schema-validated source: `stack-context.json`. "
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
    json_path = Path(args.out) if args.out else _output_path_json(root)
    md_path = json_path.with_suffix(".md")

    if not args.force and not _is_stale(json_path, max_days=args.max_days):
        if args.json:
            print(json.dumps({"skipped": True, "path": str(json_path),
                                "reason": "fresh"}))
        else:
            print(f"[detect-stack] skipped — {json_path} is fresh "
                  f"(< {args.max_days} days). Use --force to regenerate.")
        return 0

    lang_counts = _count_languages(root)
    manifests = _find_manifests(root)
    ci = _detect_ci(root)
    conventions = _convention_files_present(root)
    version_pins = _detect_version_pins(root)
    containerization = _detect_containerization(root)
    workspace = _detect_workspace(root, manifests)
    pre_commit = _detect_pre_commit(root)

    sniffed: dict = {}
    for name, _, path in manifests:
        if name in _SNIFFERS:
            sniffed.update(_SNIFFERS[name](_read_safe(path)))
            break

    record = _build_record(root, lang_counts, manifests, ci, conventions,
                            sniffed, version_pins=version_pins,
                            containerization=containerization,
                            workspace=workspace, pre_commit=pre_commit)

    # Self-validate against the shipped schema — fail loud if the
    # build_record output drifts from the contract. Best-effort:
    # silently passes when jsonschema isn't installed.
    err = _self_validate(record)
    if err:
        sys.stderr.write(f"[detect-stack] WARN: artifact failed schema validation: {err[:200]}\n")
    json_body = json.dumps(record, indent=2) + "\n"
    md_body = _render_md(record)

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json_body, encoding="utf-8")
    md_path.write_text(md_body, encoding="utf-8")

    if args.json:
        print(json.dumps({
            "json_path": str(json_path),
            "md_path":   str(md_path),
            "json_bytes": len(json_body),
            "primary":   record["stack"]["primary_language"],
            "manifests": [m["name"] for m in record["manifests"]],
            "ci":        record["ci_systems"],
        }))
    else:
        print(f"[detect-stack] wrote {json_path} ({len(json_body)}b JSON) "
              f"+ {md_path} ({len(md_body)}b md)")
    return 0

def cmd_show(args) -> int:
    """Print the JSON artifact by default; --md prints the markdown view."""
    p = _output_path_md() if args.md else _output_path_json()
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

    sh = sub.add_parser("show", help="print existing artifact (JSON by default; --md for markdown view)")
    sh.add_argument("--md", action="store_true",
                     help="print the markdown view instead of the JSON record")
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
