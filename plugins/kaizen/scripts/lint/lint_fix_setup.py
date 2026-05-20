"""lint_fix_setup — detect + offer-to-install a local OpenAI-compatible
LLM server for the dispatcher's `strategy='local_llm'` path.

  detect_servers() → list[dict]
      Sweep candidate URLs (LLM_BASE_URL env + ollama:11434 +
      llama-server:8080) and return the reachable ones. Each entry:
      {url, kind, models, reachable}.

  generate_install_script(target: 'ollama' | 'llama-server') → str
      Returns a self-contained bash script. Does NOT execute it.

  start_ollama_if_idle() → dict
      No-op if an ollama instance is already responding. Otherwise
      spawns `ollama serve` in the background when the binary exists.
      When the binary is missing, returns the install script.

  setup_summary() → dict
      Top-level orchestrator. {status, recommended_url, recommended_model,
      install_script?, setup_command?}.

Pure boundary code — no LLM calls, no model downloads done at import
time.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent

# Default coder model for the dispatcher — small + fast + good at diffs.
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:1.5b"

# Sweep order: env-configured first, then the two common conventions.
_CANDIDATE_PORTS: tuple[tuple[int, str], ...] = (
    (11434, "ollama"),          # default ollama
    (8080,  "llama-server"),    # default llama.cpp
)

# ───────────────────────────────────────────────────────────────────────
# Probe — low-level GET /v1/models with a tight timeout
# ───────────────────────────────────────────────────────────────────────

_ALLOWED_SCHEMES = frozenset({"http", "https"})

def _probe(base_url: str, timeout: float = 1.0) -> dict | None:
    """Return /v1/models JSON if reachable, else None. Never raises.

    SEC-4: explicit scheme allowlist. urlopen honors `file://` /
    `ftp://` / `gopher://`; a malicious LLM_BASE_URL=file:///etc/passwd
    would turn this probe into an arbitrary-file-read primitive.
    Incidentally, the socket.create_connection step would reject
    schemeless URLs today — but defense-in-depth says don't rely on
    that accident."""
    parsed = urlparse(base_url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return None
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    # Cheap TCP probe first so we don't wait for HTTP timeouts on dead ports
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except (TimeoutError, OSError):
        return None
    url = base_url.rstrip("/") + "/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:    # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError,
             json.JSONDecodeError):
        return None

def _which(name: str) -> str | None:
    """Wrap shutil.which so tests can monkeypatch this single symbol."""
    return shutil.which(name)

def _spawn_background(cmd: list[str]) -> int:
    """Detached background spawn — Popen + start_new_session. Returns pid."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid

# ───────────────────────────────────────────────────────────────────────
# detect_servers — sweep
# ───────────────────────────────────────────────────────────────────────

def _candidate_urls() -> list[tuple[str, str]]:
    """Return [(url, kind)] in scan order — env first, then conventions."""
    out: list[tuple[str, str]] = []
    env_url = os.environ.get("LLM_BASE_URL")
    if env_url:
        out.append((env_url, "env"))
    for port, kind in _CANDIDATE_PORTS:
        url = f"http://127.0.0.1:{port}"
        if (url, "env") in out:
            continue
        out.append((url, kind))
    return out

def detect_servers() -> list[dict[str, Any]]:
    reachable: list[dict[str, Any]] = []
    for url, kind in _candidate_urls():
        body = _probe(url)
        if body is None:
            continue
        models = body.get("data", []) if isinstance(body, dict) else []
        reachable.append({
            "url": url,
            "kind": kind,
            "models": models,
            "reachable": True,
        })
    return reachable

# ───────────────────────────────────────────────────────────────────────
# generate_install_script
# ───────────────────────────────────────────────────────────────────────

