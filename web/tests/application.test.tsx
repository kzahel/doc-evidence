import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { App } from "../src/App";
import { FixtureRuntime } from "../src/api/fixtureRuntime";
import { RuntimeProvider } from "../src/api/RuntimeProvider";
import { useWorkspaceStore } from "../src/state/workspaceStore";
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
      selectedDocumentId: null,
      page: 1,
      searchQuery: "",
      fontScale: 1.2,
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

  it("shows a bounded workspace failure", async () => {
    renderApp(new FixtureRuntime({ workspace, documents, error: new Error("catalog unavailable") }));
    expect(await screen.findByText("Workspace unavailable")).toBeInTheDocument();
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
});
