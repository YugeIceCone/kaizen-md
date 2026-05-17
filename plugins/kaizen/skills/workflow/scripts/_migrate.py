"""kaizen code-lift engine — port of shodan ``xtask/src/migrate/`` (X4).

Drives multi-step file lifts with import rewrites. The discipline:

  1. Source tree under ``<repo>/<source_root>/`` (e.g. ``port/``,
     ``vendor/``, or any other dir).
  2. Target tree under ``<repo>/<target_root>/`` (e.g. ``crates/``,
     ``packages/``, ``src/``).
  3. ``kaizen-migrations.toml`` at repo root maps source paths → target
     paths AND declares text rewrites that fire as files are copied.

Subcommands:

  - ``preview <file>`` — show lift plan for one file (target, rewrites,
    sibling deps, missing deps in target manifest).
  - ``lift <from> [--to <target>] [--apply]`` — copy + rewrite. Dry-run
    by default; ``--apply`` writes.
  - ``deps-gap <target>`` — list ``[required_deps]`` not yet declared in
    the target manifest (Cargo.toml / package.json / pyproject.toml /
    go.mod).
  - ``audit`` — workspace-wide table of source → target lift status.

## Reference

Ported from shodan ``xtask/src/migrate/{audit,preview,deps_gap,lift,
rewriter,config}.rs`` (~1100 LOC). The text rewriter is faithful to
the Rust impl (boundary-aware longest-match-first). The audit /
deps-gap surfaces are generalized to multi-language manifest reads.

## Manifest detection (deps-gap)

Per target, kaizen probes (in order):

  1. ``<target>/Cargo.toml``      → Rust
  2. ``<target>/package.json``    → Node
  3. ``<target>/pyproject.toml``  → Python
  4. ``<target>/go.mod``          → Go

The first match wins. Required-dep detection is text-shaped (regex
over the manifest body) rather than full TOML/JSON parsing, mirroring
the Rust impl's regex approach.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))


# ─── TOML loader (stdlib in 3.11+; tomli fallback) ───────────────────


def _load_toml(path: Path) -> dict:
    """Load a TOML file. Prefers stdlib ``tomllib`` (3.11+) with a
    ``tomli`` fallback for older runtimes. Empty file → empty dict."""
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        import tomllib  # type: ignore  # py311+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            raise RuntimeError(
                "kaizen-migrate: tomllib (3.11+) or tomli required.\n"
                "  pip install --user tomli"
            )
    return tomllib.loads(text)


# ─── Config ───────────────────────────────────────────────────────────


DEFAULT_CONFIG_NAME = "kaizen-migrations.toml"


@dataclasses.dataclass
class SiblingCluster:
    file: str
    must_lift_with: list[str]
    note: str = ""


class Config:
    """Parsed ``kaizen-migrations.toml``.

    Schema (all sections optional; missing sections → empty dict):

        [targets]          source → target path mappings
                           "rust-crate" = "rust-crate-renamed"   # rename
                           "old-loc" = "_skip"                    # skip
        [paths]            text rewrites (longest-match-first)
                           "old_module" = "new_module"
        [[siblings]]       file groups that must travel together
                           file = "src/foo.rs"
                           must_lift_with = ["src/bar.rs"]
                           note = "shared types"
        [required_deps]    per-target manifest deps
                           "rust-crate" = ["serde", "tokio"]
    """

    def __init__(
        self,
        *,
        targets: Optional[dict] = None,
        paths: Optional[dict] = None,
        siblings: Optional[list] = None,
        required_deps: Optional[dict] = None,
        source_root: str = "port",
        target_root: str = "crates",
    ):
        self.targets: dict[str, str] = dict(targets or {})
        self.paths: dict[str, str] = dict(paths or {})
        self.siblings: list[SiblingCluster] = list(siblings or [])
        self.required_deps: dict[str, list[str]] = dict(required_deps or {})
        self.source_root = source_root
        self.target_root = target_root

    @classmethod
    def from_dict(cls, raw: dict) -> "Config":
        siblings = []
        for s in raw.get("siblings", []) or []:
            if not isinstance(s, dict):
                continue
            file = str(s.get("file", "")).strip()
            if not file:
                continue
            siblings.append(SiblingCluster(
                file=file,
                must_lift_with=[
                    str(x) for x in s.get("must_lift_with", []) if x
                ],
                note=str(s.get("note", "")),
            ))
        meta = raw.get("meta", {}) or {}
        return cls(
            targets=raw.get("targets") or raw.get("crate_targets") or {},
            paths=raw.get("paths") or {},
            siblings=siblings,
            required_deps=raw.get("required_deps") or {},
            source_root=str(meta.get("source_root", "port")),
            target_root=str(meta.get("target_root", "crates")),
        )

    @classmethod
    def from_file(cls, path: Path) -> "Config":
        if not path.is_file():
            raise FileNotFoundError(
                f"{path} not found — create it to drive kaizen-migrate "
                f"(see docs for schema)."
            )
        return cls.from_dict(_load_toml(path))

    def target_for(self, source_path: str) -> Optional[str]:
        """Resolve a source path (relative to source_root) to its target.
        Returns the literal string ``"_skip"`` for explicit skips."""
        return self.targets.get(source_path)

    def paths_longest_first(self) -> list[tuple[str, str]]:
        """Return ``[paths]`` rewrites sorted longest-key-first so a more
        specific rewrite wins over a shorter prefix. Mirrors the Rust
        impl's ``Reverse(b.0.len())`` ordering."""
        return sorted(
            self.paths.items(), key=lambda kv: len(kv[0]), reverse=True,
        )

    def siblings_for(self, source_file: str) -> Optional[SiblingCluster]:
        """Find the sibling cluster declaring ``source_file`` as its
        primary file. Returns None when none matches."""
        for s in self.siblings:
            if s.file == source_file:
                return s
        return None

    def required_deps_for(self, target: str) -> list[str]:
        return list(self.required_deps.get(target, []))


