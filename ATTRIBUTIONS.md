# Marketplace attributions

The `kaizen-md` marketplace bundles plugins from multiple upstreams. Each is redistributed under its original license with attribution.

## kaizen (MIT)

- **Author:** YugeIceCone — https://github.com/YugeIceCone
- **License:** MIT (© 2026 YugeIceCone)
- **Source:** `./plugins/kaizen` (this repo)
- **In-plugin attributions:** see `plugins/kaizen/ATTRIBUTIONS.md` for the full list of bundled skills (coding-skills, superpowers, onion-ddd-workflow, remember, tdd, workflow-routing, plugin-pitfalls, publishing, behaviour-config) and their original authors.

## pyright-lsp, typescript-lsp, rust-analyzer-lsp (Apache 2.0)

- **Author:** Anthropic — support@anthropic.com
- **License:** Apache 2.0 (see `plugins/<lsp-name>/LICENSE`)
- **Upstream:** https://github.com/anthropics/claude-plugins-official → `plugins/<lsp-name>/`
- **What's bundled:** the marketplace.json `lspServers` block (LSP command, args, extension→language mapping) plus the upstream README + LICENSE files. The LSP binaries themselves (`pyright-langserver`, `typescript-language-server`, `rust-analyzer`) are not vendored — users install those via their language tooling (`pip install pyright`, `npm install -g typescript-language-server`, `rustup component add rust-analyzer`).
- **Why redistribute:** consolidating into a single marketplace lets users get kaizen + the LSPs they actually use with one `/plugin marketplace add` invocation, instead of also subscribing to `claude-plugins-official` for the LSP set. The downstream wiring is identical to upstream.
- **Modifications:** none. The marketplace.json entries are byte-equivalent to upstream's. README + LICENSE files copied as-is.

## Upstream tracking

When `claude-plugins-official` updates an LSP plugin (e.g. new args, new extension mapping), refresh:

```bash
# 1. pull upstream marketplace
cd ~/.claude/plugins/marketplaces/claude-plugins-official && git pull

# 2. re-extract the 3 LSP entries
python3 -c "
import json
src = json.load(open('.claude-plugin/marketplace.json'))
for p in src['plugins']:
    if p['name'] in {'pyright-lsp','typescript-lsp','rust-analyzer-lsp'}:
        print(json.dumps(p, indent=2)); print('---')
"

# 3. update kaizen-md/.claude-plugin/marketplace.json with the new entries
# 4. cp upstream's plugins/<name>/{README.md,LICENSE} → kaizen-md/plugins/<name>/
```

(Or open a PR to claude-plugins-official directly if upstream fixes belong there.)
