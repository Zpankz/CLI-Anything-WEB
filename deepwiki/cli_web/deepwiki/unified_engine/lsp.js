#!/usr/bin/env node
/**
 * lsp.js — `cli-web-deepwiki lsp` entry point.
 *
 * Boots a `unified-language-server` process with the project's remark-based
 * processor configuration. Stdio mode is the default; pass `--node-ipc` /
 * `--socket=PORT` to override.
 *
 * Usage (from Python):
 *   subprocess.Popen(["node", "lsp.js", "--stdio"], ...)
 */

import process from "node:process";

if (process.argv.includes("--help")) {
  process.stdout.write(
    "cli-web-deepwiki-lsp — unified-language-server transport.\n" +
      "Flags: --stdio (default), --node-ipc, --socket=PORT\n",
  );
  process.exit(0);
}

// Default to --stdio if no transport flag is given (matches Python expectations).
if (
  !process.argv.includes("--stdio") &&
  !process.argv.includes("--node-ipc") &&
  !process.argv.some((a) => a.startsWith("--socket"))
) {
  process.argv.push("--stdio");
}

const { createUnifiedLanguageServer } = await import("unified-language-server");
const { remarkDeepwikiWikilinks } = await import(
  "./plugins/remark-deepwiki-wikilinks.js"
);
const { default: remarkParse } = await import("remark-parse");
const { default: remarkStringify } = await import("remark-stringify");
const { default: remarkFrontmatter } = await import("remark-frontmatter");
const { default: remarkGfm } = await import("remark-gfm");
const { default: remarkMath } = await import("remark-math");
const { default: remarkDirective } = await import("remark-directive");

createUnifiedLanguageServer({
  ignoreName: ".remarkignore",
  packageField: "remarkConfig",
  pluginPrefix: "remark",
  rcName: ".remarkrc",
  plugins: [
    remarkParse,
    [remarkFrontmatter, ["yaml", "toml"]],
    remarkGfm,
    remarkMath,
    remarkDirective,
    remarkDeepwikiWikilinks,
    remarkStringify,
  ],
});
