/**
 * htmlToMd — defuddle (best-effort) → rehype-parse → rehype-remark → remark-stringify.
 *
 * Defuddle is designed for full pages and may return empty/garbage output for
 * fragments. We try defuddle first; if its output is empty or shorter than half
 * the input, we fall back to parsing the raw HTML directly. The smoke test
 * (`<h1>Hi</h1><p>World</p>`) goes through the fallback path.
 */

import { unified } from "unified";
import rehypeParse from "rehype-parse";
import rehypeRemark from "rehype-remark";
import remarkStringify from "remark-stringify";
import remarkGfm from "remark-gfm";

/**
 * Try to clean HTML with defuddle/node (which bundles JSDOM). Returns either a
 * cleaned content string + metadata, or null if defuddle is unavailable / unhappy.
 *
 * @param {string} html
 * @param {{baseUrl?: string}} opts
 * @returns {Promise<{content: string, title?: string, metadata?: Record<string, any>}|null>}
 */
async function tryDefuddle(html, opts) {
  try {
    const mod = await import("defuddle/node");
    const Defuddle = mod.Defuddle || mod.default;
    if (typeof Defuddle !== "function") return null;
    const result = await Defuddle(html, {
      url: opts?.baseUrl,
      markdown: false,
    });
    if (!result || typeof result.content !== "string") return null;
    return {
      content: result.content,
      title: result.title,
      metadata: {
        author: result.author,
        description: result.description,
        published: result.published,
        domain: result.domain,
        wordCount: result.wordCount,
      },
    };
  } catch {
    return null;
  }
}

/**
 * Convert HTML to a Markdown string + (best-effort) title and metadata.
 *
 * @param {string} html - Raw HTML.
 * @param {{baseUrl?: string}} [opts] - Optional base URL for defuddle.
 * @returns {Promise<{markdown: string, title?: string, metadata?: Record<string, any>}>}
 */
export async function htmlToMd(html, opts = {}) {
  if (typeof html !== "string") {
    throw new TypeError("htmlToMd: html must be a string");
  }

  let title;
  let metadata;
  let cleanedHtml = html;

  // Defuddle is a content-extraction stage. Skip on tiny inputs (it usually
  // returns garbage) and skip if it returns less than half the input bytes.
  if (html.length > 200) {
    const cleaned = await tryDefuddle(html, opts);
    if (cleaned && cleaned.content && cleaned.content.length > html.length / 4) {
      cleanedHtml = cleaned.content;
      title = cleaned.title;
      metadata = cleaned.metadata;
    }
  }

  const file = await unified()
    .use(rehypeParse, { fragment: true })
    .use(rehypeRemark)
    .use(remarkGfm)
    .use(remarkStringify, { bullet: "-", emphasis: "_", strong: "*", fences: true })
    .process(cleanedHtml);

  return { markdown: String(file), title, metadata };
}
