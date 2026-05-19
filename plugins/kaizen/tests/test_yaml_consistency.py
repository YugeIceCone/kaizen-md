"""Consistency tests for kaizen-original YAML files.

Bounded scope - skills/<feature>/domain/*.yaml + schemas/<name>/schema.yaml.
Excluded - agents/*.yaml (subagent briefs - generated, different
bounded context).

Rule (refined per the schema-sidecar audit):
- schemas/<name>/schema.yaml MUST declare inline `version:`
  (workflow schemas own their format contract).
- skills/<feature>/domain/X.yaml — if the feature has NO
  domain/schemas/ JSON-schema sidecar, the yaml MUST declare inline
  `version:` (the data file is the format SSOT).
  If a sidecar JSON schema exists, the schema IS the version surface
  (via $id) and inline `version` is redundant + would trigger
  `additionalProperties: false` rejection.

Per SoC + DRY - one version surface per contract, not two.
"""
from __future__ import annotations

import unittest
from pathlib import Path

try:
    import yaml  # type: ignore
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

_PLUGIN = Path(__file__).resolve().parent.parent


def _domain_yamls() -> list[Path]:
    return sorted(_PLUGIN.glob("skills/*/domain/*.yaml"))


def _schema_yamls() -> list[Path]:
    return sorted(_PLUGIN.glob("schemas/*/schema.yaml"))


def _has_sidecar_schema(domain_yaml: Path) -> bool:
    """True iff a JSON-schema sidecar exists for this domain yaml's
    feature. Sidecar lives at skills/<feature>/domain/schemas/*.schema.json.
    """
    skill_dir = domain_yaml.parents[1]
    schema_dir = skill_dir / "domain" / "schemas"
    if not schema_dir.is_dir():
        return False
    return any(schema_dir.glob("*.schema.json"))


def _has_version(p: Path) -> bool:
    data = yaml.safe_load(p.read_text())
    return isinstance(data, dict) and "version" in data


class TestVersionFieldPresent(unittest.TestCase):
    """Every yaml-format SSOT declares its version surface.

    Either inline `version:` in the yaml, OR a sidecar JSON schema
    (which carries version via $id). Not both — that's the SoC line.
    """

    @unittest.skipUnless(_HAS_YAML, "PyYAML not installed")
    def test_every_schema_yaml_has_version(self):
        """Workflow schemas always own their version inline."""
        missing = [str(p.relative_to(_PLUGIN)) for p in _schema_yamls()
                   if not _has_version(p)]
        self.assertEqual(missing, [],
            f"\n{len(missing)} schema yaml(s) missing inline `version:`:\n"
            + "\n".join(f"  - {f}" for f in missing))

    @unittest.skipUnless(_HAS_YAML, "PyYAML not installed")
    def test_every_bare_domain_yaml_has_version(self):
        """Domain yamls without a sidecar JSON schema must carry
        inline `version:`. Those WITH a sidecar inherit version from
        the schema's $id — adding inline version would conflict with
        the schema's `additionalProperties: false`."""
        missing = []
        for p in _domain_yamls():
            if _has_sidecar_schema(p):
                continue
            if not _has_version(p):
                missing.append(str(p.relative_to(_PLUGIN)))
        self.assertEqual(missing, [],
            f"\n{len(missing)} bare domain yaml(s) missing inline "
            f"`version:` (no JSON-schema sidecar to inherit from):\n"
            + "\n".join(f"  - {f}" for f in missing)
            + "\nFix - add `version: 1` (or higher) at top-level.")


if __name__ == "__main__":
    unittest.main()
