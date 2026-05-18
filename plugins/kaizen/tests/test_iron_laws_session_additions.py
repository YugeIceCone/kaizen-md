"""Tests for the 5 new iron-laws added from this session's patterns.

Each law was extracted from observed recurring patterns this session:
  - append-only-sink             — kaizen-progress, learn, observer-events,
                                    patch-journal all follow this shape
  - drift-resilient-config-read  — counter to the kaizen-implementer cache-
                                    pinning bug (9b29d3d); observer rules +
                                    ingest re-read source files per call
  - prcdr-contract-declared      — user's 5-property contract (programmable,
                                    reproducible, consistent, deterministic,
                                    reusable)
  - cross-device-safe-move       — caught via live smoke (Path.rename raises
                                    OSError(EXDEV) cross-filesystem)
  - cli-json-flag                — every structured-output CLI offers --json

Tests verify the laws landed with required shape (id / statement / severity /
enforcement / detect / why) — minimal contract-check, no auto-enforcement
hook required for the law to be documented + cross-referenceable.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_LAWS_YAML = (
    Path(__file__).resolve().parent.parent
    / "skills/iron-laws/domain/iron-laws.yaml"
)

_NEW_LAW_IDS = {
    "append-only-sink",
    "drift-resilient-config-read",
    "prcdr-contract-declared",
    "cross-device-safe-move",
    "cli-json-flag",
    "shim-and-sweep",
    "dry-extract-on-third-repetition",
    "flake-audit-load-before-logic",
}


def _load_laws() -> list[dict]:
    return yaml.safe_load(_LAWS_YAML.read_text(encoding="utf-8"))["laws"]


def test_yaml_parses():
    laws = _load_laws()
    assert isinstance(laws, list)
    assert len(laws) > 0


def test_all_new_laws_present():
    ids = {law["id"] for law in _load_laws()}
    missing = _NEW_LAW_IDS - ids
    assert not missing, f"missing law ids: {missing}"


def test_each_new_law_has_required_fields():
    by_id = {law["id"]: law for law in _load_laws()}
    for lid in _NEW_LAW_IDS:
        law = by_id[lid]
        for field in ("id", "statement", "severity", "enforcement",
                       "detect", "why"):
            assert field in law, f"{lid} missing field {field}"


def test_severity_values_valid():
    by_id = {law["id"]: law for law in _load_laws()}
    for lid in _NEW_LAW_IDS:
        assert by_id[lid]["severity"] in ("hard", "soft", "info"), \
            f"{lid} severity invalid"


def test_enforcement_values_valid():
    by_id = {law["id"]: law for law in _load_laws()}
    for lid in _NEW_LAW_IDS:
        assert by_id[lid]["enforcement"] in ("auto", "manual"), \
            f"{lid} enforcement invalid"


def test_auto_enforced_laws_have_check_name():
    by_id = {law["id"]: law for law in _load_laws()}
    for lid in _NEW_LAW_IDS:
        law = by_id[lid]
        if law["enforcement"] == "auto":
            assert "check" in law and law["check"], \
                f"{lid} is enforcement=auto but missing `check:` field"


def test_law_ids_unique():
    """No accidental duplicate id across the whole registry."""
    ids = [law["id"] for law in _load_laws()]
    assert len(ids) == len(set(ids)), "duplicate ids in iron-laws.yaml"


def test_new_law_statements_reference_session_evidence():
    """Each new law's `why` field should cite the session evidence
    (commit SHA / pattern name) that prompted it."""
    by_id = {law["id"]: law for law in _load_laws()}
    evidence_hints = {
        "append-only-sink":             ["kaizen-progress", "append-only"],
        "drift-resilient-config-read":  ["9b29d3d", "cache"],
        "prcdr-contract-declared":      ["programmable", "reproducible"],
        "cross-device-safe-move":       ["EXDEV", "shutil.move"],
        "cli-json-flag":                ["--json", "scripting"],
        "shim-and-sweep":               ["6a717e1", "stale"],
        "dry-extract-on-third-repetition": ["rule-of-three", "3a18b8f"],
    }
    for lid, hints in evidence_hints.items():
        why = by_id[lid].get("why", "").lower()
        matched = [h for h in hints if h.lower() in why]
        assert matched, f"{lid}.why should reference at least one of {hints}; got: {why[:200]}"
