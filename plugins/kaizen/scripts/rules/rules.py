#!/usr/bin/env python3
"""kaizen rules — read brain-sourced behaviour rules from the kaizen Second Brain.

Scans `~/.claude/.kaizen/brain/Notes/*.md` for files with a `kaizen:` block in their
YAML frontmatter. Each becomes a runtime rule the gate consults.

Four rule_types:

  deletion-allow        path_glob: <fnmatch>      Allow `git rm` on matching paths
                                                  without KAIZEN_ALLOW_DELETE=1.
  check-severity        check_id: <name>          Override a gate check's severity.
                        severity: skip|warn|block
  custom-pattern        pattern_regex: <regex>    Run a regex over the staged diff;
                        pattern_action: warn|block  emit warning or block on hit.
                        pattern_message: <string>
  dependency-allowlist  allowlist: <csv>          Comma-separated crates / packages
                                                  pre-vetted for import. Consulted
                                                  by kaizen-vibe-check to demote
                                                  orphan-import warnings on the
                                                  listed names.

Frontmatter schema (per brain note):

    ---
    name: my-rule
    description: <one-line>
    type: behaviour
    tags: [kaizen, deletion]
    sources_count: 1
    freshness: stable
    created: 2026-05-11
    kaizen:
      rule_type: deletion-allow
      path_glob: "tests/fixtures/**"
    ---

Body of the .md note is human-readable rationale (agent-visible, plugin ignores).

Subcommands:
    list                       List all kaizen rules
    show <name>                Print one rule as JSON
    deletion-allowed <path>    Print yes/no
    severity <check_id>        Print the override severity or "default"
    custom-patterns            Print all custom-pattern rules as JSON
    dependency-allowed <crate> Print yes/no for the given crate/package name
    validate                   Schema-check all rules; exit 1 on any error
    template <rule_type>       Print a brain-note template to stdout

Env:
    KAIZEN_BRAIN_DIR          Override brain path (default ~/.claude/.kaizen/brain)
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — _paths + other helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "workflow" / "scripts"))
import _paths  # noqa: E402

BRAIN = _paths.BRAIN_DIR
NOTES_DIR = _paths.BRAIN_NOTES

VALID_RULE_TYPES = {"deletion-allow", "check-severity", "custom-pattern", "dependency-allowlist"}
VALID_SEVERITY = {"skip", "warn", "block"}
VALID_ACTION = {"warn", "block"}


# ─── Parser ───────────────────────────────────────────────────────────


def _extract_frontmatter(text: str) -> str | None:
    """Return the YAML frontmatter content (between --- markers), or None."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    return m.group(1) if m else None


def _flat_keys(fm: str) -> dict:
    """Read top-level scalar `key: value` pairs (one per line) from frontmatter."""
    out = {}
    for line in fm.split("\n"):
        m = re.match(r"^([a-z_]+):\s*(.+?)\s*$", line)
        if m:
            v = m.group(2).strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            elif v.startswith("'") and v.endswith("'"):
                v = v[1:-1]
            out[m.group(1)] = v
    return out


def _kaizen_block(fm: str) -> dict | None:
    """Extract the nested kaizen: block (two-space indent). Returns dict or None."""
    m = re.search(r"^kaizen:\s*\n((?:  [^\n]+\n?)+)", fm, re.MULTILINE)
    if not m:
        return None
    block = {}
    for line in m.group(1).split("\n"):
        kv = re.match(r"^  ([a-z_]+):\s*(.+?)\s*$", line)
        if kv:
            v = kv.group(2).strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            elif v.startswith("'") and v.endswith("'"):
                v = v[1:-1]
            block[kv.group(1)] = v
    return block


