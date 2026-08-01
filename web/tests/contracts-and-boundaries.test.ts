import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import payloads from "../../contracts/representative-payloads.json";
import type { ComparisonResult, WorkspaceSummary } from "../src/api/runtime";
import {
  clampSourcePanePercent,
  navigationFromSearch,
  useWorkspaceStore,
} from "../src/state/workspaceStore";

describe("contracts and component boundaries", () => {
  it("validates shared representative payload shapes in TypeScript", () => {
    const workspace = payloads.workspace as WorkspaceSummary;
    const comparison = payloads.comparison as ComparisonResult;
    expect(workspace.schema_version).toBe(1);
    expect(workspace.collections[0]?.collection_id).toBe("fixture");
    expect(comparison.comparison_algorithm_version).toBe("word_numeric_diff_v1");
    expect(comparison.numeric_discrepancies[0]?.left_values).toEqual(["123"]);
  });

  it("keeps endpoint and platform knowledge out of product components", () => {
    const root = path.resolve(import.meta.dirname, "../src/components");
    for (const filename of fs.readdirSync(root).filter((name) => name.endsWith(".tsx"))) {
      const content = fs.readFileSync(path.join(root, filename), "utf8");
      expect(content, filename).not.toMatch(/["'`]\/api\/v\d/);
      expect(content, filename).not.toContain("@tauri");
      expect(content, filename).not.toContain("node:fs");
    }
  });

  it("parses bounded direct document links", () => {
    const documentId = `sha256:${"a".repeat(64)}`;
    expect(navigationFromSearch(`?library=fixture-library&document=${documentId}&page=7`)).toEqual({
      libraryId: "fixture-library",
      documentId,
      page: 7,
    });
    expect(navigationFromSearch("?document=../../private&page=-2")).toEqual({
      libraryId: null,
      documentId: null,
      page: 1,
    });
  });

  it("sets a named typography preset and rejects an identical comparison pair", () => {
    useWorkspaceStore.setState({
      baselineGroupId: "group:native",
      comparisonGroupId: "group:layout",
      fontScale: 1.2,
      reviewMode: "focused",
      comparisonView: "diff",
    });
    useWorkspaceStore.getState().setFontScale(1.3);
    expect(useWorkspaceStore.getState().fontScale).toBe(1.3);
    useWorkspaceStore.getState().setComparisonGroups("group:native", "group:native");
    expect(useWorkspaceStore.getState().comparisonGroupId).toBeNull();
  });

  it("bounds the session-local source pane split", () => {
    expect(clampSourcePanePercent(5)).toBe(28);
    expect(clampSourcePanePercent(43.26)).toBe(43.3);
    expect(clampSourcePanePercent(99)).toBe(72);
  });
});
