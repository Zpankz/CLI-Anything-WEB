# cli-web-deepwiki

> Agent-native CLI for DeepWiki — search, fetch, parse, and convert AI-generated
> wikis into Obsidian vaults via the unified.js ecosystem.

`cli-web-deepwiki` exposes [DeepWiki's](https://deepwiki.com/) underlying
Devin Ada API for programmatic search and Q&A, fetches the SSR Markdown
content of every indexed page, and pipes it through the
[`unified`](https://github.com/unifiedjs/unified) ecosystem (defuddle →
rehype → remark → retext) so that wikis can be consumed, transformed, and
republished by agents at native fidelity.

## Architecture

```
                ┌────────────────────────┐
                │  Python CLI (this pkg) │
                │  click + httpx + rich  │
                └────────┬───────┬───────┘
                         │       │
              ┌──────────┘       └──────────┐
              ▼                              ▼
     ┌───────────────────┐         ┌─────────────────────┐
     │  Devin Ada API    │         │  Node sidecar       │
     │  api.devin.ai/ada │         │  unified_engine/    │
     │  search · ask     │         │  defuddle · remark  │
     │                   │         │  rehype · retext    │
     └───────────────────┘         │  zod2md · LSP       │
                                   └─────────────────────┘
```

The sidecar is a long-lived Node process that the Python CLI talks to via
line-delimited JSON-RPC over stdio. All Markdown/HTML transformations happen
authoritatively inside the unified ecosystem — no Python re-implementations.

## Installation

```bash
# 1. Install Python package
pip install cli-web-deepwiki

# 2. Install Node sidecar dependencies (requires Node 18+)
cli-web-deepwiki-install-engine
```

For development:

```bash
cd cli-web-deepwiki/agent-harness
pip install -e '.[dev]'
cli-web-deepwiki-install-engine
```

## Usage

### Discovery

```bash
cli-web-deepwiki search                              # all indexed repos (top 25)
cli-web-deepwiki search rust --limit 50              # repos matching "rust"
cli-web-deepwiki repo agenticnotetaking/arscontexta  # one repo overview
cli-web-deepwiki wiki agenticnotetaking/arscontexta  # full wiki TOC
```

### Pages and Q&A

```bash
# Single page as Markdown
cli-web-deepwiki page agenticnotetaking/arscontexta/3.2-the-15-kernel-primitives -m

# Ask Devin a question (Fast mode)
cli-web-deepwiki ask agenticnotetaking/arscontexta "What are the kernel primitives?"

# Research mode (slower, deeper)
cli-web-deepwiki ask agenticnotetaking/arscontexta "Explain the 6 Rs workflow" --mode research
```

### Obsidian vault generation

```bash
cli-web-deepwiki vault agenticnotetaking/arscontexta --output ./vault \
    --canvas --mocs --frontmatter
```

This produces:

```
vault/
├── .obsidian/app.json                # newLinkFormat: shortest
├── index.md                           # top-level Map of Content
├── 1-overview.md
├── 2-plugin-infrastructure.md
├── 3-core-concepts.md
├── 3.1-research-foundation.md         # …with [[wikilinks]] cross-refs
├── …
└── _graph.canvas                      # JSON Canvas backlink graph
```

### Pipeline subcommands (work on any HTML/MD)

```bash
cli-web-deepwiki extract https://example.com/article.html         # defuddle clean MD
cli-web-deepwiki parse path.html --target mdast                   # JSON AST
cli-web-deepwiki normalize draft.md --ofm                         # canonical OFM
cli-web-deepwiki query draft.md --select heading                  # all headings
cli-web-deepwiki convert input.html --from html --to nlcst        # cross-format
cli-web-deepwiki analyze draft.md --metrics readability           # retext stats
cli-web-deepwiki graph owner/repo --format mermaid                # wiki graph
```

### Editor integration via LSP

```bash
cli-web-deepwiki lsp --stdio
```

Configure your editor to launch this as a Markdown language server. It
runs the same remark/rehype/retext pipeline as the CLI, giving live
diagnostics, completions, and citations.

### REPL

```bash
cli-web-deepwiki      # no subcommand → REPL
> ask agenticnotetaking/arscontexta "What is arscontexta?"
> wiki agenticnotetaking/arscontexta
> exit
```

### JSON output

Every command supports `--json` for agent consumption:

```bash
cli-web-deepwiki search rust --json
cli-web-deepwiki page owner/repo/1-overview -m --json | jq '.markdown'
```

## API contract

See [`DEEPWIKI.md`](./DEEPWIKI.md) for the full API map (endpoints, request/response
schemas, polling semantics, and the JSON-RPC contract between Python and the
Node sidecar).

## License

MIT
