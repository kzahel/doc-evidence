import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { FixtureRuntime, comparisonKey } from "../src/api/fixtureRuntime";
import { RuntimeProvider } from "../src/api/RuntimeProvider";
import { ComparisonPanel } from "../src/components/ComparisonPanel";
import { OutputGroups } from "../src/components/OutputGroups";
import { useWorkspaceStore } from "../src/state/workspaceStore";
import {
  comparison,
  detail,
  documentId,
  documents,
  equivalentComparison,
  groups,
  pageGroups,
  workspace,
} from "./fixtures";

function runtime() {
  return new FixtureRuntime({
    workspace,
    documents,
    details: { [documentId]: detail },
    groups: { [`${documentId}|1`]: pageGroups },
    comparisons: {
      [comparisonKey({
        document_id: documentId,
        page: 1,
        left_run_ref: "run:native",
        right_run_ref: "run:layout",
      })]: comparison,
      [comparisonKey({
        document_id: documentId,
        page: 1,
        left_run_ref: "run:layout",
        right_run_ref: "run:layout",
      })]: equivalentComparison,
    },
  });
}

function wrapper(children: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <RuntimeProvider runtime={runtime()}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </RuntimeProvider>,
  );
}

describe("comparison workspace", () => {
  beforeEach(() => {
    useWorkspaceStore.setState({
      baselineGroupId: "group:native",
      comparisonGroupId: "group:layout",
      diffMode: "differences",
      numericIndex: 0,
    });
  });

  it("collapses exact output and labels every contributing run", () => {
    wrapper(<OutputGroups data={pageGroups} />);
    expect(screen.getByText("Identical output from 2 runs")).toBeInTheDocument();
    expect(screen.getByText("poppler")).toBeInTheDocument();
    expect(screen.getByText("ocrmypdf-tesseract")).toBeInTheDocument();
  });

  it("opens raw artifacts in a bounded preview", async () => {
    const user = userEvent.setup();
    const withArtifact = structuredClone(pageGroups);
    withArtifact.groups[0]!.runs[0]!.raw_artifacts = [
      {
        artifact_id: "artifact:fixture",
        label: "raw.txt",
        media_type: "text/plain",
        size_bytes: 16,
      },
    ];
    wrapper(<OutputGroups data={withArtifact} />);

    await user.click(screen.getByText("poppler"));
    await user.click(screen.getByRole("button", { name: /raw\.txt/ }));
    const dialog = await screen.findByRole("dialog", { name: /Raw artifact: raw\.txt/ });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByTitle(/Raw artifact preview/)).toHaveAttribute("sandbox", "");
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(dialog).not.toBeInTheDocument();
  });

  it("switches diff density, navigates numbers, and changes the baseline", async () => {
    const user = userEvent.setup();
    wrapper(<ComparisonPanel documentId={documentId} page={1} groups={groups} />);
    expect(await screen.findByText("2 numeric discrepancies")).toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next numeric discrepancy" }));
    expect(screen.getByText("2 / 2")).toBeInTheDocument();
    expect(screen.queryByText("equal")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Full aligned output" }));
    expect(screen.getAllByText("equal")).toHaveLength(2);

    await user.selectOptions(screen.getByRole("combobox", { name: "Baseline output" }), "group:layout");
    expect(await screen.findByText("The selected outputs are exactly identical.")).toBeInTheDocument();
  });
});
