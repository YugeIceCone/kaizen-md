"""kaizen lens — schema-driven CLI runtime helper.

Pairs with ``_envelope.py``: every kaizen subcommand can declare its
input/output contract in a v2 manifest at ``skills/<feature>/domain/<feature>.yaml``,
and ``lens`` validates I/O against those schemas before the canonical
envelope ships. Plus a data-driven ``BucketWalker`` for rubric /
classifier-shaped rule yamls (the deterministic outcome rubric is the
motivating consumer).

See the ``schema-driven-cli`` SKILL.md for the full pattern and when
to reach for the lens vs. directly using ``_envelope.emitter``.

## Public surface

    Manifest                       — v2 feature manifest loader
    Subcommand                     — one subcommand's input/output schemas
    ManifestError                  — manifest-shape problems
    SchemaValidationError          — input/output didn't match
    lens_emit(...)                 — validate output → wrap envelope → write
    lens_dispatch(...)             — validate input → handler → emit

    BucketWalker                   — walks a rubric yaml against signal dict
    BucketWalker.from_yaml(path)
    BucketWalker.evaluate(signals) → WalkerResult
    WalkerResult.bucket / .method / .confidence / .rationale
    RuleError                      — unknown operator, malformed rule

## Dependencies

PyYAML required (matches ``application/_yaml.py`` discipline).
``jsonschema`` optional — when absent, validation skips with a stderr
warning (constrained CI sandboxes).
"""

from __future__ import annotations

import json
import operator
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _envelope  # noqa: E402


try:
    import yaml as _yaml
except ImportError:  # pragma: no cover — kaizen environments install PyYAML
    sys.stderr.write(
        "lens: PyYAML required (pip install pyyaml) — manifests are YAML\n"
    )
    raise

try:
    from jsonschema import validate as _js_validate
    from jsonschema import ValidationError as _JsValidationError
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False


# ─── Errors ──────────────────────────────────────────────────────────


class ManifestError(ValueError):
    """A feature manifest is missing required keys, wrong version, etc."""


class SchemaValidationError(ValueError):
    """Input or output failed schema validation. Stops the lens flow."""


class RuleError(ValueError):
    """A rule yaml uses an unknown operator or malformed condition."""


# ─── Manifest + Subcommand ───────────────────────────────────────────


_MANIFEST_REQUIRED = ("version", "feature", "subcommands")
_MANIFEST_VERSION = 2


@dataclass
class Subcommand:
    """One subcommand's I/O contract.

    Either schema path may be None (subcommand declined to declare one);
    in that case the matching validate_* is a no-op."""

    name: str
    description: str = ""
    input_schema_path: Optional[Path] = None
    output_schema_path: Optional[Path] = None

    def validate_input(self, data: Any) -> None:
        if self.input_schema_path is None:
            return
        _validate_against(self.input_schema_path, data, where="input")

    def validate_output(self, data: Any) -> None:
        if self.output_schema_path is None:
            return
        _validate_against(self.output_schema_path, data, where="output")


class Manifest:
    """A feature's v2 manifest, loaded from yaml.

    Subcommand schema paths are resolved RELATIVE TO THE MANIFEST FILE
    so the manifest itself is the contract's root."""

    def __init__(
        self,
        version: int,
        feature: str,
        subcommands: dict[str, Subcommand],
        path: Path,
    ):
        self.version = version
        self.feature = feature
        self.subcommands = subcommands
        self.path = path

    @classmethod
    def load(cls, manifest_path: Path) -> "Manifest":
        path = Path(manifest_path).resolve()
        if not path.is_file():
            raise ManifestError(f"manifest not found: {path}")

        with path.open("r", encoding="utf-8") as f:
            raw = _yaml.safe_load(f) or {}

        for key in _MANIFEST_REQUIRED:
            if key not in raw:
                raise ManifestError(
                    f"{path.name}: missing required key {key!r} — "
                    f"v{_MANIFEST_VERSION} manifests need: {', '.join(_MANIFEST_REQUIRED)}"
                )

        if raw.get("version") != _MANIFEST_VERSION:
            raise ManifestError(
                f"{path.name}: version {raw.get('version')!r} unsupported — "
                f"lens requires version: {_MANIFEST_VERSION}"
            )

        manifest_dir = path.parent
        subs: dict[str, Subcommand] = {}
        for name, body in (raw.get("subcommands") or {}).items():
            body = body or {}
            subs[name] = Subcommand(
                name=name,
                description=body.get("description", "") or "",
                input_schema_path=_resolve_schema(manifest_dir, body.get("input_schema")),
                output_schema_path=_resolve_schema(manifest_dir, body.get("output_schema")),
            )

        return cls(
            version=raw["version"],
            feature=raw["feature"],
            subcommands=subs,
            path=path,
        )

    def get(self, subcommand_name: str) -> Subcommand:
        try:
            return self.subcommands[subcommand_name]
        except KeyError:
            raise KeyError(
                f"{self.path.name}: unknown subcommand {subcommand_name!r} "
                f"(known: {', '.join(sorted(self.subcommands)) or '<none>'})"
            )


