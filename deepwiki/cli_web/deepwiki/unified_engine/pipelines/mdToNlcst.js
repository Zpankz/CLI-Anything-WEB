/**
 * mdToNlcst — Markdown → nlcst tree via the remark-retext bridge.
 *
 *   remark-parse → remark-retext(ParseEnglish) → retext-pos
 *
 * `remark-retext` has two modes:
 *   • Given a Parser (e.g. `ParseEnglish`), it *mutates* the tree in place,
 *     so subsequent retext plugins can run on the nlcst tree.
 *   • Given a Processor, it acts as a *bridge*, running the destination as a
 *     side-effect and returning the unchanged mdast.
 *
 * For tree output we want mutate-mode, then `.run()` to apply `retext-pos`.
 */

import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkRetext from "remark-retext";
import retextPos from "retext-pos";
import { ParseEnglish } from "parse-english";

/**
 * Convert Markdown to an nlcst tree (with POS tags).
 *
 * @param {string} markdown
 * @returns {Promise<{tree: any}>}
 */
export async function mdToNlcst(markdown) {
  if (typeof markdown !== "string") {
    throw new TypeError("mdToNlcst: markdown must be a string");
  }
  const processor = unified()
    .use(remarkParse)
    .use(remarkRetext, ParseEnglish)
    .use(retextPos);

  const mdast = processor.parse(markdown);
  const tree = await processor.run(mdast);
  return { tree };
}
