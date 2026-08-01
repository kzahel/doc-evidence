import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { App } from "../src/App";
import { FixtureRuntime } from "../src/api/fixtureRuntime";
import { RuntimeProvider } from "../src/api/RuntimeProvider";
import {
  DEFAULT_SOURCE_PANE_PERCENT,
  useWorkspaceStore,
} from "../src/state/workspaceStore";
import { detail, documentId, documents, pageGroups, workspace } from "./fixtures";

function renderApp(runtime: FixtureRuntime) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <RuntimeProvider runtime={runtime}>
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>
    </RuntimeProvider>,
  );
}

describe("application states", () => {
  beforeEach(() => {
    useWorkspaceStore.setState({
      activeLibraryId: null,
      selectedDocumentId: null,
      page: 1,
      searchQuery: "",
      fontScale: 1.2,
      libraryCollapsed: false,
      sourcePanePercent: DEFAULT_SOURCE_PANE_PERCENT,
      textPresentationMode: "auto",
      reviewMode: "focused",
      comparisonView: "diff",
      activeGroupId: null,
    });
  });

  it("shows an actionable empty catalog state", async () => {
    renderApp(
      new FixtureRuntime({
        workspace: { ...workspace, document_count: 0, source_occurrence_count: 0 },
        documents: { ...documents, total: 0, items: [] },
      }),
    );
    expect(await screen.findByText("The catalog is empty.")).toBeInTheDocument();
    expect(screen.getByText(/Select a document/)).toBeInTheDocument();
  });

  it("shows an actionable library home when no library is registered", async () => {
    renderApp(
      new FixtureRuntime({
        workspace,
        documents,
        app: {
          schema_version: 1,
          active_library_id: null,
          default_library_id: null,
          last_library_id: null,
        },
        libraries: { schema_version: 1, items: [] },
      }),
    );
    expect(await screen.findByText(/No libraries are registered/)).toBeInTheDocument();
    expect(screen.getByText(/doc-evidence library-register --config PATH/)).toBeInTheDocument();
  });

  it("switches explicit library identity and exposes collection settings", async () => {
    const user = userEvent.setup();
    const secondLibrary = {
      library_id: "second-library",
      name: "Second Library",
      store_mode: "managed" as const,
      collection_count: 1,
      last_opened_at: null,
      status: "ready" as const,
      status_detail: null,
      is_default: false,
      is_active: false,
    };
    renderApp(
      new FixtureRuntime({
        workspace,
        documents,
        details: { [documentId]: detail },
        groups: { [`${documentId}|1`]: pageGroups },
        libraries: {
          schema_version: 1,
          items: [
            {
              library_id: workspace.library_id,
              name: workspace.library_name,
              store_mode: "adopted",
              collection_count: 1,
              last_opened_at: null,
              status: "ready",
              status_detail: null,
              is_default: true,
              is_active: true,
            },
            secondLibrary,
          ],
        },
      }),
    );
    const selector = await screen.findByRole("combobox", { name: "Active library" });
    await user.selectOptions(selector, secondLibrary.library_id);
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Active library" })).toHaveValue(
        secondLibrary.library_id,
      ),
    );
    expect(await screen.findByText("Library settings · 1 collection(s)")).toBeInTheDocument();
    expect(window.location.search).toContain("library=second-library");
  });

  it("shows a bounded workspace failure", async () => {
    renderApp(new FixtureRuntime({ workspace, documents, error: new Error("catalog unavailable") }));
    expect(await screen.findByText("Application state unavailable")).toBeInTheDocument();
    expect(screen.getByText("catalog unavailable")).toBeInTheDocument();
  });

  it("uses named global typography presets with Normal as the default", async () => {
    const user = userEvent.setup();
    renderApp(
      new FixtureRuntime({
        workspace,
        documents,
        details: { [documentId]: detail },
        groups: { [`${documentId}|1`]: pageGroups },
      }),
    );
    const normal = await screen.findByRole("button", { name: "Normal" });
    expect(normal).toHaveAttribute("aria-pressed", "true");
    expect(document.documentElement.style.getPropertyValue("--font-scale")).toBe("1.2");

    await user.click(screen.getByRole("button", { name: "Small" }));
    expect(document.documentElement.style.getPropertyValue("--font-scale")).toBe("1");
    await user.click(screen.getByRole("button", { name: "Large" }));
    expect(document.documentElement.style.getPropertyValue("--font-scale")).toBe("1.3");
    expect(screen.getByRole("button", { name: "Large" })).toHaveAttribute("aria-pressed", "true");
  });

  it("explains image-only PDFs without implying that opening one starts OCR", async () => {
    renderApp(
      new FixtureRuntime({
        workspace,
        documents,
        details: { [documentId]: { ...detail, extraction_status: "image_only" } },
        groups: { [`${documentId}|1`]: pageGroups },
      }),
    );
    expect(await screen.findByText(/This PDF is image-only/)).toBeInTheDocument();
    expect(screen.getByText(/opening the document does not start OCR/)).toBeInTheDocument();
  });

  it("collapses the library and adjusts the evidence pane split by keyboard", async () => {
    const user = userEvent.setup();
    renderApp(
      new FixtureRuntime({
        workspace,
        documents,
        details: { [documentId]: detail },
        groups: { [`${documentId}|1`]: pageGroups },
      }),
    );

    await user.click(await screen.findByRole("button", { name: "Collapse document library" }));
    expect(screen.getByRole("button", { name: "Expand document library" })).toBeInTheDocument();
    expect(useWorkspaceStore.getState().libraryCollapsed).toBe(true);
    await user.click(screen.getByRole("button", { name: "Expand document library" }));
    expect(screen.getByRole("button", { name: "Collapse document library" })).toBeInTheDocument();

    const separator = await screen.findByRole("separator", {
      name: "Resize source and extraction panes",
    });
    separator.focus();
    await user.keyboard("{ArrowRight}");
    expect(useWorkspaceStore.getState().sourcePanePercent).toBe(47);
    await user.keyboard("{Home}");
    expect(useWorkspaceStore.getState().sourcePanePercent).toBe(
      DEFAULT_SOURCE_PANE_PERCENT,
    );
  });

  it("keeps prominent buttons and direct entry in the source-page toolbar", async () => {
    const user = userEvent.setup();
    const fourPageDetail = { ...detail, page_count: 4 };
    const pageData = Object.fromEntries(
      [1, 2, 3, 4].map((page) => [
        `${documentId}|${page}`,
        { ...pageGroups, page, page_count: 4 },
      ]),
    );
    renderApp(
      new FixtureRuntime({
        workspace,
        documents: {
          ...documents,
          items: [{ ...documents.items[0]!, page_count: 4 }],
        },
        details: { [documentId]: fourPageDetail },
        groups: pageData,
      }),
    );

    const previous = await screen.findByRole("button", { name: "Previous page" });
    const next = screen.getByRole("button", { name: "Next page" });
    expect(previous).toBeDisabled();
    expect(next).toBeEnabled();
    await user.click(next);
    expect(useWorkspaceStore.getState().page).toBe(2);

    const input = screen.getByRole("spinbutton", { name: "Current page" });
    await user.clear(input);
    await user.type(input, "4{Enter}");
    expect(useWorkspaceStore.getState().page).toBe(4);
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });
});
