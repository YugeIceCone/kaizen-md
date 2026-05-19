"""kaizen _ollama — minimal urllib-based client for the local Ollama
chat API (no pip dep). Single public function: `score_hint`.

Used by gold_mine (Phase 3) to ask granite4.1:8b "is this gold-worthy?"
with a structured-output JSON schema. Returns the parsed dict or None
(disabled / connection refused / malformed response / missing fields).

## Gating

  KAIZEN_GOLD_MINE_ENABLE=1   → make the call
  anything else                → return None (no network roundtrip)

## Endpoint

POSTs to `http://localhost:11434/api/chat` with:
  {
    "model":    "granite4.1:8b",
    "messages": [{"role": "system", ...}, {"role": "user", "content": hint}],
    "format":   <jsonschema dict>,
    "options":  {"temperature": 0},
    "stream":   false
  }

The response shape Ollama returns:
  {"message": {"content": "<jsonstring matching format>"}, ...}

We parse `message.content` as JSON, validate the required fields are
present, and return the dict. Any failure → None + one-line stderr.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Optional


OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "granite4.1:8b"
DEFAULT_TIMEOUT_S = 30.0


# Two few-shot examples — one positive (gold-worthy recurrent pattern),
# one negative (transient one-off). Burned into the system prompt to
# anchor the model.
_SYSTEM_PROMPT = """\
You judge whether a developer event is a "gold-worthy" pattern — a
durable learning worth recording for future reference. Reply with JSON
matching the requested schema.

Examples:

POSITIVE — gold-worthy:
  Input: "EVENT_TYPE: context.warn.red\\nRECURRENCE: 5\\n..."
  Output: {"gold_worthy": true, "confidence": 0.88,
           "pattern": "context.warn.red recurring 5x signals premature compaction",
           "tag": "context-mgmt",
           "reason": "recurrent pattern, actionable, points at a real failure mode"}

NEGATIVE — not gold-worthy:
  Input: "EVENT_TYPE: tool.use\\nRECURRENCE: 1\\n..."
  Output: {"gold_worthy": false, "confidence": 0.15,
           "pattern": "single tool.use event",
           "tag": "noise",
           "reason": "one-off, no recurring signal, nothing to learn"}
"""


def _enabled() -> bool:
    return os.environ.get("KAIZEN_GOLD_MINE_ENABLE", "") == "1"


def score_hint(
    hint: str,
    *,
    model: str = DEFAULT_MODEL,
    schema: dict,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> Optional[dict]:
    """Ask Ollama to score `hint` and return the parsed structured
    response. Returns None on any failure (disabled, network, parse,
    schema-violation). Never raises.
    """
    if not _enabled():
        return None

    body = {
        "model":    model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": hint},
        ],
        "format":   schema,
        "options":  {"temperature": 0},
        "stream":   False,
    }

    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as e:
        sys.stderr.write(f"gold-mine: ollama call failed ({e})\n")
        return None

    try:
        wire = json.loads(raw)
        content = wire.get("message", {}).get("content", "")
        parsed = json.loads(content)
    except (json.JSONDecodeError, AttributeError):
        return None

    if not isinstance(parsed, dict):
        return None

    # Lightweight schema validation: required keys present.
    required = (schema or {}).get("required", []) or []
    if not all(k in parsed for k in required):
        return None

    return parsed


__all__ = ["score_hint", "OLLAMA_URL", "DEFAULT_MODEL"]