# ─── Rewriter ─────────────────────────────────────────────────────────


_BOUNDARY_BYTES = frozenset(b":;, \t\n})./")


@dataclasses.dataclass
class RewriteEvent:
    from_: str
    to: str
    occurrences: int


def rewrite(src: str, cfg: Config) -> tuple[str, list[RewriteEvent]]:
    """Apply ``[paths]`` text rewrites to ``src``.

    Faithful port of the Rust ``rewriter::rewrite`` — boundary-aware
    so partial-identifier matches don't fire. A token like
    ``shodan_core_extension`` is NOT rewritten by a ``shodan_core`` rule
    because the next byte ``_`` isn't in the boundary set.

    Returns ``(rewritten_text, events)`` — one event per matching rule
    that fired, with occurrence count."""
    current = src
    events: list[RewriteEvent] = []
    for from_, to in cfg.paths_longest_first():
        count = 0
        search_from = 0
        new_parts: list[str] = []
        cur_bytes = current.encode("utf-8")
        from_bytes = from_.encode("utf-8")
        flen = len(from_bytes)
        while True:
            idx = cur_bytes.find(from_bytes, search_from)
            if idx < 0:
                new_parts.append(cur_bytes[search_from:].decode("utf-8", errors="replace"))
                break
            end = idx + flen
            next_byte = cur_bytes[end:end + 1]
            is_boundary = (
                next_byte == b""
                or next_byte[0] in _BOUNDARY_BYTES
            )
            if not is_boundary:
                new_parts.append(cur_bytes[search_from:end].decode("utf-8", errors="replace"))
                search_from = end
                continue
            new_parts.append(cur_bytes[search_from:idx].decode("utf-8", errors="replace"))
            new_parts.append(to)
            search_from = end
            count += 1
        if count > 0:
            events.append(RewriteEvent(from_=from_, to=to, occurrences=count))
            current = "".join(new_parts)
    return current, events


# ─── Manifest detection (multi-language deps-gap) ────────────────────


