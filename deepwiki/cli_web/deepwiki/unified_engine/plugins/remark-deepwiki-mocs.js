import { safeFilename } from "../lib/safeFilename.js";

/**
 * remark-deepwiki-mocs — build a Map-of-Content (MOC) Markdown body from a
 * page index.
 *
 * Used as a *generator* (not a transformer): callers do not feed input through
 * this plugin; instead, they call `buildMoc(repo, pages, structure)` to get a
 * canonical mdast root they can stringify.
 *
 * Pages are grouped by numbered prefix hierarchy. A slug like `3.2-the-15-...`
 * has the path "3", "3.2"; we use these prefixes to nest list items.
 */

/**
 * @typedef {{slug: string, title: string, parent?: string|null}} StructureNode
 * @typedef {{slug: string, title: string}} PageRef
 */

/**
 * @param {string} slug
 * @returns {string[]} Prefix path, e.g. "3.2-foo" → ["3", "3.2"].
 */
function prefixPath(slug) {
  const m = slug.match(/^(\d+(?:\.\d+)*)\b/);
  if (!m) return [];
  const parts = m[1].split(".");
  /** @type {string[]} */
  const acc = [];
  for (let i = 0; i < parts.length; i++) {
    acc.push(parts.slice(0, i + 1).join("."));
  }
  return acc;
}

/**
 * Build a nested mdast list from the given pages.
 *
 * @param {string} repo
 * @param {PageRef[]} pages
 * @param {StructureNode[]} structure
 * @returns {{type: "root", children: any[]}}
 */
export function buildMoc(repo, pages, structure) {
  /** @type {Map<string, {title: string, slug: string, kids: any[]}>} */
  const byPrefix = new Map();
  /** @type {any[]} */
  const top = [];

  // Index structure by slug for title lookups.
  const titleBySlug = new Map();
  for (const s of structure || []) titleBySlug.set(s.slug, s.title);
  for (const p of pages || []) if (!titleBySlug.has(p.slug)) titleBySlug.set(p.slug, p.title);

  // Sort pages by their numeric prefix path so parents appear before children.
  const sorted = [...(pages || [])].sort((a, b) => a.slug.localeCompare(b.slug, undefined, { numeric: true }));

  for (const page of sorted) {
    const path = prefixPath(page.slug);
    const node = {
      title: titleBySlug.get(page.slug) || page.title || page.slug,
      slug: page.slug,
      kids: [],
    };
    if (path.length <= 1) {
      top.push(node);
      byPrefix.set(path[0] || page.slug, node);
    } else {
      const parentKey = path[path.length - 2];
      const parent = byPrefix.get(parentKey);
      if (parent) parent.kids.push(node);
      else top.push(node);
      byPrefix.set(path[path.length - 1], node);
    }
  }

  /**
   * @param {{title: string, slug: string, kids: any[]}[]} items
   * @returns {any}
   */
  function toList(items) {
    return {
      type: "list",
      ordered: false,
      spread: false,
      children: items.map((it) => ({
        type: "listItem",
        spread: false,
        children: [
          {
            type: "paragraph",
            children: [
              {
                type: "link",
                url: `${safeFilename(it.slug)}.md`,
                title: null,
                children: [{ type: "text", value: it.title }],
              },
            ],
          },
          ...(it.kids.length ? [toList(it.kids)] : []),
        ],
      })),
    };
  }

  return {
    type: "root",
    children: [
      {
        type: "heading",
        depth: 1,
        children: [{ type: "text", value: `${repo} — Map of Content` }],
      },
      ...(top.length
        ? [toList(top)]
        : [{ type: "paragraph", children: [{ type: "text", value: "(no pages yet)" }] }]),
    ],
  };
}

export default buildMoc;
