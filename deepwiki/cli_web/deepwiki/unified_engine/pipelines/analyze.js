/**
 * analyze — produce text analytics for a Markdown document.
 *
 * Pipeline (outer): remark-parse → remark-retext(<inner>) → remark-stringify
 * Pipeline (inner): retext-english → retext-pos → retext-readability →
 *                   retext-keywords → retext-stringify
 *
 * The inner retext processor is fully configured (with a stringify compiler)
 * so the bridge can call .process() on it without errors.
 */

import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkStringify from "remark-stringify";
import remarkRetext from "remark-retext";
import retextEnglish from "retext-english";
import retextPos from "retext-pos";
import retextReadability from "retext-readability";
import retextKeywords from "retext-keywords";
import retextStringify from "retext-stringify";
import { VFile } from "vfile";
import { visit } from "unist-util-visit";
import { toString as nlcstToString } from "../lib/nlcstToString.js";

/**
 * Generate readability + stats + keywords for a markdown document.
 *
 * @param {string} markdown
 * @returns {Promise<{readability: any, stats: {sentences: number, words: number, chars: number}, entities: any[]}>}
 */
export async function analyze(markdown) {
  if (typeof markdown !== "string") {
    throw new TypeError("analyze: markdown must be a string");
  }

  const retextProcessor = unified()
    .use(retextEnglish)
    .use(retextPos)
    .use(retextReadability, { age: 18 })
    .use(retextKeywords, { maximum: 8 })
    .use(retextStringify);

  const processor = unified()
    .use(remarkParse)
    .use(remarkRetext, retextProcessor)
    .use(remarkStringify);

  const file = new VFile(markdown);
  await processor.process(file);

  // For sentence/word counts: re-parse just the text via the inner retext
  // processor (the outer pipeline re-emits Markdown, not nlcst).
  const nlcst = retextProcessor.parse(new VFile(markdown));
  let sentences = 0;
  let words = 0;
  visit(nlcst, "SentenceNode", () => sentences++);
  visit(nlcst, "WordNode", () => words++);

  const readability = {
    notes: file.messages.map((m) => ({
      reason: m.reason,
      ruleId: m.ruleId,
      source: m.source,
      line: m.line,
      column: m.column,
    })),
  };

  const keywords = (file.data && file.data.keywords) || [];
  const keyphrases = (file.data && file.data.keyphrases) || [];
  const entities = [
    ...keywords.map((k) => ({
      type: "keyword",
      stem: k.stem,
      score: k.score,
      matches: (k.matches || []).map((m) => nlcstToString(m.node)),
    })),
    ...keyphrases.map((k) => ({
      type: "keyphrase",
      stems: k.stems,
      score: k.score,
      matches: (k.matches || []).map((m) =>
        (m.nodes || []).map((n) => nlcstToString(n)).join(" ")
      ),
    })),
  ];

  return {
    readability,
    stats: { sentences, words, chars: markdown.length },
    entities,
  };
}
