/**
 * mdToOfm — round-trip Markdown through the Obsidian-Flavoured Markdown stack.
 *
 *   remark-parse
 *     → remark-frontmatter
 *     → remark-gfm (configured for OFM-style)
 *     → remark-math
 *     → remark-directive
 *     → remark-deepwiki-wikilinks (custom)
 *   → remark-stringify
 */

import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkStringify from "remark-stringify";
import remarkFrontmatter from "remark-frontmatter";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkDirective from "remark-directive";

import { remarkDeepwikiWikilinks } from "../plugins/remark-deepwiki-wikilinks.js";

/**
 * Convert raw Markdown to canonical OFM Markdown.
 *
 * @param {string} markdown
 * @param {{repo?: string, baseUrl?: string, frontmatter?: boolean, wikilinks?: boolean}} [options]
 * @returns {Promise<{markdown: string}>}
 */
export async function mdToOfm(markdown, options = {}) {
  if (typeof markdown !== "string") {
    throw new TypeError("mdToOfm: markdown must be a string");
  }

  let processor = unified().use(remarkParse);

  if (options.frontmatter !== false) {
    processor = processor.use(remarkFrontmatter, ["yaml", "toml"]);
  }
  processor = processor
    .use(remarkGfm, { singleTilde: false })
    .use(remarkMath)
    .use(remarkDirective);

  if (options.wikilinks !== false) {
    processor = processor.use(remarkDeepwikiWikilinks, {
      repo: options.repo,
      baseUrl: options.baseUrl,
    });
  }

  processor = processor.use(remarkStringify, {
    bullet: "-",
    emphasis: "_",
    strong: "*",
    fences: true,
    listItemIndent: "one",
    rule: "-",
  });

  const file = await processor.process(markdown);
  return { markdown: String(file) };
}
