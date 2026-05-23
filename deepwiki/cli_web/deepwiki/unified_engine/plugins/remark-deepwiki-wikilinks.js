/**
 * remark-deepwiki-wikilinks — rewrite cross-page deepwiki links as Obsidian
 * wikilinks.
 *
 * For a link node whose href matches `/owner/repo/slug` (relative path) or an
 * absolute `https://deepwiki.com/owner/repo/slug` URL, replace the whole node
 * with a text node containing `[[slug|original-text]]`.
 *
 * The rewrite only fires when `options.repo` is set on the plugin or
 * `vfile.data.repo` is populated by the caller. We strip parentheses, square
 * brackets, pipes and hashes from the slug for Obsidian filename safety.
 */

import { visit } from "unist-util-visit";

const ABSOLUTE_RE = /^https?:\/\/(?:www\.)?deepwiki\.com\/([^/?#]+)\/([^/?#]+)(?:\/([^?#]+))?/i;
const RELATIVE_RE = /^\/?([^/?#]+)\/([^/?#]+)(?:\/([^?#]+))?/;

/**
 * @param {{repo?: string, baseUrl?: string}} [options]
 * @returns {(tree: any, file: any) => void}
 */
export function remarkDeepwikiWikilinks(options = {}) {
  return (tree, file) => {
    const repo = options.repo || (file && file.data && file.data.repo);
    if (!repo) return;
    const [scopeOwner, scopeName] = repo.split("/");

    visit(tree, "link", (node, index, parent) => {
      if (!parent || typeof index !== "number") return;
      const href = node.url || "";
      let owner;
      let name;
      let slug;
      const abs = href.match(ABSOLUTE_RE);
      if (abs) {
        [, owner, name, slug] = abs;
      } else if (href.startsWith("/")) {
        const rel = href.match(RELATIVE_RE);
        if (rel) {
          [, owner, name, slug] = rel;
        }
      }
      if (!owner || !name || !slug) return;
      if (owner !== scopeOwner || name !== scopeName) return;

      // MUST match Python utils.helpers.safe_filename:
      //   strip []|#():*?"<>\\/, collapse `-` runs, trim trailing.
      // This keeps wikilinks pointing at the on-disk filenames vault.py writes.
      const safeSlug = slug
        .replace(/\?.*/, "")
        .replace(/#.*/, "")
        .replace(/[\[\]()|#:*?"<>\\/]/g, "-")
        .replace(/-+/g, "-")
        .replace(/^-+|-+$/g, "")
        .trim();
      if (!safeSlug) return;

      const text = node.children
        .map((c) => (typeof c.value === "string" ? c.value : ""))
        .join("")
        .trim();
      const value = text && text !== safeSlug
        ? `[[${safeSlug}|${text}]]`
        : `[[${safeSlug}]]`;

      // Use an `html` node so remark-stringify passes the brackets through
      // verbatim instead of escaping them (`[[…]]` → `\[\[…]]`).
      parent.children.splice(index, 1, { type: "html", value });
      return index + 1;
    });
  };
}

export default remarkDeepwikiWikilinks;
