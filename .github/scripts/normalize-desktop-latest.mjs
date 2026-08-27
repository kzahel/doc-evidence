#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const PLATFORM_ALIASES = {
  "darwin-aarch64": "darwin-aarch64-app",
  "windows-x86_64": "windows-x86_64-nsis",
};

function fail(message) {
  throw new Error(message);
}

export function normalizeDesktopLatest(latest) {
  if (!latest || typeof latest !== "object" || Array.isArray(latest)) {
    fail("latest.json must be an object");
  }
  if (!latest.platforms || typeof latest.platforms !== "object" || Array.isArray(latest.platforms)) {
    fail("latest.json platforms are missing");
  }

  const allowed = new Set([
    ...Object.keys(PLATFORM_ALIASES),
    ...Object.values(PLATFORM_ALIASES),
  ]);
  const unexpected = Object.keys(latest.platforms).filter((name) => !allowed.has(name));
  if (unexpected.length > 0) {
    fail(`latest.json contains unexpected platform aliases: ${unexpected.join(", ")}`);
  }

  const platforms = {};
  for (const [platform, alias] of Object.entries(PLATFORM_ALIASES)) {
    const metadata = latest.platforms[platform];
    if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
      fail(`latest.json is missing canonical platform ${platform}`);
    }
    const aliasMetadata = latest.platforms[alias];
    if (aliasMetadata !== undefined) {
      try {
        assert.deepStrictEqual(aliasMetadata, metadata);
      } catch {
        fail(`latest.json alias ${alias} differs from ${platform}`);
      }
    }
    platforms[platform] = metadata;
  }
  return { ...latest, platforms };
}

function run(path) {
  const latest = JSON.parse(fs.readFileSync(path, "utf8"));
  const normalized = normalizeDesktopLatest(latest);
  fs.writeFileSync(path, `${JSON.stringify(normalized, null, 2)}\n`);
  console.log(`Normalized desktop updater metadata: ${Object.keys(normalized.platforms).join(", ")}`);
}

if (fileURLToPath(import.meta.url) === process.argv[1]) {
  try {
    if (process.argv.length !== 3) fail("usage: normalize-desktop-latest.mjs PATH");
    run(process.argv[2]);
  } catch (error) {
    console.error(`Desktop updater normalization failed: ${error.message}`);
    process.exitCode = 1;
  }
}
