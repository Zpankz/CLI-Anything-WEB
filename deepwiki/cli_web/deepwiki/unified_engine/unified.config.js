/**
 * unified.config.js — shared unified configuration consumed by `unified-args`
 * (CLI mode) and `unified-language-server` (LSP mode).
 *
 * Exports a single function that returns a fresh `unified.Processor` so each
 * entry point can call `.use(...)` further without polluting the prototype
 * chain.
 */

import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkStringify from "remark-stringify";
import remarkFrontmatter from "remark-frontmatter";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkDirective from "remark-directive";

import { remarkDeepwikiWikilinks } from "./plugins/remark-deepwiki-wikilinks.js";
import { remarkDeepwikiSources } from "./plugins/remark-deepwiki-sources.js";

/**
 * Build a configured Markdown processor mirroring `mdToOfm`.
 *
 * @returns {import("unified").Processor}
 */
export function createProcessor() {
  return unified()
    .use(remarkParse)
    .use(remarkFrontmatter, ["yaml", "toml"])
    .use(remarkGfm)
    .use(remarkMath)
    .use(remarkDirective)
    .use(remarkDeepwikiSources)
    .use(remarkDeepwikiWikilinks)
    .use(remarkStringify, {
      bullet: "-",
      emphasis: "_",
      strong: "*",
      fences: true,
      listItemIndent: "one",
      rule: "-",
    });
}

export default createProcessor;
