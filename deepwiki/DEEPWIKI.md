# DEEPWIKI — Agent-Native CLI Reference

`cli-web-deepwiki` is a Python+Node hybrid CLI that turns DeepWiki into a programmable
data source. It calls Devin's underlying Ada API for repo discovery and Q&A, and
fetches DeepWiki SSR HTML for wiki content, then pipes it through the unified.js
ecosystem (defuddle → rehype → remark → retext) for clean Markdown extraction,
Obsidian vault generation, and structured analysis.

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  cli-web-deepwiki (Python — entry point)                       │
│  ├── core/                                                     │
│  │   ├── client.py        Devin Ada API + DeepWiki HTML        │
│  │   ├── models.py        Repo, WikiTree, Page, Answer         │
│  │   ├── exceptions.py    DeepwikiError hierarchy              │
│  │   └── session.py       devin_client_uuid persistence        │
│  ├── commands/            one file per resource                │
│  │   ├── search.py  repo.py  wiki.py  page.py  ask.py          │
│  │   ├── parse.py   normalize.py  query.py  convert.py         │
│  │   ├── extract.py vault.py graph.py  analyze.py  lsp.py      │
│  └── utils/                                                    │
│      ├── unified_bridge.py   stdio JSON-RPC to Node sidecar    │
│      ├── output.py           Rich tables + JSON                │
│      └── helpers.py          handle_errors, _resolve_cli       │
│                                                                │
│         ▲ stdin/stdout JSON-RPC ▼                              │
│                                                                │
│  unified_engine/ (Node.js — sidecar)                           │
│  ├── server.js            Line-delimited JSON-RPC dispatcher   │
│  ├── pipelines/                                                │
│  │   ├── htmlToMd.js      defuddle + rehype-remark             │
│  │   ├── htmlToMdast.js   rehype-parse → rehype-remark-tree    │
│  │   ├── mdToOfm.js       remark + frontmatter + gfm-as-OFM    │
│  │   │                    + math + directive + wikilinks       │
│  │   ├── mdToNlcst.js     retext-english + retext-pos          │
│  │   ├── astQuery.js      unist-util-visit + select            │
│  │   └── astConvert.js    HTML/MD/XML/NLCST round-trips        │
│  ├── plugins/                                                  │
│  │   ├── remark-deepwiki-wikilinks.js   /a/b/slug → [[slug]]   │
│  │   ├── remark-deepwiki-sources.js     "Sources:" → frontmatter│
│  │   └── remark-deepwiki-mocs.js        Build Maps of Content  │
│  ├── schemas/                                                  │
│  │   └── *.zod.ts         Zod schemas (zod2md target)          │
│  └── package.json                                              │
└────────────────────────────────────────────────────────────────┘
```

## Two Authentic Backends

### Devin Ada API (`api.devin.ai/ada/*`) — discovery + Q&A

| Endpoint | Method | Body / Query | Returns |
|----------|--------|--------------|---------|
| `/ada/list_public_indexes?search_repo={q}` | GET | (none) | `{indices: Index[], needs_reindex: [], pending_repos: []}` |
| `/ada/query` | POST | see schema below | `{status: "success"}` (sync ack) |
| `/ada/query/{query_id}` | GET | (none) | `{title, queries: Query[], org_id}` (poll until `state == "done"`) |

CORS: `Access-Control-Allow-Origin: https://deepwiki.com`. The CLI sets:

```
Origin: https://deepwiki.com
Referer: https://deepwiki.com/
User-Agent: cli-web-deepwiki/0.1.0 (compatible; Mozilla/5.0)
```

#### Query POST body (verified against live API)

```jsonc
{
  "query_id": "{slug}_{uuid4}",                      // client-generated; slug = first 30 chars of question kebab-cased
  "user_query": "What are the kernel primitives?",
  "additional_context": "",                          // optional preamble (e.g. wiki page Overview)
  "repo_names": ["agenticnotetaking/arscontexta"],
  "repo_context_ids": ["v1.9.9.5/PUBLIC/agenticnotetaking/arscontexta/2acfd5cc"],
  "engine_id": "multihop_faster"                     // "multihop_faster"=Fast, "deep_research"=Research
}
```

#### Query GET response (steady state)

`queries[0]` is the answer object. `state` cycles `pending → running → done`.
`response[]` is a flat ordered stream of typed message blocks — concatenate all
`{type: "chunk", data: "..."}` to reconstruct the answer Markdown. References
appear inline as `{type: "reference", data: {file_path, range_start, range_end}}`
and resolve to `https://github.com/{owner}/{repo}/blob/{commit}/{path}?plain=1#L{a}-L{b}`.

#### Index ID format

`v{api_version}/PUBLIC/{owner}/{repo}/{short_commit_sha}` — the `short_commit_sha`
is the commit DeepWiki indexed against. Pass the full ID in `repo_context_ids[]`.

### DeepWiki SSR HTML (`deepwiki.com/{owner}/{repo}[/{slug}]`) — wiki content

| Path | Returns | Use |
|------|---------|-----|
| `/{owner}/{repo}` | text/html (full page) | Repo overview + sidebar TOC |
| `/{owner}/{repo}/{slug}` | text/html (full page) | Individual wiki page |
| `/{owner}/{repo}?_rsc={token}` | text/x-component | RSC payload (skip — harder to parse) |

Strategy: GET the HTML directly (omit `_rsc` query) and pipe to defuddle, then
rehype-remark for canonical Markdown.

## Command Surface

### Discovery / data
- `search [QUERY] [--limit N] [--lang L]` → list repos via Ada
- `repo <owner>/<repo>` → full Index metadata + last_indexed commit
- `wiki <owner>/<repo>` → wiki TOC (alias for `wiki tree …`)
- `wiki tree <owner>/<repo>` → sidebar TOC
- `wiki best-practices` → print Devin's documented authoring guidance
- `wiki config validate <path>` → validate `.devin/wiki.json` against schema and limits
  (max 30 pages public / 80 enterprise, 100 total notes, 10k chars per note,
  unique titles, parent refs resolve)
- `wiki config scaffold <owner>/<repo> [--out PATH]` → generate a starter
  `.devin/wiki.json` from the existing TOC for the repo owner to refine
- `page <owner>/<repo>/<slug>` → fetch one page as Markdown
- `ask <owner>/<repo> <question> [--mode MODE] [--context PAGE] [--follow-up QID | --continue]
  [--show-thoughts] [--show-tool-calls] [--list-modes] [--no-wait]` →
  Q&A. Modes resolved via `resolve_engine`:
  - `fast` → `multihop_faster` (default; ~3-8s)
  - `research` / `deep` → `multihop` (~15-30s, multi-hop reasoning)
  - `codemap` → `codemap` (returns structured JSON architecture trace)
  - `agent` / `omni` / `planning` → specialized agents (emit thoughts + tool_calls;
    use `--show-thoughts` to surface reasoning)
  Follow-ups: re-POST the same `query_id` with a new `user_query`. The CLI
  persists the most recent `query_id` in session.json so `--continue` works
  on the next invocation.

### Pipeline / unified
- `parse <html|url> [--target hast|mdast|xast|nlcst]` → AST as JSON
- `normalize <md_path> [--ofm]` → canonical formatting via remark
- `query <md_path> --select '<query>'` → unist-util-select queries (`heading`, `link`, `code`, `inlineCode`, etc.)
- `convert <input> --from <fmt> --to <fmt>` → HTML/MD/JSON/XML/NLCST round-trips
- `extract <url> [--readability]` → defuddle → cleaned MD
- `analyze <md_path>` → retext stats: readability, sentence length, entities

### Vault / aggregation
- `vault <owner>/<repo> --output ./vault [--canvas] [--mocs] [--frontmatter]` →
  generate Obsidian vault: every page as `.md` with YAML frontmatter,
  cross-page links rewritten as `[[wikilinks]]`, `index.md` MOC, optional
  `_graph.canvas` JSON Canvas backlink graph
- `graph <owner>/<repo> [--format mermaid|canvas|json]` → wiki structure as graph

### LSP
- `lsp [--stdio | --tcp PORT]` → start unified-language-server with the project's
  remark/rehype/retext plugins so editors get diagnostics, hover, completion

### Auth / context (optional persistence of devin_client_uuid)
- `auth status` / `auth reset` / `use <owner>/<repo>` / `status`

## Polling

`ask` and any future generation commands use exponential backoff:
2s → 3s → 4.5s → 6.75s → 10s, factor 1.5, timeout 300s. On `429` (none observed
during capture), retry chain: 60s → 90s → 135s → 200s → 300s.

## Hybrid Stdio Bridge

Python invokes Node sidecar as a long-lived child process, sending one JSON
request per line:

```
> {"id":"1","method":"htmlToMd","params":{"html":"<...>","options":{...}}}
< {"id":"1","ok":true,"data":{"markdown":"...","metadata":{...}}}
```

Methods:
- `htmlToMd(html, options)` → `{markdown, title, metadata}`
- `htmlToMdast(html)` → `{tree}` (mdast JSON)
- `mdToOfm(markdown, options)` → `{markdown}` (canonical OFM)
- `mdToNlcst(markdown)` → `{tree}` (nlcst JSON)
- `astQuery(tree, type, selector)` → `{matches: []}`
- `astConvert(input, from, to)` → `{output}`
- `vaultPage(html, ctx)` → `{markdown, frontmatter, links}` — single-page vault transform
- `vaultMoc(pages)` → `{markdown}` — Map of Content
- `vaultCanvas(pages)` → `{canvas}` — JSON Canvas backlink graph
- `lsp(action)` → starts/stops unified-language-server

## Citations

Devin's `reference` blocks resolve to `github.com/{owner}/{repo}/blob/{commit}/{path}?plain=1#L{start}-L{end}`.
The CLI emits these as Markdown links: `[file.md:200-220](https://github.com/.../blob/...#L200-L220)`.

## Frontmatter Schema (vault output)

```yaml
---
title: The 15 Kernel Primitives
slug: 3.2-the-15-kernel-primitives
repo: agenticnotetaking/arscontexta
indexed_at: 2026-03-14T11:01:38Z
indexed_commit: 2acfd5cc
sources:
  - path: README.md
    url: https://github.com/agenticnotetaking/arscontexta/blob/2acfd5cc/README.md?plain=1
    line_range: [202, 207]
deepwiki_url: https://deepwiki.com/agenticnotetaking/arscontexta/3.2-the-15-kernel-primitives
tags: [deepwiki, generated]
fetched_at: 2026-04-26T07:10:00Z
---
```

`mdschema` validates this frontmatter against `vault_page.zod.ts` on every
vault generation.