def _resolve_schema(manifest_dir: Path, ref: Optional[str]) -> Optional[Path]:
    if not ref:
        return None
    p = Path(ref)
    if not p.is_absolute():
        p = manifest_dir / p
    return p


def _validate_against(schema_path: Path, data: Any, *, where: str) -> None:
    """Raise SchemaValidationError on miss; silently skip if jsonschema unavailable."""
    if not _HAS_JSONSCHEMA:
        sys.stderr.write(
            f"[lens] jsonschema not installed; skipping {where} validation "
            f"against {schema_path.name}\n"
        )
        return
    if not schema_path.is_file():
        raise SchemaValidationError(
            f"{where} schema not found: {schema_path}"
        )
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    try:
        _js_validate(data, schema)
    except _JsValidationError as exc:
        raise SchemaValidationError(
            f"{where} failed schema {schema_path.name}: {exc.message} "
            f"at {list(exc.absolute_path) or '<root>'}"
        ) from exc


# ─── Envelope emission (the "lens" rendering layer) ──────────────────


def lens_emit(
    tool: str,
    manifest: Manifest,
    subcommand: str,
    data: Any,
    *,
    verdict: Optional[str] = None,
    counts: Optional[dict[str, int]] = None,
    tool_version: Optional[str] = None,
    file=None,
) -> None:
    """Validate `data` against the subcommand's output schema, then emit
    the canonical envelope via `_envelope.emitter()`.

    Fails closed: SchemaValidationError raises BEFORE anything is
    written to `file`. Callers that want a "best effort even if shape
    is wrong" path should skip lens_emit and call `_envelope.emit`
    directly."""
    sub = manifest.get(subcommand)
    sub.validate_output(data)
    emitter = _envelope.emitter(tool, tool_version=tool_version)
    emitter(data, verdict=verdict, counts=counts, file=file)


def lens_dispatch(
    tool: str,
    manifest: Manifest,
    subcommand: str,
    *,
    input_data: Any,
    handler: Callable[[Any], Any],
    verdict: Optional[str] = None,
    counts: Optional[dict[str, int]] = None,
    tool_version: Optional[str] = None,
    file=None,
) -> int:
    """End-to-end lens flow: validate input → run handler → validate +
    emit output. Returns 0 on success, non-zero on any validation
    failure (handler exceptions propagate)."""
    sub = manifest.get(subcommand)
    try:
        sub.validate_input(input_data)
    except SchemaValidationError as exc:
        sys.stderr.write(f"[{tool}] input rejected: {exc}\n")
        return 2

    output = handler(input_data)

    try:
        sub.validate_output(output)
    except SchemaValidationError as exc:
        sys.stderr.write(f"[{tool}] output rejected: {exc}\n")
        return 2

    emitter = _envelope.emitter(tool, tool_version=tool_version)
    emitter(output, verdict=verdict, counts=counts, file=file)
    return 0


# ─── BucketWalker — data-driven classifier over a signal dict ────────


_OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    ">=": operator.ge,
    ">":  operator.gt,
    "<=": operator.le,
    "<":  operator.lt,
    "==": operator.eq,
    "!=": operator.ne,
}


@dataclass
class _Rule:
    bucket: str
    require_all: list[dict] = field(default_factory=list)
    require_any: list[dict] = field(default_factory=list)


@dataclass
class WalkerResult:
    bucket: str
    method: str             # "deterministic" | "fallback"
    confidence: float       # 1.0 for deterministic match, threshold for fallback
    matched_conditions: int
    total_conditions: int
    rationale: str


