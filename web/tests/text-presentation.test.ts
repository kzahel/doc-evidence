import { describe, expect, it } from "vitest";

import {
  recommendTextPresentation,
  resolveTextPresentation,
} from "../src/presentation/textPresentation";

describe("extraction text presentation", () => {
  it("recommends aligned mode for repeated whitespace columns", () => {
    const result = recommendTextPresentation([
      [
        "Description        Amount      Year",
        "Checking           1,200.00    2023",
        "Retirement       100,000.00    2023",
        "Mortgage         450,000.00    2023",
      ].join("\n"),
    ]);
    expect(result.mode).toBe("aligned");
    expect(result.reason).toMatch(/column|spacing/);
  });

  it("recommends reading mode for ordinary prose", () => {
    const result = recommendTextPresentation([
      "This is a normal paragraph.\nIt contains another sentence.\nNothing relies on columns.",
    ]);
    expect(result.mode).toBe("reading");
  });

  it("always honors a manual override", () => {
    expect(resolveTextPresentation("aligned", ["ordinary prose"]).mode).toBe("aligned");
    expect(resolveTextPresentation("reading", ["a  b\nc  d\ne  f"]).mode).toBe("reading");
  });
});
