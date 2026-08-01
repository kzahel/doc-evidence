import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { App } from "../src/App";
import { FixtureRuntime } from "../src/api/fixtureRuntime";
import { RuntimeProvider } from "../src/api/RuntimeProvider";
import { useWorkspaceStore } from "../src/state/workspaceStore";
import { documents, workspace } from "./fixtures";

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
    useWorkspaceStore.setState({ selectedDocumentId: null, page: 1, searchQuery: "" });
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
});
