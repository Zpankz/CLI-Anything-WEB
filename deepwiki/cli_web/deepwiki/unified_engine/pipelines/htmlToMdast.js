/**
 * htmlToMdast — rehype-parse → rehype-remark → mdast tree (no stringify).
 */

import { unified } from "unified";
import rehypeParse from "rehype-parse";
import rehypeRemark from "rehype-remark";
import remarkGfm from "remark-gfm";

/**
 * Parse HTML and return the resulting mdast tree.
 *
 * @param {string} html
 * @returns {Promise<{tree: any}>}
 */
export async function htmlToMdast(html) {
  if (typeof html !== "string") {
    throw new TypeError("htmlToMdast: html must be a string");
  }
  const processor = unified()
    .use(rehypeParse, { fragment: true })
    .use(rehypeRemark)
    .use(remarkGfm);
  const hast = processor.parse(html);
  const tree = await processor.run(hast);
  return { tree };
}
