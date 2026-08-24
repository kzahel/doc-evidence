import assert from "node:assert/strict";
import test from "node:test";
import { validateDesktopRelease } from "./validate-desktop-release.mjs";

const tag = "desktop-v1.2.3";
const repository = "kzahel/doc-evidence";
const version = "1.2.3";
const digest = `sha256:${"a".repeat(64)}`;

function fixture() {
  const updaterAssets = {
    "darwin-aarch64": "Doc.Evidence_aarch64.app.tar.gz",
    "windows-x86_64": `Doc.Evidence_${version}_x64-setup.exe`,
  };
  const names = new Set([
    `Doc-Evidence_${version}_aarch64.dmg`,
    `Doc.Evidence_${version}_x64-setup.exe`,
    `Doc-Evidence_${version}_compliance-preflight.tar.gz`,
    "latest.json",
  ]);
  for (const name of Object.values(updaterAssets)) {
    names.add(name);
    names.add(`${name}.sig`);
  }
  return {
    release: {
      tagName: tag,
      isDraft: true,
      assets: [...names].map((name) => ({ name, digest })),
    },
    latest: {
      version,
      platforms: Object.fromEntries(
        Object.entries(updaterAssets).map(([platform, name]) => [
          platform,
          {
            signature: "signed-updater-metadata-that-is-long-enough",
            url: `https://github.com/${repository}/releases/download/${tag}/${name}`,
          },
        ]),
      ),
    },
  };
}

test("accepts one complete two-target draft", () => {
  const result = validateDesktopRelease({ ...fixture(), tag, repository });
  assert.equal(result.version, version);
  assert.deepEqual(result.platforms, ["darwin-aarch64", "windows-x86_64"]);
});

test("rejects an already-public release", () => {
  const data = fixture();
  data.release.isDraft = false;
  assert.throws(
    () => validateDesktopRelease({ ...data, tag, repository }),
    /remain a draft/,
  );
});

test("rejects missing or extra updater targets", () => {
  const missing = fixture();
  delete missing.latest.platforms["windows-x86_64"];
  assert.throws(
    () => validateDesktopRelease({ ...missing, tag, repository }),
    /must contain exactly/,
  );

  const extra = fixture();
  extra.latest.platforms["linux-x86_64"] = {
    signature: "signed-updater-metadata-that-is-long-enough",
    url: "https://example.test/linux.AppImage",
  };
  assert.throws(
    () => validateDesktopRelease({ ...extra, tag, repository }),
    /must contain exactly/,
  );
});

test("rejects updater URLs outside the tagged release", () => {
  const data = fixture();
  data.latest.platforms["windows-x86_64"].url = "https://example.test/setup.exe";
  assert.throws(
    () => validateDesktopRelease({ ...data, tag, repository }),
    /unexpected URL/,
  );
});

test("rejects a wrong updater package type", () => {
  const data = fixture();
  const wrong = "Doc.Evidence_aarch64.dmg";
  data.latest.platforms["darwin-aarch64"].url =
    `https://github.com/${repository}/releases/download/${tag}/${wrong}`;
  data.release.assets.push(
    { name: wrong, digest },
    { name: `${wrong}.sig`, digest },
  );
  assert.throws(
    () => validateDesktopRelease({ ...data, tag, repository }),
    /must use \.app\.tar\.gz/,
  );
});

test("rejects missing direct installers, compliance, and asset digests", () => {
  for (const pattern of [/aarch64\.dmg$/, /compliance-preflight/, /x64-setup\.exe$/]) {
    const data = fixture();
    data.release.assets = data.release.assets.filter((asset) => !pattern.test(asset.name));
    assert.throws(() => validateDesktopRelease({ ...data, tag, repository }), /missing|required|expected/);
  }

  const data = fixture();
  data.release.assets[0].digest = null;
  assert.throws(
    () => validateDesktopRelease({ ...data, tag, repository }),
    /missing a GitHub SHA-256 digest/,
  );
});
