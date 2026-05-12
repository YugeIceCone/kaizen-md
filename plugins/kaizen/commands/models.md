---
name: models
description: Ollama-backed local model management — list, pull, show, delete, copy, plus embed/chat smoke tests with full capability surface (streaming, thinking, structured outputs, vision) and `pin-embed` / `pin-chat` to bridge Ollama models into kaizen's profile.env. Replaces manual `ollama` CLI invocations + manual env-var edits for the kaizen embed/chat surfaces. Requires Ollama running at `:11434` (or `KAIZEN_OLLAMA_HOST` / `OLLAMA_HOST`). The `ollama` Python client is installed on-demand via `uv run --script` (PEP 723).
argument-hint: [list|pull <m>|show <m>|delete <m>|copy <src> <dst>|embed-test <m>|chat-test <m>|pin-embed <m>|pin-chat <m>]
---

# kaizen models

!`bash ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-models $ARGUMENTS`
