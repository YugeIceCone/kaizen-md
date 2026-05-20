#!/usr/bin/env python3
"""kaizen config — single editable file for plugin-wide defaults + SSOT
parser for per-project `.kaizen.toml`.

## Where things live (the config trio)

| File | Layer | What it owns |
|---|---|---|
| `config.py` (this file) | **Plugin defaults** + per-project TOML parser | `PLUGIN ▸ DEFAULTS` constants, embedding model, dims, size caps, `.kaizen.toml` reader |
| `_paths.py`             | **Path SSOT (Python)**                       | every `KAIZEN_*_DIR` resolver — `~/.claude/.kaizen/` layout |
| `_paths.sh`             | **Path SSOT (shell mirror)**                 | bash-source-able variants of the same KAIZEN_*_DIR vars |

Resolution order (low → high precedence):
  1. `config.py` PLUGIN_DEFAULTS               (shipped defaults)
  2. `_paths.{py,sh}` env-overridable paths    (KAIZEN_* env vars)
  3. `<repo>/.kaizen.toml`                     (per-project key=value)

When prose and code disagree, **code wins** — these files are the SSOT.

## Two responsibilities of THIS file

1. **Plugin defaults** — the `PLUGIN ▸ DEFAULTS` section at the top of
   this file is the ONE place to edit the plugin's wide-reaching knobs:
   path layout, embedding model, dimensions, size caps. Every kaizen
   script imports from here so a tune-once surface is the convention.

2. **Per-project `.kaizen.toml` parser** — the lower section retains the
   v1.5.0+ contract: a flat TOML file at repo root holds per-repo gate
   knobs (`compile_check_cmd`, `verify_cmd`, `backlog_path`,
   `architecture_log`). The `load_config()` / `get()` / CLI surface is
   unchanged.

Both surfaces ship in this file so users wanting to retune kaizen only
have to read one place. The plugin defaults are environment-overridable;
per-project keys override defaults at the repo level.

## CLI

    config.py                 # print all per-project key=value pairs
    config.py <key>           # print one per-project key value
    config.py <key> --default <fallback>  # print with fallback
    config.py --json          # full per-project config as JSON
    config.py --defaults      # print the plugin-wide DEFAULTS (v1.22.0+)
    config.py --validate      # schema + fs check

Shell-facing wrapper: `kaizen-config <args>` (in `bin/`).

## Env-var overrides (from _paths.{py,sh})

  KAIZEN_DIR                       # user-global root (default ~/.claude/.kaizen)
  KAIZEN_INDEXES_DIR / DATA_DIR / SNAPSHOTS_DIR / ARCHIVE_DIR
  KAIZEN_INBOX_DIR / BACKUP_DIR / USER_SCHEMAS
  KAIZEN_HANDOFF_DIR               # ~/.claude/handoff (separate; user-facing)
  KAIZEN_*_DISABLE                 # per-feature bypass (every hook honors this)

See `_paths.sh` for the complete list with defaults.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

# Late import — _envelope lives alongside config.py; deferred to avoid
# a circular at module-load time (consumers of config.py would also
# trigger _envelope's plugin.json lookup before sys.path has been set).
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "io"))
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-config", tool_version="1.0.0")

# ═══════════════════════════════════════════════════════════════════════
# PLUGIN ▸ DEFAULTS — edit this one block to retune the plugin.
# ═══════════════════════════════════════════════════════════════════════
#
# Each value can also be overridden at runtime via the matching env var
# (shown in the comment). Setting an env var wins over the constant here.

# Path layout — user-global root (v1.22.0+ unification).
USER_DIR_NAME           = ".kaizen"              # env: -- (directory name under ~/.claude/)
USER_TRACE_NAME         = "trace"                # env: -- (subdir name)
USER_KNOWLEDGE_NAME     = "knowledge"
USER_DAEMON_NAME        = "daemon"
USER_INBOX_NAME         = "inbox"
USER_BACKUPS_NAME       = "backups"
USER_SCHEMAS_NAME       = "schemas"
USER_SCRAPE_NAME        = "scrape"               # v1.24.0+ — scrape index dir
USER_OBSERVE_NAME       = "observe"              # v1.30.0+ — observe snapshots dir
USER_CLAUDE_DOCS_NAME   = "claude-docs"          # v1.30.0+ — Claude API/Code docs sem-index dir
USER_BRAIN_NAME         = "brain"                # v1.38.0+ — Second Brain (PARA + Persona + Notes)
INSTALL_LOG_NAME        = "install.log"          # v1.30.0+ — kaizen install/setup log
# v1.39.0+ umbrella dirs — flatten 4 search dirs under indexes/, 5
# operational singletons under data/, 1 observability dir hoisted to
# snapshots/, rename _legacy → archive.
USER_INDEXES_NAME       = "indexes"              # v1.39.0+ — umbrella for trace/knowledge/scrape/claude-docs
USER_DATA_NAME          = "data"                 # v1.39.0+ — umbrella for daemon/handoff/manifest/profile
USER_SNAPSHOTS_NAME     = "snapshots"            # v1.39.0+ — hoisted from observe/snapshots/
ARCHIVE_NAME            = "archive"              # v1.39.0+ — was _legacy (drop misleading underscore)
# Legacy (pre-v1.39.0) name kept for migrator detection only.
LEGACY_ARCHIVE_NAME     = "_legacy"              # v1.30.0–1.38.x — superseded by ARCHIVE_NAME

# v1.30.0+ — upstream source for Claude docs (cloned by `claude_docs_index bootstrap`).
CLAUDE_DOCS_REPO_URL    = "https://github.com/ericbuess/claude-code-docs.git"

# Project-side layout (relative to repo root).
PROJECT_KAIZEN_NAME     = ".kaizen"              # env: --
PROJECT_WORKFLOW_NAME   = "workflow"             # under .kaizen/: state.json + backlog.json + ...

# Semantic search (trace_index, knowledge_index, onboard_index).
EMBED_MODEL             = "all-MiniLM-L6-v2"     # env: KAIZEN_EMBED_MODEL
EMBED_DIM               = 384                    # env: -- (matches all-MiniLM-L6-v2)

# Per-corpus knobs.
ONBOARD_MAX_BYTES       = 1_000_000              # env: KAIZEN_ONBOARD_MAX_BYTES
ONBOARD_SNIPPET_MAX     = 2048
KNOWLEDGE_SNIPPET_MAX   = 400
SCRAPE_SNIPPET_MAX      = 1024                   # v1.24.0+ — chars stored per scrape item

# Scrape — defaults the user can retune (env vars still win).
# Empty SCRAPE_LLM_MODEL ("") triggers zero-config auto-detect on first use
# (probes llama.cpp server / Ollama / LM Studio / vLLM / text-gen-webui ports).
SCRAPE_LLM_MODEL        = ""                      # env: KAIZEN_SCRAPE_LLM_MODEL — "" = auto
SCRAPE_LLM_BASE_URL     = ""                      # env: KAIZEN_SCRAPE_LLM_BASE_URL — "" = auto
SCRAPE_LLM_AUTO         = True                    # env: KAIZEN_SCRAPE_LLM_AUTO=0 to disable probe
SCRAPE_LLM_PROBE_TIMEOUT = 2.0                    # seconds per endpoint
SCRAPE_DEFAULT_PROMPT   = "Extract the main content as structured data: title, headings, key facts, and any tabular data. Return JSON."

# Probe targets — ordered by ascending invasiveness (local-first). Each entry:
#   (provider_prefix, base_url, list_endpoint, model_field)
# provider_prefix is what scrapegraph-ai's model string needs: "openai/<m>"
# for OpenAI-compatible servers, "ollama/<m>" for Ollama.
SCRAPE_LLM_PROBES = [
    # llama.cpp `llama-server` (most common port). Native OpenAI-compatible API.
    ("openai", "http://localhost:8080/v1", "/models", "id"),
    # Ollama (different endpoint shape — handled in detect_llm)
    ("ollama", "http://localhost:11434",   "/api/tags", "name"),
    # LM Studio
    ("openai", "http://localhost:1234/v1", "/models", "id"),
    # vLLM / OpenAI Python proxy
    ("openai", "http://localhost:8000/v1", "/models", "id"),
    # text-generation-webui (oobabooga) OpenAI extension
    ("openai", "http://localhost:5000/v1", "/models", "id"),
]

# Env-var resolution for scrape (env wins over the constants above).
SCRAPE_LLM_MODEL    = os.environ.get("KAIZEN_SCRAPE_LLM_MODEL",    SCRAPE_LLM_MODEL)
SCRAPE_LLM_BASE_URL = os.environ.get("KAIZEN_SCRAPE_LLM_BASE_URL", SCRAPE_LLM_BASE_URL)
SCRAPE_LLM_AUTO     = os.environ.get("KAIZEN_SCRAPE_LLM_AUTO", "1") not in ("0", "false", "no")

# Env-var resolution for the knobs that ARE env-overridable.
EMBED_MODEL = os.environ.get("KAIZEN_EMBED_MODEL", EMBED_MODEL)
try:
    ONBOARD_MAX_BYTES = int(os.environ.get("KAIZEN_ONBOARD_MAX_BYTES", ONBOARD_MAX_BYTES))
except ValueError:
    pass  # keep the default if env var is malformed

# ═══════════════════════════════════════════════════════════════════════
# Per-project .kaizen.toml parser (v1.5.0+ contract; unchanged).
# ═══════════════════════════════════════════════════════════════════════

DEFAULTS: dict = {
    "compile_check_cmd": "",
    "verify_cmd": "",
    "backlog_path": f"{PROJECT_KAIZEN_NAME}/{PROJECT_WORKFLOW_NAME}/backlog.md",
    "architecture_log": f"{PROJECT_KAIZEN_NAME}/{PROJECT_WORKFLOW_NAME}/progress.md",
}

def repo_root(start: Path | None = None) -> Path | None:
    """Walk up from `start` (default: cwd) looking for `.git/` or `.kaizen.toml`.
    Returns the directory containing either, or None if nothing found."""
    cur = (start or Path.cwd()).resolve()
    while True:
        if (cur / ".git").exists() or (cur / ".kaizen.toml").exists():
            return cur
        if cur.parent == cur:
            return None
        cur = cur.parent

def config_path(repo: Path | None = None) -> Path | None:
    r = repo if repo is not None else repo_root()
    return (r / ".kaizen.toml") if r is not None else None

def load_config(repo: Path | None = None) -> dict:
    """Load `.kaizen.toml` and merge over DEFAULTS. Returns DEFAULTS on any
    error (missing file, parse failure, no tomllib). Never raises."""
    p = config_path(repo)
    if p is None or not p.exists():
        return DEFAULTS.copy()
    if tomllib is None:
        # Python <3.11 — degraded grep-style fallback
        return _legacy_parse(p)
    try:
        data = tomllib.loads(p.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return DEFAULTS.copy()
    result = DEFAULTS.copy()
    if isinstance(data, dict):
        # Only stringify scalar values for bash-callable output;
        # nested tables stay as dicts in the Python-callable path.
        for k, v in data.items():
            result[k] = v
    return result

def _legacy_parse(p: Path) -> dict:
    """Fallback for Python <3.11 without tomllib. Handles only top-level
    `key = "value"` and `key = value` lines (no tables, no nested)."""
    result = DEFAULTS.copy()
    try:
        text = p.read_text()
    except OSError:
        return result
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        result[key] = val
    return result

def get(key: str, default: str = "", repo: Path | None = None) -> str:
    """Convenience: fetch one key as a string. Bash callers use this."""
    cfg = load_config(repo)
    v = cfg.get(key, default)
    return str(v) if v is not None else default

# ─── CLI ─────────────────────────────────────────────────────────────

KNOWN_KEYS = set(DEFAULTS.keys()) | {
    "plan_dir",
    "allow_deletion_env",
    "skip_tdd_check_env",
    "brain_path",
    "project_memory_path",
    # Trace-index knobs (v1.11.0+)
    "trace_embedding_model",
    "trace_index_path",
}

def validate(repo: Path | None = None) -> dict:
    """Validate the loaded config against KNOWN_KEYS + filesystem checks.

    Returns a dict with `ok` (bool), `errors` (list of str — block), and
    `warnings` (list of str — surface but not block). v1.12.0+."""
    out = {"ok": True, "errors": [], "warnings": [], "path": None}
    cp = config_path(repo)
    if cp is None:
        out["warnings"].append("no .kaizen.toml found in this repo (or any parent)")
        return out
    out["path"] = str(cp)

    cfg = load_config(repo)

    for key in cfg:
        if key not in KNOWN_KEYS:
            out["warnings"].append(f"unknown key {key!r} — typo? or future-version field?")

    # Filesystem checks for path-valued keys
    if cfg.get("backlog_path"):
        bp_abs = (repo or repo_root() or Path.cwd()) / cfg["backlog_path"]
        if not bp_abs.parent.exists():
            out["warnings"].append(
                f"backlog_path={cfg['backlog_path']!r} parent dir doesn't exist: {bp_abs.parent}")

    if cfg.get("compile_check_cmd"):
        first_word = cfg["compile_check_cmd"].split()[0] if cfg["compile_check_cmd"] else ""
        if first_word:
            import shutil as _sh
            if _sh.which(first_word) is None:
                out["warnings"].append(
                    f"compile_check_cmd starts with {first_word!r} but that's not on PATH")

    if cfg.get("brain_path"):
        bp = Path(str(cfg["brain_path"]).replace("~", str(Path.home())))
        if not bp.exists():
            out["warnings"].append(f"brain_path doesn't exist: {bp}")

    return out

def plugin_defaults_dict() -> dict:
    """Return the PLUGIN ▸ DEFAULTS section as a flat dict (v1.22.0+).

    Used by CLI `--defaults` and by other scripts that want to inspect
    the plugin's editable knobs without importing each constant by name."""
    return {
        "USER_DIR_NAME": USER_DIR_NAME,
        "USER_TRACE_NAME": USER_TRACE_NAME,
        "USER_KNOWLEDGE_NAME": USER_KNOWLEDGE_NAME,
        "USER_DAEMON_NAME": USER_DAEMON_NAME,
        "USER_INBOX_NAME": USER_INBOX_NAME,
        "USER_BACKUPS_NAME": USER_BACKUPS_NAME,
        "USER_SCHEMAS_NAME": USER_SCHEMAS_NAME,
        "PROJECT_KAIZEN_NAME": PROJECT_KAIZEN_NAME,
        "PROJECT_WORKFLOW_NAME": PROJECT_WORKFLOW_NAME,
        "EMBED_MODEL": EMBED_MODEL,
        "EMBED_DIM": EMBED_DIM,
        "ONBOARD_MAX_BYTES": ONBOARD_MAX_BYTES,
        "ONBOARD_SNIPPET_MAX": ONBOARD_SNIPPET_MAX,
        "KNOWLEDGE_SNIPPET_MAX": KNOWLEDGE_SNIPPET_MAX,
        "USER_SCRAPE_NAME": USER_SCRAPE_NAME,
        "USER_OBSERVE_NAME": USER_OBSERVE_NAME,
        "USER_BRAIN_NAME": USER_BRAIN_NAME,
        "USER_INDEXES_NAME": USER_INDEXES_NAME,
        "USER_DATA_NAME": USER_DATA_NAME,
        "USER_SNAPSHOTS_NAME": USER_SNAPSHOTS_NAME,
        "ARCHIVE_NAME": ARCHIVE_NAME,
        "USER_CLAUDE_DOCS_NAME": USER_CLAUDE_DOCS_NAME,
        "CLAUDE_DOCS_REPO_URL": CLAUDE_DOCS_REPO_URL,
        "INSTALL_LOG_NAME": INSTALL_LOG_NAME,
        "LEGACY_ARCHIVE_NAME": LEGACY_ARCHIVE_NAME,
        "SCRAPE_SNIPPET_MAX": SCRAPE_SNIPPET_MAX,
        "SCRAPE_LLM_MODEL": SCRAPE_LLM_MODEL,
        "SCRAPE_LLM_BASE_URL": SCRAPE_LLM_BASE_URL,
        "SCRAPE_LLM_AUTO": SCRAPE_LLM_AUTO,
        "SCRAPE_LLM_PROBE_TIMEOUT": SCRAPE_LLM_PROBE_TIMEOUT,
    }

