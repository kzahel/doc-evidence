import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
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
        right_run_ref: "run:native",
      })]: {
        ...comparison,
        left_run_ref: "run:layout",
        right_run_ref: "run:native",
      },
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
      textPresentationMode: "auto",
      reviewMode: "focused",
      comparisonView: "diff",
      activeGroupId: null,
    });
  });

  it("collapses exact output and labels every contributing run", () => {
    wrapper(<OutputGroups data={pageGroups} />);
    expect(screen.getByText(/3 cached runs/)).toBeInTheDocument();
    expect(screen.getByText("Identical output from 2 runs")).toBeInTheDocument();
    expect(screen.getByText("poppler")).toBeInTheDocument();
    expect(screen.getByText("ocrmypdf-tesseract")).toBeInTheDocument();
  });

  it("explains when only one cached extractor run exists", () => {
    const single = { ...groups[0]!, runs: [groups[0]!.runs[0]!] };
    wrapper(<ComparisonPanel documentId={documentId} page={1} groups={[single]} />);
    expect(screen.getByText(/Only one cached extractor run is available/)).toBeInTheDocument();
    expect(screen.getByText(/does not launch missing extractors/)).toBeInTheDocument();
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

  it("switches between reading and alignment-preserving extraction text", async () => {
    const user = userEvent.setup();
    const view = wrapper(<OutputGroups data={pageGroups} />);
    expect(screen.getByRole("button", { name: "Auto" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText(/Auto chose reading/)).toBeInTheDocument();
    expect(view.container.querySelector('pre[data-presentation="reading"]')).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Aligned" }));
    expect(screen.getByRole("button", { name: "Aligned" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(view.container.querySelector('pre[data-presentation="aligned"]')).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reading" }));
    expect(view.container.querySelector('pre[data-presentation="reading"]')).toBeInTheDocument();
  });

  it("switches between focused, stacked, and integrated comparison modes", async () => {
    const user = userEvent.setup();
    const view = wrapper(<OutputGroups data={pageGroups} />);

    expect(screen.getByRole("button", { name: "Focused" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(view.container.querySelector('[data-review-mode="focused"]')).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /2 docling-standard/ }));
    expect(screen.getByRole("heading", { name: "docling-standard" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Stacked" }));
    expect(view.container.querySelector('[data-review-mode="stacked"]')).toBeInTheDocument();
    expect(screen.getByText("Identical output from 2 runs")).toBeInTheDocument();

    await user.click(
      within(screen.getByRole("group", { name: "Review mode" })).getByRole("button", {
        name: "Compare",
      }),
    );
    expect(await screen.findByText("2 numeric discrepancies")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Extractor comparison" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Raw two-up" }));
    expect(screen.getByLabelText("Raw extractor outputs")).toBeInTheDocument();
    expect(view.container.querySelectorAll("[data-presentation]")).toHaveLength(2);
  });

  it("switches diff density, navigates numbers, and keeps the sides distinct", async () => {
    const user = userEvent.setup();
    wrapper(<ComparisonPanel documentId={documentId} page={1} groups={groups} />);
    expect(await screen.findByText("2 numeric discrepancies")).toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next numeric discrepancy" }));
    expect(screen.getByText("2 / 2")).toBeInTheDocument();
    expect(screen.queryByText("equal")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Full aligned output" }));
    expect(screen.getAllByText("equal")).toHaveLength(2);

    const baseline = screen.getByRole("combobox", { name: "Baseline output" });
    const comparisonOutput = screen.getByRole("combobox", { name: "Comparison output" });
    expect(baseline.querySelector('option[value="group:layout"]')).toBeDisabled();
    expect(comparisonOutput.querySelector('option[value="group:native"]')).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Swap comparison direction" }));
    expect(baseline).toHaveValue("group:layout");
    expect(comparisonOutput).toHaveValue("group:native");
  });
});
