"""Structural-drift detector — roadmap X2.

Port of shodan's xtask/src/drift/mod.rs (270 LOC Rust → ~250 LOC Python).
Same comparison model: diff JSON profiles in a baseline-dir against
JSON profiles in a current-dir; report added/removed/renamed public
items, dep deltas, LOC swings, test-count swings.

## Profile shape (JSON per unit, e.g. per Rust crate / Python package)

    {
      "name": "<unit>",
      "total_loc": 1234,
      "total_tests": 56,
      "files": [
        { "path": "src/foo.rs",
          "items": [{"kind": "fn", "name": "bar"}, ...] }
      ],
      "deps": ["dep_a", "dep_b"]
    }

Produced by `/kaizen:docs --json` (any language; the indexer writes the
above shape). The current-dir default is `<repo>/docs/crates/` (kept
the Rust name for compatibility; consumers can override).

## Paths

  baseline-dir: `<repo>/.kaizen/workflow/drift-baseline/` (default)
  current-dir:  `<repo>/docs/crates/` (default)
  Both overridable via constructor / CLI flags.

## CLI workflow

    kaizen-docs --json                    # emit current profiles
    kaizen-drift record                   # seed baseline (one-off)
    # ... refactor work ...
    kaizen-docs --json                    # re-emit
    kaizen-drift check                    # report deltas
    kaizen-drift check --fail-on-drift    # CI gate (exit 1 on drift)
    kaizen-drift explain <crate>          # detail one unit's drift
"""
from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path


# ─── Path resolution ──────────────────────────────────────────────────


def default_baseline_dir(root: Path | None = None) -> Path:
    root = root or Path.cwd()
    return root / ".kaizen" / "workflow" / "drift-baseline"


def default_current_dir(root: Path | None = None) -> Path:
    root = root or Path.cwd()
    return root / "docs" / "crates"


# ─── Models ──────────────────────────────────────────────────────────


@dataclasses.dataclass
class UnitDrift:
    """Drift in one unit (crate / package / module)."""
    unit: str
    items_added: list[str] = dataclasses.field(default_factory=list)
    items_removed: list[str] = dataclasses.field(default_factory=list)
    deps_added: list[str] = dataclasses.field(default_factory=list)
    deps_removed: list[str] = dataclasses.field(default_factory=list)
    loc_delta: int = 0
    tests_delta: int = 0

    def is_empty(self) -> bool:
        return (
            not self.items_added
            and not self.items_removed
            and not self.deps_added
            and not self.deps_removed
            and self.loc_delta == 0
            and self.tests_delta == 0
        )


@dataclasses.dataclass
class DriftReport:
    """Whole-repo drift report. Has per-unit details + summary counts."""
    baseline_dir: str
    current_dir: str
    changed: list[UnitDrift] = dataclasses.field(default_factory=list)
    added_units: list[str] = dataclasses.field(default_factory=list)
    removed_units: list[str] = dataclasses.field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.changed) + len(self.added_units) + len(self.removed_units)

    @property
    def is_empty(self) -> bool:
        return self.total == 0


# ─── Loaders ──────────────────────────────────────────────────────────


def load_profiles(profile_dir: Path) -> dict[str, dict]:
    """Read every `*.json` in `profile_dir`. Returns dict keyed by file
    stem. Missing dir → empty dict (caller decides whether to fail)."""
    out: dict[str, dict] = {}
    if not profile_dir.is_dir():
        return out
    for p in sorted(profile_dir.glob("*.json")):
        try:
            out[p.stem] = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
    return out


def collect_items(profile: dict) -> set[str]:
    """Pull every `{kind, name}` item pair from all files in the profile.

    Items are represented as `"<kind> <name>"` strings to make set-diff
    output human-readable."""
    out: set[str] = set()
    for f in profile.get("files") or []:
        if not isinstance(f, dict):
            continue
        for it in f.get("items") or []:
            if not isinstance(it, dict):
                continue
            kind = (it.get("kind") or "").strip()
            name = (it.get("name") or "").strip()
            if name:
                out.add(f"{kind} {name}" if kind else name)
    return out


def collect_deps(profile: dict) -> set[str]:
    """Pull dep names. Accepts list-of-strings OR list-of-dicts (with `name`)."""
    raw = profile.get("deps") or []
    out: set[str] = set()
    for d in raw:
        if isinstance(d, str):
            out.add(d)
        elif isinstance(d, dict) and isinstance(d.get("name"), str):
            out.add(d["name"])
    return out


