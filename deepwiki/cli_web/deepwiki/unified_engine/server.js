#!/usr/bin/env node
/**
 * cli-web-deepwiki — unified ecosystem sidecar (JSON-RPC over stdio).
 *
 * Reads line-delimited JSON requests from stdin, dispatches to a method
 * handler, writes one JSON response per line to stdout. Errors land on
 * stderr (Python parent drains them).
 *
 * Wire format:
 *   > {"id":"<uuid>","method":"<name>","params":{...}}
 *   < {"id":"<uuid>","ok":true,"data":{...}}
 *   < {"id":"<uuid>","ok":false,"error":"<message>"}
 */

import readline from "node:readline";
import process from "node:process";

import { htmlToMd } from "./pipelines/htmlToMd.js";
import { htmlToMdast } from "./pipelines/htmlToMdast.js";
import { mdToOfm } from "./pipelines/mdToOfm.js";
import { mdToNlcst } from "./pipelines/mdToNlcst.js";
import { astQuery } from "./pipelines/astQuery.js";
import { astConvert } from "./pipelines/astConvert.js";
import { analyze } from "./pipelines/analyze.js";
import { vaultPage, vaultMoc, vaultCanvas } from "./vault.js";

/**
 * Map of supported JSON-RPC method names to async handlers.
 * Each handler receives the request `params` object and returns the
 * response `data` payload (anything JSON-serialisable).
 *
 * @type {Record<string, (params: any) => Promise<any> | any>}
 */
const HANDLERS = {
  htmlToMd: (p) => htmlToMd(p?.html ?? "", { baseUrl: p?.baseUrl }),
  htmlToMdast: (p) => htmlToMdast(p?.html ?? ""),
  mdToOfm: (p) => mdToOfm(p?.markdown ?? "", p?.options ?? {}),
  mdToNlcst: (p) => mdToNlcst(p?.markdown ?? ""),
  astQuery: (p) => astQuery(p?.tree ?? null, p?.type ?? "mdast", p?.selector ?? ""),
  astConvert: (p) => astConvert(p?.input ?? "", p?.from ?? "", p?.to ?? ""),
  vaultPage: (p) => vaultPage(p?.html ?? "", p?.ctx ?? {}),
  vaultMoc: (p) => vaultMoc(p?.repo ?? "", p?.pages ?? [], p?.structure ?? []),
  vaultCanvas: (p) => vaultCanvas(p?.repo ?? "", p?.pages ?? [], p?.links ?? []),
  analyze: (p) => analyze(p?.markdown ?? ""),
  /**
   * The actual unified-language-server binds to its own stdio process via
   * lsp.js. This stub exists so the sidecar acknowledges the call without
   * trying to start a server inside this process.
   */
  lsp: (_p) => ({ ok: true, note: "lsp runs as a separate entry point (lsp.js)" }),
};

/**
 * Write a JSON-RPC response line to stdout.
 *
 * @param {string|undefined} id - Original request id (echoed back).
 * @param {boolean} ok - Success flag.
 * @param {any} payload - On success, the data; on failure, the error string.
 */
function writeResponse(id, ok, payload) {
  const out = ok
    ? { id, ok: true, data: payload }
    : { id, ok: false, error: payload };
  process.stdout.write(JSON.stringify(out) + "\n");
}

/**
 * Dispatch a single request line.
 *
 * @param {string} line - Raw JSON line.
 */
async function handleLine(line) {
  const trimmed = line.trim();
  if (!trimmed) return;
  let req;
  try {
    req = JSON.parse(trimmed);
  } catch (err) {
    writeResponse(undefined, false, `invalid JSON: ${err.message}`);
    return;
  }
  const { id, method, params } = req || {};
  const handler = HANDLERS[method];
  if (!handler) {
    writeResponse(id, false, `unknown method: ${method}`);
    return;
  }
  try {
    const data = await handler(params || {});
    writeResponse(id, true, data);
  } catch (err) {
    const msg = err && err.stack ? `${method} failed: ${err.message}\n${err.stack}` : `${method} failed: ${err}`;
    writeResponse(id, false, msg);
  }
}

const rl = readline.createInterface({
  input: process.stdin,
  output: undefined,
  terminal: false,
});

// Serialize handlers — each line waits for its predecessor before writing.
let chain = Promise.resolve();
rl.on("line", (line) => {
  chain = chain.then(() => handleLine(line)).catch((err) => {
    process.stderr.write(`[unified_engine] internal: ${err}\n`);
  });
});

rl.on("close", () => {
  // Drain in-flight handlers, then exit cleanly.
  chain.finally(() => process.exit(0));
});

process.on("uncaughtException", (err) => {
  process.stderr.write(`[unified_engine] uncaught: ${err.stack || err}\n`);
});
process.on("unhandledRejection", (err) => {
  process.stderr.write(`[unified_engine] unhandled: ${err}\n`);
});
