# Marketplace attributions

The `kaizen-md` marketplace bundles plugins from multiple upstreams. Each is redistributed under its original license with attribution.

## kaizen (MIT)

- **Author:** YugeIceCone — https://github.com/YugeIceCone
- **License:** MIT (© 2026 YugeIceCone)
- **Source:** `./plugins/kaizen` (this repo)
- **In-plugin attributions:** see `plugins/kaizen/ATTRIBUTIONS.md` for the full list of bundled skills (coding-skills, superpowers, onion-ddd-workflow, remember, tdd, workflow-routing, plugin-pitfalls, publishing, behaviour-config) and their original authors.

## LSP plugins (Apache 2.0) — 12 language servers

`clangd-lsp`, `csharp-lsp`, `gopls-lsp`, `jdtls-lsp`, `kotlin-lsp`, `lua-lsp`, `php-lsp`, `pyright-lsp`, `ruby-lsp`, `rust-analyzer-lsp`, `swift-lsp`, `typescript-lsp`

- **Plugin author:** Anthropic — support@anthropic.com
- **Plugin license:** Apache 2.0 (see `plugins/<lsp-name>/LICENSE`)
- **Plugin source:** https://github.com/anthropics/claude-plugins-official → `plugins/<lsp-name>/`
- **What's bundled:** the marketplace.json `lspServers` block (LSP command, args, extension→language mapping) plus the upstream README + LICENSE files. The LSP binaries themselves are not vendored — users install those via their language tooling (`pip install pyright`, `rustup component add rust-analyzer`, etc.).
- **Why redistribute:** consolidating into a single marketplace lets users get kaizen + the LSPs they actually use with one `/plugin marketplace add` invocation, instead of also subscribing to `claude-plugins-official` for the LSP set. The downstream wiring is identical to upstream.
- **Modifications:** none. The marketplace.json entries are byte-equivalent to upstream's. README + LICENSE files copied as-is.

### Upstream language-server binaries — credits to the projects that built them

Each `*-lsp` plugin spawns an upstream binary. The plugin manifest is
Anthropic-authored (Apache-2.0); the binary itself is a separately
licensed third-party project. Credit + license for each:

| Plugin | Binary | Upstream project | License |
|---|---|---|---|
| `clangd-lsp` | `clangd` | [llvm/llvm-project — clang-tools-extra/clangd](https://github.com/llvm/llvm-project/tree/main/clang-tools-extra/clangd) | Apache-2.0 WITH LLVM-exception |
| `csharp-lsp` | `csharp-ls` | [razzmatazz/csharp-language-server](https://github.com/razzmatazz/csharp-language-server) | MIT |
| `gopls-lsp` | `gopls` | [golang/tools — gopls](https://github.com/golang/tools/tree/master/gopls) | BSD-3-Clause |
| `jdtls-lsp` | `jdtls` | [eclipse-jdtls/eclipse.jdt.ls](https://github.com/eclipse-jdtls/eclipse.jdt.ls) | EPL-2.0 |
| `kotlin-lsp` | `kotlin-lsp` | [Kotlin/kotlin-lsp](https://github.com/Kotlin/kotlin-lsp) — JetBrains | Apache-2.0 |
| `lua-lsp` | `lua-language-server` | [LuaLS/lua-language-server](https://github.com/LuaLS/lua-language-server) | MIT |
| `php-lsp` | `intelephense` | [Intelephense](https://intelephense.com/) | **Proprietary / freemium** ⚠ — premium features require a paid license. Open-source alternatives include [Phpactor](https://github.com/phpactor/phpactor) (MIT) and [PHPStan](https://phpstan.org/) used out-of-process. |
| `pyright-lsp` | `pyright-langserver` | [microsoft/pyright](https://github.com/microsoft/pyright) — Microsoft | MIT |
| `ruby-lsp` | `ruby-lsp` | [Shopify/ruby-lsp](https://github.com/Shopify/ruby-lsp) | MIT |
| `rust-analyzer-lsp` | `rust-analyzer` | [rust-lang/rust-analyzer](https://github.com/rust-lang/rust-analyzer) | MIT OR Apache-2.0 (dual) |
| `swift-lsp` | `sourcekit-lsp` | [swiftlang/sourcekit-lsp](https://github.com/swiftlang/sourcekit-lsp) | Apache-2.0 with Runtime Library Exception |
| `typescript-lsp` | `typescript-language-server` | [typescript-language-server/typescript-language-server](https://github.com/typescript-language-server/typescript-language-server) | Apache-2.0 |

The Anthropic-authored plugin manifest only wraps these binaries — it
doesn't redistribute them. Users install the binaries themselves per
each LSP plugin's README. Full license text accompanies each
distribution channel (rustup, brew, npm, apt, etc.) per the upstream
project's release policy.

## Upstream tracking

When `claude-plugins-official` updates an LSP plugin (e.g. new args, new extension mapping), refresh:

```bash
# 1. pull upstream marketplace
cd ~/.claude/plugins/marketplaces/claude-plugins-official && git pull

# 2. re-extract LSP entries (replace the wanted set as needed)
python3 -c "
import json
src = json.load(open('.claude-plugin/marketplace.json'))
for p in src['plugins']:
    if p['name'].endswith('-lsp'):
        print(json.dumps(p, indent=2)); print('---')
"

# 3. update kaizen-md/.claude-plugin/marketplace.json with the new entries
# 4. cp upstream's plugins/<name>/{README.md,LICENSE} → kaizen-md/plugins/<name>/
```

(Or open a PR to claude-plugins-official directly if upstream fixes belong there.)