def load_rules() -> list[dict]:
    """Scan brain Notes/ for kaizen rules. Returns list of rule dicts."""
    rules = []
    if not NOTES_DIR.exists():
        return rules
    for f in sorted(NOTES_DIR.glob("*.md")):
        if f.name.endswith(".disabled"):
            continue
        try:
            text = f.read_text()
        except Exception:
            continue
        fm = _extract_frontmatter(text)
        if not fm:
            continue
        block = _kaizen_block(fm)
        if not block:
            continue
        flat = _flat_keys(fm)
        rule = {
            "name": flat.get("name", f.stem),
            "description": flat.get("description", ""),
            "source": str(f),
            **block,
        }
        rules.append(rule)
    return rules


# ─── Lookups ──────────────────────────────────────────────────────────


def deletion_allowed(path: str) -> tuple[bool, str | None]:
    """Return (allowed, rule_name)."""
    for r in load_rules():
        if r.get("rule_type") != "deletion-allow":
            continue
        glob_pat = r.get("path_glob", "")
        if glob_pat and fnmatch.fnmatch(path, glob_pat):
            return True, r["name"]
    return False, None


def get_severity(check_id: str) -> str | None:
    for r in load_rules():
        if r.get("rule_type") == "check-severity" and r.get("check_id") == check_id:
            sev = r.get("severity")
            if sev in VALID_SEVERITY:
                return sev
    return None


def custom_patterns() -> list[dict]:
    return [r for r in load_rules() if r.get("rule_type") == "custom-pattern"]


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def dependency_allowed(name: str) -> tuple[bool, str | None]:
    """Return (allowed, rule_name) — union over all dependency-allowlist rules."""
    for r in load_rules():
        if r.get("rule_type") != "dependency-allowlist":
            continue
        if name in _split_csv(r.get("allowlist", "")):
            return True, r["name"]
    return False, None


# ─── Validation ───────────────────────────────────────────────────────


def validate_rule(r: dict) -> list[str]:
    """Return list of error strings (empty = valid)."""
    errs = []
    rt = r.get("rule_type")
    if rt not in VALID_RULE_TYPES:
        errs.append(f"rule_type '{rt}' not in {VALID_RULE_TYPES}")
        return errs
    if rt == "deletion-allow":
        if not r.get("path_glob"):
            errs.append("deletion-allow missing path_glob")
    elif rt == "check-severity":
        if not r.get("check_id"):
            errs.append("check-severity missing check_id")
        if r.get("severity") not in VALID_SEVERITY:
            errs.append(f"check-severity severity must be one of {VALID_SEVERITY}")
    elif rt == "custom-pattern":
        if not r.get("pattern_regex"):
            errs.append("custom-pattern missing pattern_regex")
        if r.get("pattern_action") not in VALID_ACTION:
            errs.append(f"custom-pattern action must be one of {VALID_ACTION}")
        try:
            re.compile(r.get("pattern_regex", ""))
        except re.error as e:
            errs.append(f"custom-pattern regex invalid: {e}")
    elif rt == "dependency-allowlist":
        if not _split_csv(r.get("allowlist", "")):
            errs.append("dependency-allowlist requires non-empty allowlist (comma-separated)")
    return errs


# ─── Templates ────────────────────────────────────────────────────────


