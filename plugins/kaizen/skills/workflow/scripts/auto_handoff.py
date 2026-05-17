"""kaizen auto_handoff — schema-driven context-pressure trigger that
forces a handoff before /compact. When fires, returns
`{"decision": "block", "reason": ...}` which prevents the agent from
stopping until a handoff is created.

Config: skills/auto-handoff/domain/config.yaml
        (validated against schemas/config.schema.json)
        Overridable via KAIZEN_AUTO_HANDOFF_CONFIG=<path>.

Dedupe: dxm event written on first fire (configured event type).
        Subsequent invocations see the marker → no-op.
        Once per session.

Bypass: KAIZEN_AUTO_HANDOFF_DISABLE=1 (full opt-out).

CLI:
    auto_handoff.py check [--session SID] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _dxm_emit  # noqa: E402
import _session_jsonl as _sj  # noqa: E402
import context as _ctx  # noqa: E402
import session_mode as _sm  # noqa: E402


# script at skills/workflow/scripts/ → plugin_root is 3 levels up
_PLUGIN_ROOT = _SCRIPT_DIR.parent.parent.parent
_DEFAULT_CONFIG_PATH = _PLUGIN_ROOT / "skills" / "auto-handoff" / "domain" / "config.yaml"
_DEFAULT_RUBRIC_PATH = _PLUGIN_ROOT / "skills" / "auto-handoff" / "domain" / "rubric.yaml"

_BUILTIN_DEFAULT = {
    "version": 1,
    "valid_thresholds": [25, 50, 75, 85],
    "dedupe_event_type": "auto_handoff.requested",
    "on_fire": {
        "decision": "block",
        "reason_template": (
            "⚠ MANDATORY pre-compact handoff (context at {pct}%, "
            "threshold {threshold}%). Create the handoff before Stop."
        ),
    },
}


def _config_path() -> Path:
    env = os.environ.get("KAIZEN_AUTO_HANDOFF_CONFIG")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return _DEFAULT_CONFIG_PATH


def _rubric_path() -> Path:
    env = os.environ.get("KAIZEN_AUTO_HANDOFF_RUBRIC")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return _DEFAULT_RUBRIC_PATH


def _compute_signals(*, pct: int, threshold: int,
                       compact_count: int = 0,
                       peak_pct: int | None = None) -> dict:
    """Pure-function signal computer for the BucketWalker. All ints
    so the rubric's numeric comparisons work cleanly."""
    return {
        "pct":             int(pct),
        "threshold":       int(threshold),
        "above_threshold": 1 if pct >= threshold else 0,
        "compact_count":   int(compact_count),
        "peak_pct":        int(peak_pct if peak_pct is not None else pct),
        "threshold_delta": int(pct) - int(threshold),
    }


def _walk_rubric(signals: dict) -> str | None:
    """Load rubric.yaml + walk against signals. Returns the bucket
    name (e.g. 'critical-block'), or None when the rubric is absent
    or BucketWalker is unavailable. 'noop' bucket → None."""
    path = _rubric_path()
    if not path.is_file():
        return None
    try:
        import schema_cli
    except ImportError:
        return None
    try:
        walker = schema_cli.BucketWalker.from_yaml(path)
        result = walker.evaluate(signals)
    except Exception:
        return None
    if not result.bucket or result.bucket == "noop":
        return None
    return result.bucket


def load_config() -> dict:
    """Load + minimally validate config.yaml. Falls back to builtin
    defaults on parse error so the hook never breaks the host flow."""
    path = _config_path()
    if not path.is_file():
        return dict(_BUILTIN_DEFAULT)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return dict(_BUILTIN_DEFAULT)
    try:
        import yaml  # type: ignore
        parsed = yaml.safe_load(text)
    except Exception:
        return dict(_BUILTIN_DEFAULT)
    if not isinstance(parsed, dict):
        return dict(_BUILTIN_DEFAULT)
    # Light validation — full JSONSchema check is in tests
    if not isinstance(parsed.get("version"), int):
        return dict(_BUILTIN_DEFAULT)
    if not isinstance(parsed.get("valid_thresholds"), list):
        return dict(_BUILTIN_DEFAULT)
    if not isinstance(parsed.get("dedupe_event_type"), str):
        return dict(_BUILTIN_DEFAULT)
    if not isinstance(parsed.get("on_fire"), dict):
        return dict(_BUILTIN_DEFAULT)
    return parsed


