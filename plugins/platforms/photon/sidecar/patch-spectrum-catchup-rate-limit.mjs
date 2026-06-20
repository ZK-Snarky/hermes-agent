#!/usr/bin/env node
// Patch spectrum-ts so a Photon `EventService.CatchUpEvents` RESOURCE_EXHAUSTED
// reply (the documented per-line "catchUpEvents concurrency limit (16) reached"
// signal) is treated like a CursorRejectedError instead of a generic retryable
// error.
//
// Why this matters
// ----------------
// spectrum-ts' `resumableOrderedStream` reconnect loop opens BOTH a fresh
// `subscribeLive` and a fresh `catchUp` on every retry whenever it has a
// `lastCursor`. If the server is at concurrency cap, the catch-up call fails
// immediately, the live consume is torn down with it, the SDK backs off (cap
// 30s), then opens a new pair of streams — adding to the server-side stale
// stream pile. The retries never escape on their own, so inbound iMessages
// stop being delivered for hours until the gateway is restarted.
//
// The SDK already has a clean exit path for this exact shape: a
// `CursorRejectedError` from catch-up resets `lastCursor` and the next
// reconnect runs `consumeLive()` (no catch-up call), which releases the
// server-side slot and resumes the live stream. The Hermes Python adapter
// already dedupes inbound events by `messageId`, so accepting the catch-up gap
// is safe — any missed event that surfaces in a later catch-up will be
// deduped, and live events keep flowing.
//
// We map RateLimitError → CursorRejectedError by extending the
// `isCursorRejectedIMessageError` predicate that spectrum-ts already passes
// into both message and poll streams (chunk-WMG36LHW.js).
//
// Pinned to spectrum-ts 3.1.0 (see sidecar/package.json). Re-verify match
// against the dist when bumping the SDK; the patch fails closed if the target
// expression isn't found.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const MARKER = "Hermes patch: accept catchUpEvents concurrency RESOURCE_EXHAUSTED as cursor-rejected";

const TARGET = "var isCursorRejectedIMessageError = (error) => error instanceof ValidationError;";
const REPLACEMENT = "var isCursorRejectedIMessageError = (error) => error instanceof ValidationError || (error != null && error.name === \"RateLimitError\" && typeof error.message === \"string\" && error.message.includes(\"catchUpEvents concurrency limit\"));";

function scriptDir() {
  return path.dirname(fileURLToPath(import.meta.url));
}

export function patchSpectrumCatchUpRateLimit(root = scriptDir()) {
  const dist = path.join(root, "node_modules", "spectrum-ts", "dist");
  if (!fs.existsSync(dist)) {
    throw new Error(`spectrum-ts dist not found: ${dist}`);
  }
  const files = fs.readdirSync(dist)
    .filter((name) => name.endsWith(".js"))
    .map((name) => path.join(dist, name));

  for (const file of files) {
    const raw = fs.readFileSync(file, "utf8");
    if (raw.includes(MARKER)) {
      return { patched: false, file, reason: "already patched" };
    }
    // Normalize CRLF so a Windows checkout doesn't defeat the LF-only search
    // string; restore on write.
    const CR = String.fromCharCode(13);
    const CRLF = CR + "\n";
    const usedCRLF = raw.includes(CRLF);
    const original = usedCRLF ? raw.split(CRLF).join("\n") : raw;
    if (!original.includes(TARGET)) {
      continue;
    }
    const count = original.split(TARGET).length - 1;
    if (count !== 1) {
      throw new Error(
        `expected exactly one isCursorRejectedIMessageError match in ${file}, found ${count}`
      );
    }
    let patched = original.replace(TARGET, REPLACEMENT);
    patched = `// ${MARKER}\n${patched}`;
    if (usedCRLF) {
      patched = patched.split("\n").join(CRLF);
    }
    fs.writeFileSync(file, patched, "utf8");
    return { patched: true, file };
  }
  throw new Error(
    "could not find isCursorRejectedIMessageError in spectrum-ts dist — " +
      "the SDK may have changed; update the catch-up rate-limit patch"
  );
}

const _invokedDirectly =
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href;
if (_invokedDirectly) {
  try {
    const root = process.argv[2] ? path.resolve(process.argv[2]) : scriptDir();
    const result = patchSpectrumCatchUpRateLimit(root);
    const action = result.patched ? "patched" : "ok";
    console.error(`photon-sidecar: spectrum catch-up rate-limit patch ${action}: ${result.file}`);
  } catch (err) {
    console.error(`photon-sidecar: spectrum catch-up rate-limit patch failed: ${err?.stack || err}`);
    process.exit(1);
  }
}
