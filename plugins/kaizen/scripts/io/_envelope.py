#!/usr/bin/env python3
"""kaizen — canonical tool-output envelope helper.

Every kaizen CLI that supports `--json` should emit through `wrap(...)`
so consumers get the same shape across the whole surface. Schema at
`assets/schemas/tool-output.schema.json`.

## Usage

    from _envelope import wrap, render
    import sys, json

    findings = compute_findings()
    out = wrap(
        tool="kaizen-mytool",
        tool_version="1.0.0",
        data={"findings": findings},
        verdict="green" if not findings else "red",
        counts={"error": sum(1 for f in findings if f.sev == "error"),
                "warn":  sum(1 for f in findings if f.sev == "warn")},
        argv=sys.argv,
    )
    print(render(out))     # deterministic key order + 2-space indent

The wrap() default for `ran_at_utc` is OMITTED (not auto-stamped) so
two identical runs produce byte-identical output. Pass include_time=True
to opt in to the timestamp.

## Decision: stdlib-only

No PyYAML / no jsonschema imports at this layer. Validation against the
envelope schema lives in `tests/test_envelope.py` (where jsonschema is
allowed). The helper itself is pure stdlib so tools embedding it stay
zero-extra-dep.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ENVELOPE_SCHEMA_VERSION = 1

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]  # plugins/kaizen/
_PLUGIN_JSON = _PLUGIN_ROOT / ".claude-plugin" / "plugin.json"


def _plugin_version() -> str:
    """Lookup plugin version from .claude-plugin/plugin.json. Cheap +
    cached at module load."""
    try:
        with _PLUGIN_JSON.open() as f:
            return json.load(f).get("version", "?")
    except (OSError, json.JSONDecodeError):
        return "?"


_PLUGIN_VERSION = _plugin_version()


def wrap(
    tool: str,
    data,
    *,
    tool_version: str | None = None,
    verdict: str | None = None,
    counts: dict[str, int] | None = None,
    duration_ms: int | None = None,
    argv: list[str] | None = None,
    errors: list[str] | None = None,
    include_time: bool = False,
) -> dict:
    """Build the canonical envelope around a tool's data payload.

    Args:
      tool:           identifier ("kaizen-gatekeeper", "kaizen-surface")
      data:           tool-specific payload — any JSON-encodable shape
      tool_version:   optional per-tool semver
      verdict:        green|yellow|red|ok|warn|fail|... or None
      counts:         severity bucket counts (error/warn/info typical)
      duration_ms:    wall-clock for the run
      argv:           verbatim sys.argv — reproducibility aid
      errors:         tool-INTERNAL errors (not findings)
      include_time:   True → add `ran_at_utc`; False (default) → omit so
                      identical runs are byte-identical (reproducible)

    Returns:
      dict matching tool-output.schema.json
    """
    kaizen_meta: dict = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "tool": tool,
        "plugin_version": _PLUGIN_VERSION,
    }
    if tool_version:
        kaizen_meta["tool_version"] = tool_version
    if argv:
        # Drop the absolute path to argv[0] — keeps the command relative
        # / reproducible across machines.
        cmd_parts = [os.path.basename(argv[0])] + list(argv[1:])
        kaizen_meta["command"] = " ".join(cmd_parts)
    if duration_ms is not None:
        kaizen_meta["duration_ms"] = int(duration_ms)
    if include_time:
        kaizen_meta["ran_at_utc"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    out: dict = {"kaizen": kaizen_meta, "data": data}
    if verdict is not None:
        out["verdict"] = verdict
    if counts:
        # Sort keys for deterministic output
        out["counts"] = {k: counts[k] for k in sorted(counts)}
    if errors:
        out["errors"] = list(errors)
    return out


def render(envelope: dict, indent: int = 2) -> str:
    """JSON-serialize the envelope with deterministic key ordering.

    `sort_keys=True` ensures byte-identical output for identical inputs.
    The 2-space indent is human-readable but compact; pass indent=None
    for a single-line minified output (CI consumption)."""
    return json.dumps(envelope, sort_keys=True, indent=indent, default=str)


def opt_in_json(argv: list[str]) -> bool:
    """Helper: True if `--json` flag is in argv. Tools that support both
    text + JSON output can call this for the standard detection."""
    return "--json" in argv


def emitter(tool: str, tool_version: str | None = None):
    """Return a tool-bound emit() — closure pattern.

    Each retrofit was duplicating an inline `_emit(data, verdict, counts)`
    helper that hardcoded the tool name + version + sys.argv. Hoist that
    pattern here so retrofits become:

        import _envelope
        _emit = _envelope.emitter("kaizen-mytool", tool_version="1.0.0")

        # in main():
        if args.json:
            _emit(data, verdict="green", counts={"items": N})

    The returned callable signature mirrors `emit()` minus tool/version
    (already captured) and argv (auto-pulled from sys.argv at call time
    so late-mutation of argv is respected).

    Args:
      tool:         identifier ("kaizen-mytool")
      tool_version: optional per-tool semver

    Returns:
      _bound(data, *, verdict=None, counts=None, duration_ms=None,
             errors=None, include_time=False, indent=2, file=None) -> None
    """
    def _bound(
        data,
        *,
        verdict: str | None = None,
        counts: dict[str, int] | None = None,
        duration_ms: int | None = None,
        errors: list[str] | None = None,
        include_time: bool = False,
        indent: int = 2,
        file=None,
    ) -> None:
        emit(
            tool=tool,
            data=data,
            tool_version=tool_version,
            verdict=verdict,
            counts=counts,
            duration_ms=duration_ms,
            argv=sys.argv,
            errors=errors,
            include_time=include_time,
            indent=indent,
            file=file,
        )
    return _bound


def emit(
    tool: str,
    data,
    *,
    tool_version: str | None = None,
    verdict: str | None = None,
    counts: dict[str, int] | None = None,
    duration_ms: int | None = None,
    argv: list[str] | None = None,
    errors: list[str] | None = None,
    include_time: bool = False,
    indent: int = 2,
    file=None,
) -> None:
    """One-liner replacement for the `--json` branch of CLI tools.

    Equivalent to: `print(render(wrap(...)))` but consolidates the
    8-line "try import / fallback to bare json.dumps" boilerplate that
    early retrofits (gatekeeper, surface, iron-laws) duplicated.

    Tools that support BOTH text + JSON output structure their main()
    as:

        if args.json:
            _envelope.emit(tool="kaizen-foo", tool_version="1.0.0",
                           data=data, verdict=verdict, counts=counts,
                           argv=sys.argv)
        else:
            print(render_text(...))

    Args mirror `wrap()` plus `indent` (render formatting) and `file`
    (default stdout — pass sys.stderr or any file-like for redirection).
    """
    out = render(
        wrap(
            tool=tool,
            data=data,
            tool_version=tool_version,
            verdict=verdict,
            counts=counts,
            duration_ms=duration_ms,
            argv=argv,
            errors=errors,
            include_time=include_time,
        ),
        indent=indent,
    )
    print(out, file=file if file is not None else sys.stdout)


if __name__ == "__main__":
    # Self-test: round-trip a sample envelope
    sample = wrap(
        tool="kaizen-self-test",
        tool_version="0.0.1",
        data={"items": [1, 2, 3]},
        verdict="green",
        counts={"error": 0, "warn": 0},
        duration_ms=42,
        argv=["test", "--flag"],
    )
    print(render(sample))
