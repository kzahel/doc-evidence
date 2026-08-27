#!/usr/bin/env node

import fs from "node:fs";

function fail(message) {
  throw new Error(message);
}

function requireMatch(path, pattern, expected) {
  const content = fs.readFileSync(path, "utf8");
  const match = content.match(pattern);
  if (!match) fail(`could not read version from ${path}`);
  if (match[1] !== expected) {
    fail(`${path} has version ${match[1]}, expected ${expected}`);
  }
}

const tagIndex = process.argv.indexOf("--tag");
const tag = tagIndex >= 0 ? process.argv[tagIndex + 1] : undefined;
if (!tag || !/^desktop-v\d+\.\d+\.\d+$/.test(tag)) {
  fail(`expected --tag desktop-vMAJOR.MINOR.PATCH, received ${tag ?? "<none>"}`);
}
const version = tag.slice("desktop-v".length);
requireMatch("pyproject.toml", /^version = "([^"]+)"/m, version);
requireMatch("src/doc_evidence/__init__.py", /^__version__ = "([^"]+)"/m, version);
requireMatch("desktop/src-tauri/Cargo.toml", /^version = "([^"]+)"/m, version);

for (const path of [
  "desktop/src-tauri/tauri.conf.json",
  "desktop/package.json",
  "web/package.json",
]) {
  const value = JSON.parse(fs.readFileSync(path, "utf8"));
  if (value.version !== version) fail(`${path} has version ${value.version}, expected ${version}`);
}

const changelog = fs.readFileSync("CHANGELOG.md", "utf8");
if (!changelog.includes(`## [${version}]`)) {
  fail(`CHANGELOG.md has no ${version} entry`);
}
console.log(`Desktop release versions agree at ${version}`);
