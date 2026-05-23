/**
 * astConvert — generic format converter between html, markdown, mdast, hast,
 * nlcst, xast.
 *
 * Inputs may be either source strings (html, markdown) or JSON-stringified
 * trees (mdast, hast, nlcst, xast). Outputs are stringified the same way.
 */

import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkStringify from "remark-stringify";
import remarkRehype from "remark-rehype";
import remarkRetext from "remark-retext";
import remarkGfm from "remark-gfm";
import rehypeParse from "rehype-parse";
import rehypeStringify from "rehype-stringify";
import rehypeRemark from "rehype-remark";
import retextStringify from "retext-stringify";
import { ParseEnglish } from "parse-english";
import { fromXml } from "xast-util-from-xml";
import { toXml } from "xast-util-to-xml";

const FORMATS = new Set(["html", "markdown", "md", "mdast", "hast", "nlcst", "xast", "xml"]);

/**
 * Parse a source string or tree-as-JSON into a unist tree.
 *
 * @param {string} input
 * @param {string} from
 * @returns {Promise<any>}
 */
async function parseInput(input, from) {
  switch (from) {
    case "html": {
      return unified().use(rehypeParse, { fragment: true }).parse(input);
    }
    case "markdown":
    case "md": {
      return unified().use(remarkParse).parse(input);
    }
    case "xml":
    case "xast": {
      if (from === "xml") return fromXml(input);
      return JSON.parse(input);
    }
    case "mdast":
    case "hast":
    case "nlcst": {
      return JSON.parse(input);
    }
    default:
      throw new RangeError(`astConvert: unsupported source format '${from}'`);
  }
}

/**
 * Run a tree through any required transformer to land in `to` form, then
 * stringify (or JSON-stringify, for tree formats).
 *
 * @param {any} tree
 * @param {string} from
 * @param {string} to
 * @returns {Promise<string>}
 */
async function convertTree(tree, from, to) {
  // Tree-to-tree direct cases (no transform required, just JSON dump).
  if (to === from) {
    if (to === "html" || to === "markdown" || to === "md" || to === "xml") {
      throw new RangeError("astConvert: source-form input cannot equal source-form output");
    }
    return JSON.stringify(tree);
  }

  // mdast → markdown
  if (from === "mdast" && (to === "markdown" || to === "md")) {
    return String(await unified().use(remarkStringify).stringify(tree));
  }
  // hast → html
  if (from === "hast" && to === "html") {
    return String(await unified().use(rehypeStringify).stringify(tree));
  }
  // nlcst → text
  if (from === "nlcst" && (to === "text" || to === "plain")) {
    return String(await unified().use(retextStringify).stringify(tree));
  }
  // xast → xml
  if ((from === "xast" || from === "xml") && to === "xml") {
    return toXml(tree);
  }
  // markdown → html
  if ((from === "markdown" || from === "md") && to === "html") {
    const file = await unified()
      .use(remarkParse)
      .use(remarkGfm)
      .use(remarkRehype)
      .use(rehypeStringify)
      .process(typeof tree === "string" ? tree : await unified().use(remarkStringify).stringify(tree));
    return String(file);
  }
  // html → markdown
  if (from === "html" && (to === "markdown" || to === "md")) {
    const file = await unified()
      .use(rehypeParse, { fragment: true })
      .use(rehypeRemark)
      .use(remarkGfm)
      .use(remarkStringify)
      .process(typeof tree === "string" ? tree : await unified().use(rehypeStringify).stringify(tree));
    return String(file);
  }
  // markdown → mdast (already a tree by now in some paths)
  if ((from === "markdown" || from === "md") && to === "mdast") {
    return JSON.stringify(tree);
  }
  // html → hast
  if (from === "html" && to === "hast") {
    return JSON.stringify(tree);
  }
  // markdown → hast
  if ((from === "markdown" || from === "md") && to === "hast") {
    const hast = await unified().use(remarkRehype).run(tree);
    return JSON.stringify(hast);
  }
  // html → mdast
  if (from === "html" && to === "mdast") {
    const mdast = await unified().use(rehypeRemark).run(tree);
    return JSON.stringify(mdast);
  }
  // markdown → nlcst (uses retext bridge in mutate mode)
  if ((from === "markdown" || from === "md") && to === "nlcst") {
    const processor = unified().use(remarkRetext, ParseEnglish);
    const out = await processor.run(tree);
    return JSON.stringify(out);
  }

  throw new RangeError(`astConvert: no path from '${from}' to '${to}'`);
}

/**
 * Convert a document between any two of: html, markdown, mdast, hast, nlcst,
 * xast / xml.
 *
 * @param {string} input
 * @param {string} from
 * @param {string} to
 * @returns {Promise<{output: string}>}
 */
export async function astConvert(input, from, to) {
  if (typeof input !== "string") {
    throw new TypeError("astConvert: input must be a string");
  }
  if (!FORMATS.has(from)) {
    throw new RangeError(`astConvert: unknown 'from' format '${from}'`);
  }
  if (!FORMATS.has(to) && !["text", "plain"].includes(to)) {
    throw new RangeError(`astConvert: unknown 'to' format '${to}'`);
  }
  const tree = await parseInput(input, from);
  const output = await convertTree(tree, from, to);
  return { output };
}
