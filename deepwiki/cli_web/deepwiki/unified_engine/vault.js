/**
 * vault.js — Obsidian vault output stages.
 *
 *   vaultPage   single-page transform (HTML → frontmatter+wikilinks markdown)
 *   vaultMoc    Map-of-Content top-level index for a repo
 *   vaultCanvas JSON Canvas (jsoncanvas.org/spec/1.0/) backlink graph
 */

import { unified } from "unified";
import rehypeParse from "rehype-parse";
import rehypeRemark from "rehype-remark";
import remarkParse from "remark-parse";
import remarkStringify from "remark-stringify";
import remarkFrontmatter from "remark-frontmatter";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkDirective from "remark-directive";
import { visit } from "unist-util-visit";

import { remarkDeepwikiWikilinks } from "./plugins/remark-deepwiki-wikilinks.js";
import { remarkDeepwikiSources } from "./plugins/remark-deepwiki-sources.js";
import { remarkFrontmatterYaml } from "./plugins/remark-frontmatter-yaml.js";
import { buildMoc } from "./plugins/remark-deepwiki-mocs.js";

/**
 * Find the article body inside a DeepWiki SSR page. Returns the inner HTML of
 * `<div class="prose-custom ...">` (the actual article container) or null
 * when not present.
 *
 * Tolerant to nested divs (we count opening vs closing tags). Falls back to
 * the broader `<div class="prose ...">` if the inner one isn't found.
 */
export function extractArticleBody(html) {
  // Strip Next.js Suspense markers and React server-component scaffolding
  let cleaned = html
    .replace(/<!--\$\??-->/g, "")
    .replace(/<!--\/\$-->/g, "")
    .replace(/<!--\s*-->/g, "");
  // Try inner prose-custom first (the actual article container)
  for (const klass of ["prose-custom", "prose prose-invert", "prose"]) {
    const opener = new RegExp(
      `<div\\s+[^>]*class=\"[^\"]*${klass.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}[^\"]*\"[^>]*>`,
      "i",
    );
    const m = opener.exec(cleaned);
    if (!m) continue;
    const start = m.index + m[0].length;
    // Walk forward, counting nested <div>s until depth returns to zero.
    let depth = 1;
    const re = /<\/?div\b[^>]*>/gi;
    re.lastIndex = start;
    let match;
    while ((match = re.exec(cleaned))) {
      if (match[0].startsWith("</")) {
        depth--;
        if (depth === 0) {
          return cleaned.slice(start, match.index);
        }
      } else {
        depth++;
      }
    }
  }
  return null;
}

/**
 * Transform a single DeepWiki HTML page into vault Markdown.
 *
 * Steps:
 *   1. defuddle (best effort) → rehype → mdast
 *   2. lift `**Sources:**` blocks into vfile.data.sources
 *   3. rewrite same-repo links as `[[wikilink|title]]`
 *   4. attach YAML frontmatter from ctx + collected sources
 *
 * @param {string} html
 * @param {Record<string, any>} ctx - title, slug, repo, indexed_at, etc.
 * @returns {Promise<{markdown: string, frontmatter: Record<string, any>, links: string[], sources: any[]}>}
 */
