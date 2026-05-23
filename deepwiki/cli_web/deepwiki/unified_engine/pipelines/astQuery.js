/**
 * astQuery — query a unist tree with either a node-type filter or a
 * unist-util-select CSS-like selector. Returns the matching nodes.
 */

import { visit } from "unist-util-visit";
import { selectAll } from "unist-util-select";

/**
 * Query a unist tree.
 *
 * If `selector` is a non-empty string, defer to `unist-util-select`
 * (CSS-like selector syntax: `heading[depth=1]`, `link`, etc.).
 *
 * Otherwise, walk the tree with `unist-util-visit` and collect nodes whose
 * `type` matches `type`. If `type` is `"mdast"` or empty, collect everything.
 *
 * @param {any} tree
 * @param {string} type
 * @param {string} selector
 * @returns {{matches: any[]}}
 */
export function astQuery(tree, type = "mdast", selector = "") {
  if (!tree || typeof tree !== "object") {
    throw new TypeError("astQuery: tree must be an object");
  }
  /** @type {any[]} */
  let matches = [];
  if (selector && selector.trim()) {
    matches = selectAll(selector, tree);
  } else {
    const family = ["mdast", "hast", "nlcst", "xast", ""];
    visit(tree, (node) => {
      if (family.includes(type) || node.type === type) {
        matches.push(node);
      }
    });
  }
  return { matches };
}