class BucketWalker:
    """Walks a rubric yaml against a signal dict; first matching rule wins.

    Rule yaml shape::

        rules:
          - bucket: SUCCEEDED
            require_all:
              - {signal: completed_ratio, op: ">=", value: 1.0}
              - {signal: blocker_count,   op: "==", value: 0}
          - bucket: PARTIAL_MINUS
            require_any:
              - {signal: blocker_count,   op: ">",  value: 0}
        confidence_threshold: 0.85
        fallback: NEEDS_AGENT

    `require_all` semantics: ALL conditions must hold for the rule to fire.
    `require_any` semantics: at least one condition must hold.
    A rule with both keys is ALL-then-ANY (rare but legal). A missing
    signal in the input is treated as an unsatisfied condition (no
    KeyError raised). Unknown operator → RuleError at load time."""

    def __init__(
        self, rules: list[_Rule], confidence_threshold: float, fallback: str,
    ):
        self.rules = rules
        self.confidence_threshold = confidence_threshold
        self.fallback = fallback

    @classmethod
    def from_yaml(cls, path: Path) -> "BucketWalker":
        with Path(path).open("r", encoding="utf-8") as f:
            raw = _yaml.safe_load(f) or {}

        rules: list[_Rule] = []
        for rule_raw in (raw.get("rules") or []):
            require_all = list(rule_raw.get("require_all") or [])
            require_any = list(rule_raw.get("require_any") or [])
            for cond in require_all + require_any:
                op = cond.get("op")
                if op not in _OPERATORS:
                    raise RuleError(
                        f"unknown operator {op!r} in rule {rule_raw.get('bucket')!r} — "
                        f"valid: {', '.join(sorted(_OPERATORS))}"
                    )
            rules.append(_Rule(
                bucket=rule_raw["bucket"],
                require_all=require_all,
                require_any=require_any,
            ))

        return cls(
            rules=rules,
            confidence_threshold=float(raw.get("confidence_threshold", 0.85)),
            fallback=str(raw.get("fallback", "NEEDS_AGENT")),
        )

    def evaluate(self, signals: dict[str, Any]) -> WalkerResult:
        for rule in self.rules:
            matched, total = self._check(rule, signals)
            if matched is None:
                continue  # rule did not fire
            return WalkerResult(
                bucket=rule.bucket,
                method="deterministic",
                confidence=1.0,
                matched_conditions=matched,
                total_conditions=total,
                rationale=(
                    f"rule {rule.bucket!r} matched "
                    f"({matched}/{total} conditions clear)"
                ),
            )

        return WalkerResult(
            bucket=self.fallback,
            method="fallback",
            confidence=self.confidence_threshold,
            matched_conditions=0,
            total_conditions=0,
            rationale=(
                f"no rule matched signals — falling back to {self.fallback!r}"
            ),
        )

    @staticmethod
    def _check(rule: _Rule, signals: dict[str, Any]) -> tuple[Optional[int], int]:
        """Return (matched_count, total) when the rule fires, else (None, total)."""
        total = len(rule.require_all) + len(rule.require_any)
        all_pass = all(
            _eval_condition(c, signals) for c in rule.require_all
        ) if rule.require_all else True
        any_pass = any(
            _eval_condition(c, signals) for c in rule.require_any
        ) if rule.require_any else True

        if rule.require_all and not all_pass:
            return None, total
        if rule.require_any and not any_pass:
            return None, total

        matched = sum(
            1 for c in (rule.require_all + rule.require_any)
            if _eval_condition(c, signals)
        )
        return matched, total


def _eval_condition(cond: dict, signals: dict[str, Any]) -> bool:
    """Apply one condition's op to the corresponding signal. Missing
    signal → unsatisfied (False), never raises."""
    sig = cond["signal"]
    op_fn = _OPERATORS[cond["op"]]
    value = cond["value"]
    if sig not in signals:
        return False
    return op_fn(signals[sig], value)


if __name__ == "__main__":  # pragma: no cover — lens is a library
    sys.stderr.write(
        "lens.py is a library — use Manifest.load() / lens_emit() / "
        "lens_dispatch() / BucketWalker from your CLI script.\n"
    )
    raise SystemExit(2)
