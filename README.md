# kaizen-md

[![test](https://github.com/YugeIceCone/kaizen-md/actions/workflows/test.yml/badge.svg)](https://github.com/YugeIceCone/kaizen-md/actions/workflows/test.yml)

A Claude Code [plugin marketplace](https://docs.claude.com/en/docs/claude-code/plugins) bundling **kaizen** (commit discipline + Second Brain + workflow tooling) plus 13 vendored language servers.

## Install the marketplace

```bash
/plugin marketplace add YugeIceCone/kaizen-md
```

## Plugins

### kaizen — [`plugins/kaizen/`](./plugins/kaizen/README.md)

Pre-commit gate, JSON-sourced backlog, Second Brain (Persona / PARA / Notes), 49 skills, 22 MCP servers, 18 lifecycle hooks, 6 sub-agents. MIT license.

```bash
/plugin install kaizen@kaizen-md
```

See [`plugins/kaizen/README.md`](./plugins/kaizen/README.md) for the full surface (skills, commands, MCP servers, configuration).

### LSP plugins — `plugins/*-lsp/`

13 language servers redistributed verbatim from [claude-plugins-official](https://github.com/anthropics/claude-plugins-official) under Apache 2.0. See [`ATTRIBUTIONS.md`](./ATTRIBUTIONS.md).

| Plugin | Language | Server |
|---|---|---|
| `pyright-lsp` | Python | Pyright |
| `typescript-lsp` | TypeScript/JavaScript | typescript-language-server |
| `rust-analyzer-lsp` | Rust | rust-analyzer |
| `clangd-lsp` | C/C++ | clangd |
| `csharp-lsp` | C# | csharp-ls |
| `gopls-lsp` | Go | gopls |
| `jdtls-lsp` | Java | Eclipse JDT.LS |
| `kotlin-lsp` | Kotlin | kotlin-lsp |
| `lua-lsp` | Lua | lua-language-server |
| `php-lsp` | PHP | Intelephense |
| `ruby-lsp` | Ruby | ruby-lsp |
| `swift-lsp` | Swift | SourceKit-LSP |

Install any LSP plugin with `/plugin install <name>@kaizen-md`.

## Layout

```
.claude-plugin/marketplace.json   # marketplace manifest (14 plugins)
plugins/kaizen/                   # the only plugin-original code
plugins/*-lsp/                    # vendored from claude-plugins-official
ATTRIBUTIONS.md                   # upstream credits
LICENSE                           # MIT (marketplace + kaizen plugin)
```

## Contributing

All plugin development happens in [`plugins/kaizen/`](./plugins/kaizen/). The LSP plugins are vendored — patch upstream, then refresh. See [`plugins/kaizen/CONTRIBUTING.md`](./plugins/kaizen/CONTRIBUTING.md) and the project [`CLAUDE.md`](./CLAUDE.md).

## License

MIT for the marketplace and the `kaizen` plugin. Apache 2.0 for vendored LSP plugins (see [`ATTRIBUTIONS.md`](./ATTRIBUTIONS.md)).
