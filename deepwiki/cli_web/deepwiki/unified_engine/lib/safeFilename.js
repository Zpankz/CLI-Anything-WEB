/**
 * safeFilename — must match Python `cli_web.deepwiki.utils.helpers.safe_filename`.
 *
 * Used by:
 *   - plugins/remark-deepwiki-wikilinks.js  (rewrite links)
 *   - plugins/remark-deepwiki-mocs.js       (build MOC)
 *
 * Filename and wikilink target MUST agree, otherwise Obsidian's link
 * resolver fails on slugs with colons or parentheses.
 *
 * Rules:
 *   - Strip query / fragment
 *   - Replace any of  [](){|#:*?"<>\\/   with `-`
 *   - Collapse runs of `-`
 *   - Trim leading/trailing `-`
 */
export function safeFilename(slug) {
  if (typeof slug !== "string") return "page";
  return (
    slug
      .replace(/\?.*/, "")
      .replace(/#.*/, "")
      .replace(/[\[\]()|#:*?"<>\\/]/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-+|-+$/g, "")
      .trim() || "page"
  );
}

export default safeFilename;
