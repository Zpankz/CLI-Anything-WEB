/**
 * remark-frontmatter-yaml — prepend a YAML frontmatter block built from a
 * caller-supplied object.
 *
 * Use after `remark-frontmatter` is registered so the resulting tree round-
 * trips cleanly through `remark-stringify`. Existing frontmatter is replaced
 * (last-write-wins).
 */

import YAML from "yaml";

/**
 * @param {{ctx?: Record<string, any>}} [options]
 * @returns {(tree: any) => void}
 */
export function remarkFrontmatterYaml(options = {}) {
  return (tree) => {
    const ctx = options.ctx;
    if (!ctx || typeof ctx !== "object") return;
    const yaml = YAML.stringify(ctx).trimEnd();
    const node = { type: "yaml", value: yaml };
    if (
      tree.children.length &&
      (tree.children[0].type === "yaml" || tree.children[0].type === "toml")
    ) {
      tree.children[0] = node;
    } else {
      tree.children.unshift(node);
    }
  };
}

export default remarkFrontmatterYaml;