def main():
    p = argparse.ArgumentParser(prog="config.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("key", nargs="?", default=None,
                   help="config key to look up (omit to list all)")
    p.add_argument("--default", default="",
                   help="fallback if key missing (default: empty string)")
    p.add_argument("--json", action="store_true",
                   help="print full config as JSON")
    p.add_argument("--path", action="store_true",
                   help="print the config file's absolute path (empty if not found)")
    p.add_argument("--validate", action="store_true",
                   help="check schema + filesystem; exit 1 on errors, 0 with warnings ok")
    p.add_argument("--defaults", action="store_true",
                   help="print the plugin-wide DEFAULTS (v1.22.0+) as JSON")
    args = p.parse_args()

    if args.defaults:
        _emit(plugin_defaults_dict())
        return

    if args.validate:
        v = validate()
        _emit(v,
              verdict="green" if not v["errors"] else "red",
              counts={"errors": len(v.get("errors", [])),
                      "warnings": len(v.get("warnings", []))})
        if v["errors"]:
            sys.exit(1)
        return

    if args.path:
        cp = config_path()
        print(cp if cp is not None else "")
        return

    if args.json:
        _emit(load_config())
        return

    if args.key is None:
        # List all key=value pairs
        cfg = load_config()
        for k in sorted(cfg.keys()):
            v = cfg[k]
            if isinstance(v, (dict, list)):
                continue  # skip nested for bash-callable shape
            print(f"{k}={v}")
        return

    print(get(args.key, args.default))

if __name__ == "__main__":
    main()
