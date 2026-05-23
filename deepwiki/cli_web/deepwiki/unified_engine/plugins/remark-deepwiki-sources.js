/**
 * remark-deepwiki-sources — extract `**Sources:**` paragraph trailers into
 * `vfile.data.sources` so the caller can hoist them into frontmatter.
 *
 * DeepWiki pages frequently end (or repeatedly include) a paragraph like:
 *
 *   **Sources:**
 *   - [README.md:202-207](https://github.com/owner/repo/blob/sha/README.md?plain=1#L202-L207)
 *
 * This plugin walks the tree, finds each such paragraph + the list that
 * follows, lifts the link metadata into `file.data.sources`, and removes the
 * nodes from the tree (so the rendered Markdown is clean).
 */

import { visit } from "unist-util-visit";

const SOURCES_RE = /^\s*sources?\s*:?\s*$/i;

/**
 * @returns {(tree: any, file: any) => void}
 */
export function remarkDeepwikiSources() {
  return (tree, file) => {
    if (!file.data) file.data = {};
    if (!Array.isArray(file.data.sources)) file.data.sources = [];

    const toRemove = [];
    visit(tree, "paragraph", (node, index, parent) => {
      if (!parent || typeof index !== "number") return;
      const head = node.children?.[0];
      const isHeader =
        (head?.type === "strong" || head?.type === "emphasis") &&
        SOURCES_RE.test(head.children?.[0]?.value || "");
      if (!isHeader) return;

      // Look at the immediately following list (siblings after the paragraph).
      const next = parent.children[index + 1];
      if (next && next.type === "list") {
        for (const item of next.children || []) {
          for (const block of item.children || []) {
            if (block.type !== "paragraph") continue;
            visit(block, "link", (linkNode) => {
              const text = (linkNode.children || [])
                .map((c) => c.value || "")
                .join("");
              file.data.sources.push({
                title: text,
                url: linkNode.url,
              });
            });
          }
        }
        toRemove.push({ parent, index, count: 2 });
      } else {
        toRemove.push({ parent, index, count: 1 });
      }
    });

    // Remove from the bottom up so indices remain valid.
    toRemove
      .sort((a, b) => b.index - a.index)
      .forEach(({ parent, index, count }) => parent.children.splice(index, count));
  };
}

export default remarkDeepwikiSources;
