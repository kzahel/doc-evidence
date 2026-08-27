import assert from "node:assert/strict";
import test from "node:test";
import { normalizeDesktopLatest } from "./normalize-desktop-latest.mjs";

function fixture() {
  const macos = { signature: "macos-signature", url: "https://example.test/macos" };
  const windows = { signature: "windows-signature", url: "https://example.test/windows" };
  return {
    version: "1.2.3",
    notes: "notes",
    platforms: {
      "darwin-aarch64": macos,
      "darwin-aarch64-app": { ...macos },
      "windows-x86_64": windows,
      "windows-x86_64-nsis": { ...windows },
    },
  };
}

test("removes only equal Tauri package aliases", () => {
  const normalized = normalizeDesktopLatest(fixture());
  assert.deepEqual(Object.keys(normalized.platforms), ["darwin-aarch64", "windows-x86_64"]);
  assert.equal(normalized.version, "1.2.3");
  assert.equal(normalized.notes, "notes");
});

test("accepts already normalized updater metadata", () => {
  const latest = fixture();
  delete latest.platforms["darwin-aarch64-app"];
  delete latest.platforms["windows-x86_64-nsis"];
  assert.deepEqual(normalizeDesktopLatest(latest), latest);
});

test("rejects mismatched and unexpected aliases", () => {
  const mismatched = fixture();
  mismatched.platforms["windows-x86_64-nsis"].url = "https://example.test/wrong";
  assert.throws(() => normalizeDesktopLatest(mismatched), /differs/);

  const unexpected = fixture();
  unexpected.platforms["linux-x86_64"] = {};
  assert.throws(() => normalizeDesktopLatest(unexpected), /unexpected/);
});

test("rejects a missing canonical platform", () => {
  const latest = fixture();
  delete latest.platforms["darwin-aarch64"];
  assert.throws(() => normalizeDesktopLatest(latest), /missing canonical/);
});
