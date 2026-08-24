#!/usr/bin/env node

import fs from "node:fs";
import { fileURLToPath } from "node:url";

const REQUIRED_PLATFORMS = ["darwin-aarch64", "windows-x86_64"];

function fail(message) {
  throw new Error(message);
}

function requireAsset(assetNames, name) {
  if (!assetNames.has(name)) fail(`missing required release asset: ${name}`);
}

function requireOneMatchingAsset(assetNames, pattern, label) {
  const matches = [...assetNames].filter((name) => pattern.test(name));
  if (matches.length !== 1) {
    fail(`expected exactly one ${label}, found ${matches.length}: ${matches.join(", ")}`);
  }
  return matches[0];
}

function escapePattern(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function validateDesktopRelease({ release, latest, tag, repository }) {
  if (!/^desktop-v\d+\.\d+\.\d+$/.test(tag)) fail(`unexpected desktop tag: ${tag}`);
  const version = tag.slice("desktop-v".length);
  if (release.tagName !== tag) fail(`release tag ${release.tagName} does not match ${tag}`);
  if (!release.isDraft) fail("release must remain a draft until validation succeeds");
  if (!Array.isArray(release.assets)) fail("release assets are missing");

  const assetNames = new Set();
  for (const asset of release.assets) {
    if (!asset.name || assetNames.has(asset.name)) {
      fail(`missing or duplicate release asset name: ${asset.name ?? "<empty>"}`);
    }
    assetNames.add(asset.name);
    if (!/^sha256:[0-9a-f]{64}$/i.test(asset.digest ?? "")) {
      fail(`release asset ${asset.name} is missing a GitHub SHA-256 digest`);
    }
  }

  requireAsset(assetNames, "latest.json");
  const escapedVersion = escapePattern(version);
  requireOneMatchingAsset(
    assetNames,
    new RegExp(`_${escapedVersion}_aarch64\\.dmg$`),
    "macOS Apple-silicon DMG",
  );
  requireOneMatchingAsset(
    assetNames,
    new RegExp(`_${escapedVersion}_x64-setup\\.exe$`),
    "Windows x86_64 NSIS installer",
  );
  requireOneMatchingAsset(
    assetNames,
    new RegExp(`_${escapedVersion}_compliance-preflight\\.tar\\.gz$`),
    "exact-source compliance archive",
  );

  if (latest.version !== version) {
    fail(`latest.json version ${latest.version} does not match ${version}`);
  }
  if (!latest.platforms || typeof latest.platforms !== "object" || Array.isArray(latest.platforms)) {
    fail("latest.json platforms are missing");
  }
  const actualPlatforms = Object.keys(latest.platforms).sort();
  if (JSON.stringify(actualPlatforms) !== JSON.stringify(REQUIRED_PLATFORMS)) {
    fail(`latest.json must contain exactly ${REQUIRED_PLATFORMS.join(", ")}`);
  }

  const expectedUrlPrefix = `https://github.com/${repository}/releases/download/${tag}/`;
  for (const platform of REQUIRED_PLATFORMS) {
    const metadata = latest.platforms[platform];
    if (!metadata || typeof metadata !== "object") {
      fail(`latest.json is missing platform ${platform}`);
    }
    if (typeof metadata.signature !== "string" || metadata.signature.length < 32) {
      fail(`latest.json platform ${platform} has no usable signature`);
    }
    if (typeof metadata.url !== "string" || !metadata.url.startsWith(expectedUrlPrefix)) {
      fail(`latest.json platform ${platform} has an unexpected URL: ${metadata.url}`);
    }
    const assetName = decodeURIComponent(metadata.url.slice(expectedUrlPrefix.length));
    requireAsset(assetNames, assetName);
    requireAsset(assetNames, `${assetName}.sig`);
    const expectedSuffix = platform === "darwin-aarch64" ? ".app.tar.gz" : "-setup.exe";
    if (!assetName.endsWith(expectedSuffix)) {
      fail(`updater for ${platform} must use ${expectedSuffix}: ${assetName}`);
    }
  }
  return { version, platforms: [...REQUIRED_PLATFORMS] };
}

function readJson(path) {
  return JSON.parse(fs.readFileSync(path, "utf8"));
}

function parseArguments(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    const name = argv[index];
    const value = argv[index + 1];
    if (!name?.startsWith("--") || value === undefined) fail(`invalid argument near ${name ?? "<end>"}`);
    result[name.slice(2)] = value;
  }
  for (const name of ["release", "latest", "tag", "repository"]) {
    if (!result[name]) fail(`missing --${name}`);
  }
  return result;
}

if (fileURLToPath(import.meta.url) === process.argv[1]) {
  try {
    const args = parseArguments(process.argv.slice(2));
    const result = validateDesktopRelease({
      release: readJson(args.release),
      latest: readJson(args.latest),
      tag: args.tag,
      repository: args.repository,
    });
    console.log(`Validated complete draft desktop release ${result.version}`);
  } catch (error) {
    console.error(`Desktop release validation failed: ${error.message}`);
    process.exitCode = 1;
  }
}
