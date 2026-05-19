---
name: trace-proxy
description: "Logging HTTP proxy wrapping CC → api.anthropic.com. Every LLM request/response (auth scrubbed) logged for replay/analysis."
argument-hint: [start|stop|status|log|fg]
---

# kaizen trace-proxy

!`bash ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-trace-proxy ${ARGUMENTS:-status}`
