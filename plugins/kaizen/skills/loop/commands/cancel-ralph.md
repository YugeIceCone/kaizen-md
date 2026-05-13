---
description: "Cancel active Ralph Loop"
allowed-tools: ["Bash(test -f .kaizen/loop.state.md:*)", "Bash(rm .kaizen/loop.state.md)", "Read(.kaizen/loop.state.md)"]
hide-from-slash-command-tool: "true"
---

# Cancel Ralph

To cancel the Ralph loop:

1. Check if `.kaizen/loop.state.md` exists using Bash: `test -f .kaizen/loop.state.md && echo "EXISTS" || echo "NOT_FOUND"`

2. **If NOT_FOUND**: Say "No active Ralph loop found."

3. **If EXISTS**:
   - Read `.kaizen/loop.state.md` to get the current iteration number from the `iteration:` field
   - Remove the file using Bash: `rm .kaizen/loop.state.md`
   - Report: "Cancelled Ralph loop (was at iteration N)" where N is the iteration value