def _j_int(profile: dict, key: str) -> int:
    v = profile.get(key)
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


# ─── Comparison ──────────────────────────────────────────────────────


def compare_units(unit: str, baseline: dict, current: dict) -> UnitDrift:
    """Diff two profiles for the same unit."""
    b_items = collect_items(baseline)
    c_items = collect_items(current)
    b_deps = collect_deps(baseline)
    c_deps = collect_deps(current)
    return UnitDrift(
        unit=unit,
        items_added=sorted(c_items - b_items),
        items_removed=sorted(b_items - c_items),
        deps_added=sorted(c_deps - b_deps),
        deps_removed=sorted(b_deps - c_deps),
        loc_delta=_j_int(current, "total_loc") - _j_int(baseline, "total_loc"),
        tests_delta=_j_int(current, "total_tests") - _j_int(baseline, "total_tests"),
    )


def run_check(
    baseline_dir: Path,
    current_dir: Path,
    only: str | None = None,
) -> DriftReport:
    """Compare all profiles in baseline vs current. `only` filters to
    one unit by stem (e.g. 'core', 'shodan-cli')."""
    baseline = load_profiles(baseline_dir)
    current = load_profiles(current_dir)
    report = DriftReport(
        baseline_dir=str(baseline_dir),
        current_dir=str(current_dir),
    )
    all_keys = set(baseline) | set(current)
    for key in sorted(all_keys):
        if only and key != only:
            continue
        b = baseline.get(key)
        c = current.get(key)
        if b is not None and c is not None:
            ud = compare_units(key, b, c)
            if not ud.is_empty():
                report.changed.append(ud)
        elif c is not None:
            report.added_units.append(key)
        elif b is not None:
            report.removed_units.append(key)
    return report


# ─── Record (seed baseline) ──────────────────────────────────────────


def record_baseline(
    current_dir: Path,
    baseline_dir: Path,
) -> dict:
    """Copy every `*.json` from current_dir into baseline_dir. Creates
    baseline_dir if absent. Returns {copied, baseline_dir, source_dir}."""
    if not current_dir.is_dir():
        raise FileNotFoundError(
            f"current profiles dir does not exist: {current_dir}"
        )
    baseline_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for p in current_dir.glob("*.json"):
        shutil.copy2(p, baseline_dir / p.name)
        copied += 1
    return {
        "copied": copied,
        "baseline_dir": str(baseline_dir),
        "source_dir": str(current_dir),
    }


# ─── Rendering ────────────────────────────────────────────────────────


def format_report(report: DriftReport, *, json_mode: bool = False) -> str:
    if json_mode:
        return json.dumps({
            "baseline_dir": report.baseline_dir,
            "current_dir": report.current_dir,
            "changed": [dataclasses.asdict(u) for u in report.changed],
            "added_units": report.added_units,
            "removed_units": report.removed_units,
            "total": report.total,
        }, indent=2)
    lines: list[str] = []
    lines.append(f"baseline: {report.baseline_dir}")
    lines.append(f"current:  {report.current_dir}")
    lines.append("")
    for u in report.added_units:
        lines.append(f"  ＋ NEW unit: {u}")
    for u in report.removed_units:
        lines.append(f"  － REMOVED unit: {u}")
    for ud in report.changed:
        lines.append(f"  ~ {ud.unit}")
        for it in ud.items_added[:10]:
            lines.append(f"      + {it}")
        if len(ud.items_added) > 10:
            lines.append(f"      … and {len(ud.items_added) - 10} more added")
        for it in ud.items_removed[:10]:
            lines.append(f"      - {it}")
        if len(ud.items_removed) > 10:
            lines.append(f"      … and {len(ud.items_removed) - 10} more removed")
        for d in ud.deps_added:
            lines.append(f"      + dep {d}")
        for d in ud.deps_removed:
            lines.append(f"      - dep {d}")
        if ud.loc_delta:
            sign = "+" if ud.loc_delta > 0 else ""
            lines.append(f"      LOC {sign}{ud.loc_delta}")
        if ud.tests_delta:
            sign = "+" if ud.tests_delta > 0 else ""
            lines.append(f"      tests {sign}{ud.tests_delta}")
    lines.append("")
    lines.append(
        f"summary: {len(report.changed)} changed · "
        f"{len(report.added_units)} added · "
        f"{len(report.removed_units)} removed"
    )
    return "\n".join(lines)
