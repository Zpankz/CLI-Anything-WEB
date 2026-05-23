/**
 * nlcstToString — minimal recursive flattener for nlcst trees.
 * Avoids pulling in `nlcst-to-string` so we have one fewer dep to manage.
 */

/**
 * Concatenate all leaf-level `value`s in an nlcst node.
 *
 * @param {any} node
 * @returns {string}
 */
export function toString(node) {
  if (!node) return "";
  if (typeof node.value === "string") return node.value;
  if (Array.isArray(node.children)) {
    return node.children.map(toString).join("");
  }
  return "";
}