@dataclasses.dataclass
class ManifestInfo:
    path: Path
    kind: str  # 'cargo' | 'npm' | 'pyproject' | 'go-mod'
    body: str


def detect_manifest(target_dir: Path) -> Optional[ManifestInfo]:
    """Probe a target directory for its manifest file. First match wins,
    in priority order: Cargo.toml > package.json > pyproject.toml >
    go.mod. Returns None when no manifest is detected."""
    candidates = [
        ("Cargo.toml", "cargo"),
        ("package.json", "npm"),
        ("pyproject.toml", "pyproject"),
        ("go.mod", "go-mod"),
    ]
    for name, kind in candidates:
        p = target_dir / name
        if p.is_file():
            try:
                body = p.read_text(encoding="utf-8")
            except OSError:
                continue
            return ManifestInfo(path=p, kind=kind, body=body)
    return None


def manifest_has_dep(manifest: ManifestInfo, dep: str) -> bool:
    """Heuristic substring/regex match for a dep in a manifest body.

    Cargo:    ``serde = "1"`` / ``serde.workspace = true`` / ``serde = { ... }``
    Npm:      ``"serde": "..."`` under ``dependencies`` / ``devDependencies``
    Pyproject:``serde = "*"`` (TOML) / ``"serde >=..."`` (PEP 631 list)
    Go-mod:   ``require github.com/.../serde v...`` / ``serde v...``

    Returns True on any plausible occurrence. False positives are
    acceptable — the gap check is advisory, not authoritative. False
    negatives (missing a dep that's actually there) would be a bug."""
    if not dep:
        return False
    escaped = re.escape(dep)
    if manifest.kind == "cargo":
        # serde = / serde. (workspace path) / [dependencies.serde]
        pat = rf"(?m)^\s*{escaped}\s*[=.]|\[dependencies\.{escaped}\]"
        return re.search(pat, manifest.body) is not None
    if manifest.kind == "npm":
        try:
            data = json.loads(manifest.body)
        except json.JSONDecodeError:
            return False
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            if isinstance(data.get(section), dict) and dep in data[section]:
                return True
        return False
    if manifest.kind == "pyproject":
        # Either [project.dependencies] list or [tool.poetry.dependencies]
        # table — substring check is fine for advisory.
        if re.search(rf'(?m)["\']?{escaped}["\']?\s*[=>~<!^]', manifest.body):
            return True
        if re.search(rf"(?m)^\s*{escaped}\s*=", manifest.body):
            return True
        return False
    if manifest.kind == "go-mod":
        return re.search(rf"\b{escaped}\b\s+v", manifest.body) is not None
    return False


# ─── Lift ─────────────────────────────────────────────────────────────


def collect_lift_pairs(
    src: Path,
    source_root: Path,
    target_dir: Path,
    *,
    extensions: Optional[set[str]] = None,
) -> list[tuple[Path, Path]]:
    """Build (src_file → dst_file) pairs for a lift.

    File input: one pair preserving the path under the source crate
    Dir input: walk and collect every file with an allowed extension
    (default: ``{.rs, .py, .ts, .js, .tsx, .jsx, .go, .java, .kt, .rb}``).

    Mirrors ``xtask/src/migrate/lift.rs::collect_pairs`` but uses
    ``pathlib`` walking instead of ``walkdir``."""
    if extensions is None:
        extensions = {
            ".rs", ".py", ".ts", ".tsx", ".js", ".jsx", ".go",
            ".java", ".kt", ".rb", ".swift", ".cs", ".cpp", ".c",
        }
    pairs: list[tuple[Path, Path]] = []
    if src.is_file():
        dst = _compute_dest(src, source_root, target_dir)
        pairs.append((src, dst))
        return pairs
    if src.is_dir():
        for p in src.rglob("*"):
            if not p.is_file():
                continue
            if "target" in p.parts:  # skip Rust build dir
                continue
            if "node_modules" in p.parts:
                continue
            if p.suffix.lower() not in extensions:
                continue
            dst = _compute_dest(p, source_root, target_dir)
            pairs.append((p, dst))
    return pairs


