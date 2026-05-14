#!/usr/bin/env python3
"""iron-laws — codegen for the human-readable reference.

Reads skills/iron-laws/domain/iron-laws.yaml (via _loader) and regenerates
skills/iron-laws/references/iron-laws.md so the yaml stays the single
source of truth and the markdown is a read-only copy.

## CLI

    python3 codegen.py           # regenerate references/iron-laws.md
    python3 codegen.py --check   # exit non-zero if the file is stale (CI drift gate)

## Idempotency

Running twice in a row produces byte-identical output (enforced by
tests/test_iron_laws.py::TestCodegen).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _loader import load_laws  # noqa: E402

_APP_DIR = Path(__file__).resolve().parent
REF_PATH = _APP_DIR.parent / "references" / "iron-laws.md"

GENERATED_HEADER = """<!-- DO NOT HAND-EDIT.

Generated from skills/iron-laws/domain/iron-laws.yaml by
skills/iron-laws/application/codegen.py.

To change content, edit the yaml and run `kaizen-iron-laws render`
(or this file directly). CI runs `codegen.py --check` to fail the
build if this file ever drifts from the yaml.
-->

"""


def _render() -> str:
    laws = load_laws()
    auto = [law for law in laws if law["enforcement"] == "auto"]
    manual = [law for law in laws if law["enforcement"] == "manual"]
    out: list[str] = [GENERATED_HEADER, "# Iron Laws\n\n"]
    out.append(
        "The non-negotiable rules for kaizen-plugin-original development. "
        "This file is a read-only copy of `skills/iron-laws/domain/iron-laws.yaml` "
        "(the single source of truth). `enforcement: auto` laws are machine-checked "
        "by `_iron_laws.py`; `manual` laws are listed + documented but not auto-checked.\n\n"
    )

    out.append("## Summary\n\n")
    out.append(f"{len(laws)} laws — {len(auto)} auto, {len(manual)} manual.\n\n")
    out.append("| id | severity | enforcement | check |\n")
    out.append("|---|---|---|---|\n")
    for law in laws:
        check = f"`{law['check']}`" if law.get("check") else "—"
        out.append(
            f"| `{law['id']}` | {law['severity']} | {law['enforcement']} | {check} |\n"
        )
    out.append("\n")

    out.append("## Laws\n\n")
    for law in laws:
        out.append(f"### `{law['id']}` ({law['severity']} · {law['enforcement']})\n\n")
        out.append(f"{law['statement']}\n\n")
        if law.get("check"):
            out.append(f"**Check:** `{law['check']}` (in `_iron_laws.py`)\n\n")
        if law.get("detect"):
            out.append(f"**Detect:** {law['detect']}\n\n")
        out.append(f"**Why:** {law['why']}\n\n")
    return "".join(out)


def _write_atomic(path: Path, content: str) -> bool:
    """Write only if content differs. Returns True iff a write happened."""
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def generate(check_only: bool = False) -> int:
    content = _render()
    if check_only:
        existing = REF_PATH.read_text(encoding="utf-8") if REF_PATH.exists() else ""
        if existing != content:
            print(f"DRIFT: {REF_PATH}")
            return 1
        print(f"OK:    {REF_PATH}")
        return 0
    changed = _write_atomic(REF_PATH, content)
    print(f"{'wrote' if changed else 'unchanged'}: {REF_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(generate(check_only="--check" in sys.argv))
