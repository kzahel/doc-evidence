import { describe, expect, it } from "vitest";

import { progressPercent } from "../src/updater/state";

describe("desktop updater state", () => {
  it("bounds known download progress", () => {
    expect(progressPercent({
      phase: "downloading",
      version: "0.5.1",
      downloadedBytes: 120,
      totalBytes: 100,
    })).toBe(100);
  });

  it("keeps unknown-length downloads indeterminate", () => {
    expect(progressPercent({
      phase: "downloading",
      version: "0.5.1",
      downloadedBytes: 40,
    })).toBeUndefined();
  });
});