def _compute_dest(
    src_file: Path, source_root: Path, target_dir: Path
) -> Path:
    """Map ``<source_root>/<inner>/file.rs`` → ``<target_dir>/<inner>/file.rs``.

    The "inner" is the path under the source root WITHOUT the first
    path segment (which is the project name in port/<project>/<inner>
    layouts). Falls back to the rel path verbatim when the structure
    is flatter."""
    try:
        rel = src_file.relative_to(source_root)
    except ValueError:
        return target_dir / src_file.name
    # Drop the first segment (project-name dir) if there is one
    parts = rel.parts
    if len(parts) > 1:
        return target_dir / Path(*parts[1:])
    return target_dir / rel


@dataclasses.dataclass
class LiftResult:
    pairs: list[tuple[Path, Path]]
    rewrites_per_file: dict[str, list[RewriteEvent]]
    total_rewrites: int
    applied: bool


def do_lift(
    src: Path,
    target_dir: Path,
    cfg: Config,
    source_root: Path,
    *,
    apply: bool = False,
) -> LiftResult:
    """Copy + rewrite a file or directory tree.

    When ``apply=False`` (default), reports the plan without writing.
    When ``apply=True``, creates parent dirs and writes destinations
    with rewrites applied.

    Returns a ``LiftResult`` carrying the pairs visited, per-file
    rewrite events, and total occurrence count."""
    pairs = collect_lift_pairs(src, source_root, target_dir)
    per_file: dict[str, list[RewriteEvent]] = {}
    total = 0
    for src_file, dst_file in pairs:
        try:
            original = src_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            per_file[str(src_file)] = []
            continue
        rewritten, events = rewrite(original, cfg)
        per_file[str(src_file)] = events
        total += sum(e.occurrences for e in events)
        if apply:
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            dst_file.write_text(rewritten, encoding="utf-8")
    return LiftResult(
        pairs=pairs,
        rewrites_per_file=per_file,
        total_rewrites=total,
        applied=apply,
    )


# ─── Preview ──────────────────────────────────────────────────────────


@dataclasses.dataclass
class PreviewResult:
    source_path: Path
    target_path: Path
    target_exists: bool
    rewrite_events: list[RewriteEvent]
    sibling_files: list[tuple[str, bool]]  # (path, exists)
    sibling_note: str
    missing_deps: list[str]
    status: str  # 'ok' | 'skipped' | 'no-mapping'


def do_preview(
    source_path: Path,
    repo_root: Path,
    cfg: Config,
) -> PreviewResult:
    """Compute the lift plan for one source file without writing."""
    source_root = repo_root / cfg.source_root
    rel = source_path.relative_to(source_root)
    project_dir = source_root / rel.parts[0]
    project_rel = rel.parts[0]

    target_name = cfg.target_for(project_rel)
    if target_name is None:
        return PreviewResult(
            source_path=source_path,
            target_path=Path(),
            target_exists=False,
            rewrite_events=[],
            sibling_files=[],
            sibling_note="",
            missing_deps=[],
            status="no-mapping",
        )
    if target_name == "_skip":
        return PreviewResult(
            source_path=source_path,
            target_path=Path(),
            target_exists=False,
            rewrite_events=[],
            sibling_files=[],
            sibling_note="",
            missing_deps=[],
            status="skipped",
        )

    src_under_project = source_path.relative_to(project_dir)
    target_path = repo_root / cfg.target_root / target_name / src_under_project

    text = source_path.read_text(encoding="utf-8")
    _new, events = rewrite(text, cfg)

    sibling_files: list[tuple[str, bool]] = []
    sibling_note = ""
    canonical = f"{cfg.source_root}/{rel}"
    cluster = cfg.siblings_for(canonical)
    if cluster is not None:
        sibling_note = cluster.note
        for s in cluster.must_lift_with:
            s_path = repo_root / s.lstrip("/")
            sibling_files.append((s, s_path.is_file()))

    target_dir = repo_root / cfg.target_root / target_name
    missing_deps: list[str] = []
    manifest = detect_manifest(target_dir)
    if manifest is not None:
        for dep in cfg.required_deps_for(target_name):
            if not manifest_has_dep(manifest, dep):
                missing_deps.append(dep)

    return PreviewResult(
        source_path=source_path,
        target_path=target_path,
        target_exists=target_path.is_file(),
        rewrite_events=events,
        sibling_files=sibling_files,
        sibling_note=sibling_note,
        missing_deps=missing_deps,
        status="ok",
    )