def template(rule_type: str) -> str:
    today = "2026-05-11"  # caller can replace
    templates = {
        "deletion-allow": f"""---
name: kaizen-allow-tests-fixtures
description: Allow deletion of files under tests/fixtures/ without KAIZEN_ALLOW_DELETE override.
type: behaviour
tags: [kaizen, deletion-allow]
sources_count: 1
freshness: stable
created: {today}
updated: {today}
kaizen:
  rule_type: deletion-allow
  path_glob: "tests/fixtures/**"
---

# Why

Test fixtures are intermediate, regenerable artifacts. Deletion shouldn't
require the same authorization as production code.
""",
        "check-severity": f"""---
name: kaizen-skip-paired-test
description: Skip the paired-test check (#7). My personal preference is to write tests after the implementation lands.
type: behaviour
tags: [kaizen, check-severity]
sources_count: 1
freshness: stable
created: {today}
updated: {today}
kaizen:
  rule_type: check-severity
  check_id: paired-test
  severity: skip
---

# Why

I prefer the test-after-impl workflow on solo projects. The paired-test
warn is noise.
""",
        "custom-pattern": f"""---
name: kaizen-block-todo-in-commits
description: Block commits that introduce a fresh TODO/FIXME/XXX (only on +lines).
type: behaviour
tags: [kaizen, custom-pattern]
sources_count: 1
freshness: stable
created: {today}
updated: {today}
kaizen:
  rule_type: custom-pattern
  pattern_regex: "^\\\\+.*(TODO|FIXME|XXX):"
  pattern_action: warn
  pattern_message: "Fresh TODO/FIXME/XXX introduced — file an issue or resolve before commit."
---

# Why

Unresolved markers in main are tech debt; force a moment of consideration
at commit time.
""",
        "dependency-allowlist": f"""---
name: kaizen-allow-core-deps
description: Pre-vetted dependencies. kaizen-vibe-check skips orphan-import warnings on these.
type: behaviour
tags: [kaizen, dependency-allowlist]
sources_count: 1
freshness: stable
created: {today}
updated: {today}
kaizen:
  rule_type: dependency-allowlist
  allowlist: "serde,tokio,reqwest,anyhow,thiserror,clap,tracing"
---

# Why

These crates are reviewed, version-pinned, and widely used across this
workspace. A new `use <crate>::*` import for any of them is expected —
shouldn't trigger the vibe-check orphan-import warning every time.

Append more comma-separated names as additional deps are vetted. Multiple
dependency-allowlist rules across notes are unioned at lookup time.
""",
    }
    return templates.get(rule_type, f"Unknown rule_type: {rule_type}\nExpected one of {VALID_RULE_TYPES}")


# ─── CLI ──────────────────────────────────────────────────────────────


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"

    if cmd == "list":
        rules = load_rules()
        if not rules:
            print(f"(no kaizen rules in {NOTES_DIR})")
            return
        for r in rules:
            errs = validate_rule(r)
            tag = "✗" if errs else "✓"
            print(f"  {tag} {r['name']:<40} {r.get('rule_type','?')}")
            if errs:
                for e in errs:
                    print(f"      → {e}")

    elif cmd == "show":
        if len(sys.argv) < 3:
            sys.exit("usage: show <name>")
        for r in load_rules():
            if r["name"] == sys.argv[2]:
                print(json.dumps(r, indent=2))
                return
        sys.exit(f"not found: {sys.argv[2]}")

    elif cmd == "deletion-allowed":
        if len(sys.argv) < 3:
            sys.exit("usage: deletion-allowed <path>")
        allowed, by = deletion_allowed(sys.argv[2])
        if allowed:
            print(f"yes ({by})")
        else:
            print("no")
        sys.exit(0 if allowed else 1)

    elif cmd == "severity":
        if len(sys.argv) < 3:
            sys.exit("usage: severity <check_id>")
        sev = get_severity(sys.argv[2])
        print(sev or "default")

    elif cmd == "custom-patterns":
        print(json.dumps(custom_patterns(), indent=2))

    elif cmd == "dependency-allowed":
        if len(sys.argv) < 3:
            sys.exit("usage: dependency-allowed <crate>")
        allowed, by = dependency_allowed(sys.argv[2])
        if allowed:
            print(f"yes ({by})")
        else:
            print("no")
        sys.exit(0 if allowed else 1)

    elif cmd == "validate":
        rules = load_rules()
        ok = True
        for r in rules:
            errs = validate_rule(r)
            if errs:
                ok = False
                print(f"  ✗ {r['name']}:")
                for e in errs:
                    print(f"      {e}")
        if ok:
            print(f"  ✓ all {len(rules)} rules valid")
        sys.exit(0 if ok else 1)

    elif cmd == "template":
        rt = sys.argv[2] if len(sys.argv) > 2 else "deletion-allow"
        print(template(rt))

    elif cmd in ("-h", "--help"):
        print(__doc__)

    else:
        sys.exit(f"unknown subcommand: {cmd}\ntry: list|show|deletion-allowed|severity|custom-patterns|dependency-allowed|validate|template")


if __name__ == "__main__":
    main()
