/**
 * lib/mdschema.js — local frontmatter validator.
 *
 * NOTE: There is an `mdschema` package on npm, but it does something different
 * (markdown generation from JSON Schema). We rolled our own thin wrapper here
 * using `yaml` + `zod` so the sidecar can validate vault frontmatter against
 * a Zod schema and report human-readable errors.
 *
 * Usage:
 *   import { validate } from "./lib/mdschema.js";
 *   import { VaultPageFrontmatter } from "../schemas/index.ts";  // or .js
 *   const { ok, errors } = validate(yamlText, VaultPageFrontmatter);
 */

import YAML from "yaml";

/**
 * Validate a YAML frontmatter string against a Zod schema.
 *
 * @param {string|Record<string, any>} input - Either a YAML string or already-parsed object.
 * @param {{ safeParse: (data: any) => { success: boolean, error?: any, data?: any } }} schema
 * @returns {{ok: boolean, value?: any, errors: Array<{path: string, message: string}>}}
 */
export function validate(input, schema) {
  let data;
  try {
    data = typeof input === "string" ? YAML.parse(input) : input;
  } catch (err) {
    return { ok: false, errors: [{ path: "<yaml>", message: `parse error: ${err.message}` }] };
  }
  const result = schema.safeParse(data);
  if (result.success) {
    return { ok: true, value: result.data, errors: [] };
  }
  const errors = (result.error?.issues || []).map((issue) => ({
    path: issue.path.join("."),
    message: issue.message,
  }));
  return { ok: false, errors };
}

/**
 * Render an object as a YAML frontmatter block (no `---` fences).
 *
 * @param {Record<string, any>} ctx
 * @returns {string}
 */
export function stringify(ctx) {
  return YAML.stringify(ctx).trimEnd();
}