# ─── Deps-gap ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class DepsGapResult:
    target: str
    manifest_path: Optional[Path]
    manifest_kind: Optional[str]
    required: list[str]
    missing: list[str]


def do_deps_gap(target: str, repo_root: Path, cfg: Config) -> DepsGapResult:
    """Check ``[required_deps].<target>`` against the target's manifest.

    Returns a list of declared-but-missing deps. Empty ``missing`` →
    all required deps are present (or the dep set is empty)."""
    target_dir = repo_root / cfg.target_root / target
    required = cfg.required_deps_for(target)
    manifest = detect_manifest(target_dir)
    if manifest is None:
        return DepsGapResult(
            target=target,
            manifest_path=None,
            manifest_kind=None,
            required=required,
            missing=list(required),
        )
    missing = [d for d in required if not manifest_has_dep(manifest, d)]
    return DepsGapResult(
        target=target,
        manifest_path=manifest.path,
        manifest_kind=manifest.kind,
        required=required,
        missing=missing,
    )


# ─── Audit ────────────────────────────────────────────────────────────


@dataclasses.dataclass
class AuditRow:
    source_project: str
    target: str
    status: str  # 'lifted' | 'pending' | 'skipped' | 'missing-target'
    source_files: int
    target_files: int


def do_audit(repo_root: Path, cfg: Config) -> list[AuditRow]:
    """Workspace-wide lift status table. One row per source project
    declared in ``[targets]``."""
    rows: list[AuditRow] = []
    source_root = repo_root / cfg.source_root
    for src_project, target in sorted(cfg.targets.items()):
        src_dir = source_root / src_project
        src_files = _count_source_files(src_dir) if src_dir.is_dir() else 0
        if target == "_skip":
            rows.append(AuditRow(
                source_project=src_project, target=target,
                status="skipped", source_files=src_files,
                target_files=0,
            ))
            continue
        target_dir = repo_root / cfg.target_root / target
        if not target_dir.is_dir():
            rows.append(AuditRow(
                source_project=src_project, target=target,
                status="missing-target", source_files=src_files,
                target_files=0,
            ))
            continue
        target_files = _count_source_files(target_dir)
        status = "lifted" if target_files > 0 else "pending"
        rows.append(AuditRow(
            source_project=src_project, target=target,
            status=status, source_files=src_files,
            target_files=target_files,
        ))
    return rows


def _count_source_files(d: Path) -> int:
    count = 0
    for p in d.rglob("*"):
        if not p.is_file():
            continue
        if "target" in p.parts or "node_modules" in p.parts:
            continue
        if p.suffix.lower() in {
            ".rs", ".py", ".ts", ".tsx", ".js", ".jsx", ".go",
            ".java", ".kt", ".rb", ".swift", ".cs",
        }:
            count += 1
    return count


# ─── CLI ──────────────────────────────────────────────────────────────


def _resolve_repo_root(explicit: Optional[str]) -> Path:
    """Pick a repo root. Explicit flag > CWD > git-toplevel walk."""
    if explicit:
        return Path(explicit).resolve()
    cwd = Path.cwd()
    cur = cwd
    while cur != cur.parent:
        if (cur / ".git").exists() or (cur / "kaizen-migrations.toml").is_file():
            return cur
        cur = cur.parent
    return cwd


def _resolve_config_path(repo_root: Path, explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).resolve()
    return repo_root / DEFAULT_CONFIG_NAME