def _dxm_dir() -> Path:
    env = os.environ.get("KAIZEN_DXM_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path.home() / ".claude" / ".kaizen" / "dxm"


def _already_fired(session_id: str, evt_type: str) -> bool:
    path = _dxm_dir() / f"events-{session_id}.jsonl"
    if not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if evt_type in line:
                    return True
    except OSError:
        pass
    return False


def _session_threshold() -> int | None:
    state = _sm.read_state()
    if state is None:
        return None
    t = state.get("auto_handoff_threshold")
    if isinstance(t, int) and t in _sm._VALID_THRESHOLDS:
        return t
    return None


def _format_reason(template: str, **vars) -> str:
    """Safe template substitution — only the documented vars expand;
    stray braces in the template don't blow up KeyError."""
    out = template
    for k, v in vars.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def check(session_id: str | None = None) -> dict:
    """Return decision dict — {} no-op, OR {"decision":"block","reason":…},
    OR {"systemMessage":…} depending on config.on_fire.decision."""
    if os.environ.get("KAIZEN_AUTO_HANDOFF_DISABLE") == "1":
        return {}

    threshold = _session_threshold()
    if threshold is None:
        return {}

    sid = session_id or _sj.discover_active_session_id()
    if not sid:
        return {}

    cfg = load_config()
    evt_type = cfg["dedupe_event_type"]
    if _already_fired(sid, evt_type):
        return {}

    summary = _ctx.get_usage_summary()
    if summary["current_tokens"] is None:
        return {}
    limit = _ctx.get_limit()
    pct = (summary["current_tokens"] * 100) // limit

    # Compute signals for the rubric (or for fallback single-threshold).
    peak_tokens = summary["peak_tokens"]
    peak_pct = (peak_tokens * 100 // limit) if peak_tokens is not None else pct
    compact_count = int(summary.get("compact_count") or 0)
    signals = _compute_signals(
        pct=pct, threshold=threshold,
        compact_count=compact_count, peak_pct=peak_pct,
    )

    # Rubric path (preferred) — multi-signal classification with
    # per-bucket actions. Falls through to single-threshold logic
    # when rubric is absent or returns noop.
    bucket = _walk_rubric(signals)
    if bucket is not None:
        on_bucket = (cfg.get("on_bucket") or {}).get(bucket)
        if on_bucket is None:
            return {}  # bucket mapped to null = no-op
        decision_kind = on_bucket.get("decision", "block")
        if decision_kind == "noop":
            return {}
        template = on_bucket.get(
            "reason_template", cfg["on_fire"]["reason_template"])
    else:
        # Fallback: original single-threshold gate (pct >= threshold).
        if pct < threshold:
            return {}
        decision_kind = cfg["on_fire"]["decision"]
        template = cfg["on_fire"]["reason_template"]

    # Write dedupe marker FIRST — concurrent fires don't double-block.
    _dxm_emit.emit_event(
        evt_type,
        tool_name="kaizen-auto-handoff",
        payload={"pct": pct, "threshold": threshold,
                  "tokens": summary["current_tokens"],
                  "peak_tokens": peak_tokens,
                  "bucket": bucket or "single-threshold"},
        session_id=sid,
    )

    reason = _format_reason(
        template,
        pct=pct, threshold=threshold,
        tokens=summary["current_tokens"],
        peak_pct=peak_pct,
        compact_count=compact_count,
    ).strip()

    if decision_kind == "block":
        return {"decision": "block", "reason": reason}
    return {"systemMessage": reason}


def _cmd_check(args) -> int:
    decision = check(session_id=args.session)
    print(json.dumps(decision or {}))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-auto-handoff",
        description="Schema-driven context-pressure trigger; blocks Stop until handoff.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("check", help="check + decide (block | systemMessage | no-op)")
    sc.add_argument("--session", default=None)
    sc.add_argument("--json", action="store_true",
                     help="(no-op flag — output is always JSON)")
    sc.set_defaults(func=_cmd_check)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