_OLLAMA_SCRIPT = f"""#!/usr/bin/env bash
# kaizen lint_fix — install + warm Ollama with a small coder model.
# Idempotent: re-running is safe.
set -euo pipefail

MODEL="{DEFAULT_OLLAMA_MODEL}"
LOG="/tmp/kaizen-ollama-setup.log"
: > "$LOG"

# Detect TTY so we either keep ollama's spinner (interactive) or strip
# the alt-screen / cursor-hide / move-to-column escape sequences (CLI
# tools, pipes, IDE bash tools). Strips: ESC[?…h ESC[?…l ESC[A ESC[K
# ESC[<n>G — i.e. ollama's redraw codes.
strip_tty() {{
  if [ -t 1 ]; then
    cat
  else
    sed -E -u 's/\\x1b\\[\\?[0-9;]*[hl]//g; s/\\x1b\\[[0-9]*[ABCDGKJ]//g'
  fi
}}

step() {{ printf "\\n\\033[1m▸ %s\\033[0m\\n" "$1"; }}

step "install ollama (if missing)"
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi

step "start ollama serve (if idle)"
if ! curl -fsS --max-time 1 http://127.0.0.1:11434/v1/models >/dev/null 2>&1; then
  nohup ollama serve >/tmp/kaizen-ollama.log 2>&1 &
  for _ in $(seq 1 20); do
    sleep 0.5
    curl -fsS --max-time 0.5 http://127.0.0.1:11434/v1/models >/dev/null 2>&1 && break
  done
fi

step "pull $MODEL (~600MB — first run only)"
# Pipe through strip_tty so the dispatcher's persisted output doesn't
# balloon to 100KB+ of cursor-hide spam.
OLLAMA_NOPROGRESS=1 ollama pull "$MODEL" 2>&1 | strip_tty | tee -a "$LOG" || {{
  echo "  (full log: $LOG)" >&2
  exit 1
}}

step "verify"
RESP="$(curl -fsS --max-time 3 http://127.0.0.1:11434/v1/models || true)"
if echo "$RESP" | grep -q "$MODEL"; then
  STATUS="✓ ready"
else
  STATUS="✗ pull succeeded but $MODEL not visible in /v1/models — see $LOG"
fi

cat <<EOF

═══════════════════════════════════════════════════════════════════
  Ollama local LLM — $STATUS
═══════════════════════════════════════════════════════════════════

  URL        http://127.0.0.1:11434
  Model      $MODEL
  Endpoint   /v1/models (OpenAI-compatible)

  Export for this shell (or add to ~/.bashrc):

    export LLM_BASE_URL=http://127.0.0.1:11434
    export LLM_MODEL=$MODEL

  Use from Claude (via kaizen MCP):

    auto_fix_lint(path="src/", strategy="local_llm",
                   apply=True, remember_choice=True)

  Verify by hand:

    curl http://127.0.0.1:11434/v1/models

  Logs:

    $LOG
    /tmp/kaizen-ollama.log   # if ollama serve was started by this script
EOF
"""

_LLAMA_SERVER_SCRIPT = """#!/usr/bin/env bash
# kaizen lint_fix — bootstrap llama.cpp's llama-server (heavier path).
# Prefers homebrew on macOS, falls back to building from source.
set -euo pipefail

if ! command -v llama-server >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "[kaizen-llm-setup] installing llama.cpp via brew..."
    brew install llama.cpp
  else
    echo "[kaizen-llm-setup] llama-server not found and no brew available."
    echo "Build manually: https://github.com/ggerganov/llama.cpp"
    exit 1
  fi
fi

echo "[kaizen-llm-setup] llama-server installed. Start manually with:"
echo "  llama-server -m <path-to.gguf> --host 127.0.0.1 --port 8080"
echo "Then export:"
echo "  export LLM_BASE_URL=http://127.0.0.1:8080"
"""

def generate_install_script(target: str) -> str:
    if target == "ollama":
        return _OLLAMA_SCRIPT
    if target == "llama-server":
        return _LLAMA_SERVER_SCRIPT
    raise ValueError(f"unknown target {target!r}; must be 'ollama' or 'llama-server'")

# ───────────────────────────────────────────────────────────────────────
# start_ollama_if_idle — opportunistic boot
# ───────────────────────────────────────────────────────────────────────

def start_ollama_if_idle() -> dict[str, Any]:
    if detect_servers():
        return {"status": "already_running"}
    ollama = _which("ollama")
    if not ollama:
        return {
            "status": "not_installed",
            "install_script": generate_install_script("ollama"),
        }
    pid = _spawn_background([ollama, "serve"])
    return {"status": "started", "pid": pid}

# ───────────────────────────────────────────────────────────────────────
# setup_summary — top-level orchestrator
# ───────────────────────────────────────────────────────────────────────

_SETUP_COMMAND = (
    "bash " + str(SCRIPT_DIR / "setup-local-llm.sh")
    + "   # or: bash <(cat) <<< \"$(python3 -m lint_fix_setup --print-script)\""
)

def setup_summary() -> dict[str, Any]:
    servers = detect_servers()
    if servers:
        first = servers[0]
        recommended_model = ""
        if first.get("models"):
            recommended_model = first["models"][0].get("id", "")
        return {
            "status": "ready",
            "recommended_url": first["url"],
            "recommended_model": recommended_model,
            "servers": servers,
        }
    return {
        "status": "setup_needed",
        "install_script": generate_install_script("ollama"),
        "setup_command": _SETUP_COMMAND,
        "default_model": DEFAULT_OLLAMA_MODEL,
        "default_url": "http://127.0.0.1:11434",
    }

__all__ = [
    "detect_servers", "generate_install_script", "start_ollama_if_idle",
    "setup_summary", "DEFAULT_OLLAMA_MODEL",
]

# Tiny CLI: `python3 lint_fix_setup.py --print-script` prints the bash
# script so users can pipe it into `bash`. No interactive flow.
if __name__ == "__main__":
    import sys
    if "--print-script" in sys.argv:
        target = "ollama"
        if "--target" in sys.argv:
            i = sys.argv.index("--target")
            target = sys.argv[i + 1] if i + 1 < len(sys.argv) else "ollama"
        print(generate_install_script(target))
        sys.exit(0)
    print(json.dumps(setup_summary(), indent=2, default=str))