def _cmd_path(args) -> int:
    repo_root = _resolve_repo_root(args.root)
    cfg_path = _resolve_config_path(repo_root, args.config)
    out = {
        "repo_root": str(repo_root),
        "config_path": str(cfg_path),
        "config_exists": cfg_path.is_file(),
    }
    print(json.dumps(out, indent=2))
    return 0


def _cmd_audit(args) -> int:
    repo_root = _resolve_repo_root(args.root)
    cfg = Config.from_file(_resolve_config_path(repo_root, args.config))
    rows = do_audit(repo_root, cfg)
    if args.json:
        print(json.dumps([dataclasses.asdict(r) for r in rows], indent=2))
        return 0
    print(f"[kaizen-migrate audit] {len(rows)} target(s)")
    print()
    print(f"  {'SOURCE':<28} {'TARGET':<24} {'STATUS':<16} SRC TGT")
    print(f"  {'-' * 28} {'-' * 24} {'-' * 16} --- ---")
    for r in rows:
        print(f"  {r.source_project:<28} {r.target:<24} "
              f"{r.status:<16} {r.source_files:>3} {r.target_files:>3}")
    return 0


def _cmd_preview(args) -> int:
    repo_root = _resolve_repo_root(args.root)
    cfg = Config.from_file(_resolve_config_path(repo_root, args.config))
    src = Path(args.file).resolve()
    result = do_preview(src, repo_root, cfg)
    if args.json:
        d = dataclasses.asdict(result)
        # Path objects aren't JSON-serializable
        d["source_path"] = str(result.source_path)
        d["target_path"] = str(result.target_path)
        d["rewrite_events"] = [dataclasses.asdict(e) for e in result.rewrite_events]
        print(json.dumps(d, indent=2))
        return 0
    print(f"[kaizen-migrate preview] {src.relative_to(repo_root)}")
    print()
    if result.status == "skipped":
        print("  status: SKIPPED — [targets] marks the project _skip")
        return 0
    if result.status == "no-mapping":
        print("  status: NO MAPPING — add an entry in [targets]")
        return 1
    rel_tgt = result.target_path.relative_to(repo_root) if result.target_path != Path() else result.target_path
    print(f"  target: {rel_tgt}")
    if result.target_exists:
        print("          (already exists — lift would overwrite)")
    else:
        print("          (does not exist — lift would create)")
    print()
    if result.rewrite_events:
        print(f"  rewrites ({len(result.rewrite_events)}):")
        for ev in result.rewrite_events:
            print(f"    {ev.occurrences:>3}x  {ev.from_}  ->  {ev.to}")
    else:
        print("  rewrites: none")
    print()
    if result.sibling_files:
        print("  siblings (must lift together):")
        for s, exists in result.sibling_files:
            mark = "." if exists else "x"
            print(f"    {mark} {s}")
        if result.sibling_note:
            print(f"    note: {result.sibling_note}")
    if result.missing_deps:
        print()
        print("  missing target manifest deps:")
        for d in result.missing_deps:
            print(f"    - {d}")
    return 0


def _cmd_deps_gap(args) -> int:
    repo_root = _resolve_repo_root(args.root)
    cfg = Config.from_file(_resolve_config_path(repo_root, args.config))
    result = do_deps_gap(args.target, repo_root, cfg)
    if args.json:
        d = dataclasses.asdict(result)
        d["manifest_path"] = str(result.manifest_path) if result.manifest_path else None
        print(json.dumps(d, indent=2))
        return 0
    if result.manifest_path is None:
        print(f"[kaizen-migrate deps-gap] {result.target}: no manifest found")
        return 1
    print(
        f"[kaizen-migrate deps-gap] target={result.target} "
        f"manifest={result.manifest_path.relative_to(repo_root)} "
        f"kind={result.manifest_kind} "
        f"required={len(result.required)}"
    )
    if not result.required:
        print("  no [required_deps] declared — nothing to check.")
        return 0
    if not result.missing:
        print(f"  . all {len(result.required)} required dep(s) present")
        return 0
    print("  x missing:")
    for m in result.missing:
        print(f"    - {m}")
    return 2