export async function vaultPage(html, ctx) {
  if (typeof html !== "string") throw new TypeError("vaultPage: html must be a string");
  if (!ctx || typeof ctx !== "object") ctx = {};

  // Stage 0 — narrow HTML to article body. DeepWiki wraps article content in
  // <div class="prose-custom ..."> nested inside <div class="prose ...">.
  // We pluck the inner container; sidebar / header / Q&A widget are skipped.
  const article = extractArticleBody(html) ?? html;

  // Stage 1 — HTML to mdast (operate on the narrowed article).
  const htmlProcessor = unified()
    .use(rehypeParse, { fragment: true })
    .use(rehypeRemark)
    .use(remarkGfm);
  const hast = htmlProcessor.parse(article);
  const mdast = await htmlProcessor.run(hast);

  // Stage 2 — sources lifting + wikilink rewrite + frontmatter.
  const repo = ctx.repo;
  const stringifyProcessor = unified()
    .use(remarkParse) // ignored (we feed a tree)
    .use(remarkFrontmatter, ["yaml"])
    .use(remarkGfm)
    .use(remarkMath)
    .use(remarkDirective)
    .use(remarkDeepwikiSources)
    .use(remarkDeepwikiWikilinks, { repo })
    .use(remarkStringify, {
      bullet: "-",
      emphasis: "_",
      strong: "*",
      fences: true,
      listItemIndent: "one",
      rule: "-",
    });

  const file = { data: { repo }, messages: [] };
  const transformed = await stringifyProcessor.run(mdast, file);

  const sources = (file.data && file.data.sources) || [];
  // Frontmatter assembly (caller-supplied ctx wins; sources merged in).
  const frontmatter = {
    ...(ctx || {}),
    ...(sources.length ? { sources } : {}),
  };
  // Inject frontmatter as a yaml node prepended to the tree.
  remarkFrontmatterYaml({ ctx: frontmatter })(transformed);

  const markdown = String(stringifyProcessor.stringify(transformed));

  // Collect outbound link targets for callers (used by canvas builder).
  /** @type {string[]} */
  const links = [];
  visit(transformed, (node) => {
    if (node.type !== "text" && node.type !== "html") return;
    const m = node.value && node.value.match(/\[\[([^\]|]+)(?:\|[^\]]+)?\]\]/g);
    if (m) for (const hit of m) {
      const slug = hit.slice(2, -2).split("|")[0].trim();
      if (slug) links.push(slug);
    }
  });

  return { markdown, frontmatter, links, sources };
}

/**
 * Build a top-level Map-of-Content for a repo.
 *
 * @param {string} repo
 * @param {Array<{slug: string, title: string}>} pages
 * @param {Array<{slug: string, title: string, parent?: string|null}>} structure
 * @returns {Promise<{markdown: string}>}
 */
export async function vaultMoc(repo, pages, structure) {
  const tree = buildMoc(repo, pages || [], structure || []);
  const stringifier = unified().use(remarkStringify, { bullet: "-" });
  const markdown = String(stringifier.stringify(tree));
  return { markdown };
}

/**
 * Build a JSON Canvas (https://jsoncanvas.org/spec/1.0/) representing the
 * wiki's backlink graph.
 *
 * Node positioning: greedy grid by hierarchy depth (column = top-level prefix
 * group, row = position inside that group).
 *
 * @param {string} repo
 * @param {Array<{slug: string, title: string}>} pages
 * @param {Array<{from: string, to: string}>} links
 * @returns {Promise<{canvas: any}>}
 */
export async function vaultCanvas(repo, pages, links) {
  const NODE_W = 320;
  const NODE_H = 80;
  const COL_GAP = 80;
  const ROW_GAP = 40;

  /** @type {Map<string, {x: number, y: number, w: number, h: number, slug: string, title: string, id: string}>} */
  const nodeMap = new Map();
  /** @type {Map<string, number>} */
  const colCount = new Map();

  /**
   * @param {string} slug
   * @returns {string}
   */
  function topPrefix(slug) {
    const m = slug.match(/^(\d+)/);
    return m ? m[1] : (slug[0] || "_");
  }

  for (const page of pages || []) {
    const col = topPrefix(page.slug);
    const row = colCount.get(col) || 0;
    colCount.set(col, row + 1);
    const colIndex = [...colCount.keys()].indexOf(col);
    const id = page.slug;
    nodeMap.set(id, {
      id,
      slug: page.slug,
      title: page.title || page.slug,
      x: colIndex * (NODE_W + COL_GAP),
      y: row * (NODE_H + ROW_GAP),
      w: NODE_W,
      h: NODE_H,
    });
  }

  const nodes = [...nodeMap.values()].map((n) => ({
    id: n.id,
    type: "file",
    file: `${n.slug}.md`,
    label: n.title,
    x: n.x,
    y: n.y,
    width: n.w,
    height: n.h,
  }));

  const edges = (links || [])
    .filter((l) => l && l.from && l.to && nodeMap.has(l.from) && nodeMap.has(l.to))
    .map((l, i) => ({
      id: `e${i}`,
      fromNode: l.from,
      fromSide: "right",
      toNode: l.to,
      toSide: "left",
    }));

  return { canvas: { nodes, edges } };
}
