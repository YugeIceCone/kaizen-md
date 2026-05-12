---
name: trace-proxy
description: Wrap the Claude Code → api.anthropic.com connection in a logging HTTP proxy. Every LLM request/response (auth scrubbed) flows into kaizen-trace as src=llm with model, message count, input/output tokens, latency. Stdlib-only, opt-in. Subcommands: start | stop | status | log | fg.
argument-hint: [start|stop|status|log|fg]
---

# kaizen trace-proxy

!`bash ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-trace-proxy ${ARGUMENTS:-status}`