def _cmd_lift(args) -> int:
    repo_root = _resolve_repo_root(args.root)
    cfg = Config.from_file(_resolve_config_path(repo_root, args.config))
    src = Path(args.from_).resolve()
    if not src.exists():
        print(f"source not found: {src}", file=sys.stderr)
        return 1
    if args.to:
        target_dir = repo_root / cfg.target_root / args.to
    else:
        # Derive from src path under source_root
        source_root = repo_root / cfg.source_root
        try:
            rel = src.relative_to(source_root)
            project = rel.parts[0]
        except ValueError:
            print(f"--to required when source isn't under {cfg.source_root}/",
                  file=sys.stderr)
            return 1
        target_name = cfg.target_for(project)
        if target_name is None:
            print(f"no [targets] entry for {project!r}", file=sys.stderr)
            return 1
        if target_name == "_skip":
            print(f"{project} marked _skip — refusing to lift", file=sys.stderr)
            return 1
        target_dir = repo_root / cfg.target_root / target_name
    if not target_dir.exists():
        if args.apply:
            target_dir.mkdir(parents=True, exist_ok=True)
        else:
            print(f"target dir does not exist: {target_dir} "
                  "(use --apply to create)", file=sys.stderr)
    source_root = repo_root / cfg.source_root
    result = do_lift(src, target_dir, cfg, source_root, apply=args.apply)
    if args.json:
        d = {
            "applied": result.applied,
            "total_rewrites": result.total_rewrites,
            "pairs": [(str(s), str(t)) for s, t in result.pairs],
        }
        print(json.dumps(d, indent=2))
        return 0
    mode = "(--apply)" if args.apply else "(dry-run; pass --apply to write)"
    print(f"[kaizen-migrate lift] {src.relative_to(repo_root) if src.is_relative_to(repo_root) else src} "
          f"-> {target_dir.relative_to(repo_root) if target_dir.is_relative_to(repo_root) else target_dir}  {mode}")
    print()
    for s, t in result.pairs:
        events = result.rewrites_per_file.get(str(s), [])
        occ = sum(e.occurrences for e in events)
        action = "would write" if not args.apply else "wrote"
        rel_s = s.relative_to(repo_root) if s.is_relative_to(repo_root) else s
        rel_t = t.relative_to(repo_root) if t.is_relative_to(repo_root) else t
        print(f"  {action}: {rel_s} -> {rel_t}  ({occ} rewrite(s))")
        for ev in events:
            print(f"    {ev.occurrences:>3}x  {ev.from_}  ->  {ev.to}")
    print()
    print(f"{len(result.pairs)} file(s), {result.total_rewrites} rewrite(s) total")
    if not args.apply:
        print("dry-run — re-run with --apply to write.")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-migrate",
        description="Code-lift engine with import rewrites (X4).",
    )
    p.add_argument("--root", help="repo root (default: walk up from CWD)")
    p.add_argument("--config", help=f"config path (default: <root>/{DEFAULT_CONFIG_NAME})")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("path", help="print resolved paths")
    sp.set_defaults(func=_cmd_path)

    sa = sub.add_parser("audit", help="workspace-wide lift status table")
    sa.add_argument("--json", action="store_true")
    sa.set_defaults(func=_cmd_audit)

    spv = sub.add_parser("preview", help="show lift plan for one file")
    spv.add_argument("file", help="source file to preview")
    spv.add_argument("--json", action="store_true")
    spv.set_defaults(func=_cmd_preview)

    sd = sub.add_parser("deps-gap", help="missing target-manifest deps")
    sd.add_argument("target", help="target name (e.g. crate name)")
    sd.add_argument("--json", action="store_true")
    sd.set_defaults(func=_cmd_deps_gap)

    sl = sub.add_parser("lift", help="copy + rewrite source(s)")
    sl.add_argument("from_", metavar="from", help="source file or dir")
    sl.add_argument("--to", help="explicit target name (overrides [targets])")
    sl.add_argument("--apply", action="store_true", help="actually write")
    sl.add_argument("--json", action="store_true")
    sl.set_defaults(func=_cmd_lift)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
