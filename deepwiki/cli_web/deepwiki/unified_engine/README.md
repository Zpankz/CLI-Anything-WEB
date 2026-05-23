# cli-web-deepwiki — unified ecosystem sidecar

Long-lived Node.js child process that exposes the [unified.js](https://unifiedjs.com/)
ecosystem (defuddle → rehype → remark → retext → xast) as a JSON-RPC
service over stdin/stdout. Invoked from the Python CLI via
`utils/unified_bridge.py`.

## Wire protocol

One JSON object per line. Each request must include a unique `id`:

```
> {"id":"<uuid>","method":"<name>","params":{...}}
< {"id":"<uuid>","ok":true,"data":{...}}
< {"id":"<uuid>","ok":false,"error":"<message>"}
```

Stdout carries only response lines. Stderr carries diagnostics
(the Python parent drains it asynchronously).

## Methods

| Method        | Payload                                | Returns |
|---------------|----------------------------------------|---------|
| `htmlToMd`    | `{html, baseUrl?}`                     | `{markdown, title?, metadata?}` |
| `htmlToMdast` | `{html}`                               | `{tree}` |
| `mdToOfm`     | `{markdown, options}`                  | `{markdown}` |
| `mdToNlcst`   | `{markdown}`                           | `{tree}` |
| `astQuery`    | `{tree, type, selector}`               | `{matches[]}` |
| `astConvert`  | `{input, from, to}`                    | `{output}` |
| `vaultPage`   | `{html, ctx}`                          | `{markdown, frontmatter, links, sources}` |
| `vaultMoc`    | `{repo, pages, structure}`             | `{markdown}` |
| `vaultCanvas` | `{repo, pages, links}`                 | `{canvas}` |
| `analyze`     | `{markdown}`                           | `{readability, stats, entities}` |
| `lsp`         | `{action, port?, stdio?}`              | `{ok}` (stub — actual LSP runs via `lsp.js`) |

## Layout

```
unified_engine/
  server.js              JSON-RPC dispatcher (default entry point)
  lsp.js                 `cli-web-deepwiki-lsp` entry point
  unified.config.js      Shared unified processor factory
  pipelines/             One file per transformation
  plugins/               remark-deepwiki-{wikilinks,sources,mocs} + frontmatter helper
  schemas/index.ts       Zod schemas (target for `npm run docs` via zod2md)
  lib/
    mdschema.js          Local frontmatter validator (yaml + zod)
    nlcstToString.js     Tiny nlcst flattener
  vault.js               vaultPage / vaultMoc / vaultCanvas
```

## Running

```bash
npm install
node server.js < requests.jsonl > responses.jsonl
```

Smoke test:

```bash
echo '{"id":"1","method":"htmlToMd","params":{"html":"<h1>Hi</h1><p>World</p>"}}' \
  | node server.js
```

Expected:

```
{"id":"1","ok":true,"data":{"markdown":"# Hi\n\nWorld\n"}}
```

## Notes

* ESM-only (`"type":"module"`); every relative import uses an explicit `.js` extension.
* The `mdschema` package on npm is a different project (Markdown-from-JSON-Schema).
  We rolled our own validator in `lib/mdschema.js` using `yaml` + `zod`.
* `defuddle` is invoked via the bundled `defuddle/node` subpath (which carries
  its own JSDOM); on tiny / fragmenty inputs we bypass it and pipe HTML
  directly through `rehype-parse` + `rehype-remark`.
* The `lsp` JSON-RPC method is a stub that acknowledges the call. The real
  language server boots from `lsp.js` as a separate process — this lets
  editors talk to it without going through the JSON-RPC dispatcher.
