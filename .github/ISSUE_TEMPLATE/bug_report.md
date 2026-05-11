---
name: Bug report
about: A check produces a wrong verdict, a hook output is malformed, or a script crashes.
labels: bug
---

## What happened
<!-- One sentence. What did you expect vs. what did you get? -->

## Reproduction
<!-- Minimal repro — preferably commands run in /tmp/* sandbox. -->

```bash
mkdir /tmp/repro && cd /tmp/repro
git init -q
# steps...
```

## Environment

- **OS:** (Linux / macOS / WSL)
- **Bash version:** `bash --version | head -1`
- **Python version:** `python3 --version`
- **Plugin commit:** `cd $CLAUDE_PLUGIN_ROOT && git rev-parse --short HEAD`
- **`/kaizen:doctor` output:** (paste relevant section)

## Expected behavior
<!-- What should happen instead? Reference SKILL.md or CHANGELOG.md if applicable. -->

## Logs / output
<!-- Paste failing test output, stderr, or `bash -x` trace if relevant. Keep it focused — token-efficient diagnosis. -->
