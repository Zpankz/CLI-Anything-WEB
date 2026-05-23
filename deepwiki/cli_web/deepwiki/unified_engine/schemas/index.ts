/**
 * Zod schemas for cli-web-deepwiki.
 *
 * Used by:
 *   - The Python parent (via `mdschema` validate) to verify vault frontmatter.
 *   - `npm run docs` (zod2md) to render Markdown reference docs.
 */

import { z } from "zod";

/** A single source citation lifted from `**Sources:**` paragraphs. */
export const Source = z.object({
  path: z.string().optional(),
  url: z.string().url(),
  line_range: z.tuple([z.number().int(), z.number().int()]).optional(),
  title: z.string().optional(),
});

/** YAML frontmatter at the top of every generated vault page. */
export const VaultPageFrontmatter = z.object({
  title: z.string(),
  slug: z.string(),
  repo: z.string(),
  indexed_at: z.string().optional(),
  indexed_commit: z.string().optional(),
  sources: z.array(Source).optional(),
  deepwiki_url: z.string().url().optional(),
  tags: z.array(z.string()).optional(),
  fetched_at: z.string().optional(),
});

/** Structure node in a wiki tree (one per page). */
export const StructureNode = z.object({
  slug: z.string(),
  title: z.string(),
  parent: z.string().nullable().optional(),
});

/** vault index (the metadata JSON sidecar emitted alongside the .md files). */
export const VaultIndex = z.object({
  repo: z.string(),
  generated_at: z.string(),
  pages: z.array(z.object({ slug: z.string(), title: z.string() })),
  structure: z.array(StructureNode),
});

/** Devin Ada answer envelope (after streaming has converged). */
export const AskAnswer = z.object({
  query_id: z.string(),
  state: z.enum(["pending", "running", "done", "error"]),
  title: z.string().optional(),
  markdown: z.string().optional(),
  references: z.array(z.object({
    file_path: z.string(),
    range_start: z.number().int().optional(),
    range_end: z.number().int().optional(),
    url: z.string().url().optional(),
  })).optional(),
});

/** Repo metadata as returned by `/ada/list_public_indexes`. */
export const RepoIndex = z.object({
  id: z.string(),
  owner: z.string(),
  name: z.string(),
  full_name: z.string(),
  short_commit_sha: z.string().optional(),
  language: z.string().optional(),
  last_indexed: z.string().optional(),
  description: z.string().optional(),
});

export type Source = z.infer<typeof Source>;
export type VaultPageFrontmatter = z.infer<typeof VaultPageFrontmatter>;
export type StructureNode = z.infer<typeof StructureNode>;
export type VaultIndex = z.infer<typeof VaultIndex>;
export type AskAnswer = z.infer<typeof AskAnswer>;
export type RepoIndex = z.infer<typeof RepoIndex>;
