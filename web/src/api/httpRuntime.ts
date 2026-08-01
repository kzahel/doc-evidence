import { createGeneratedClient } from "./generated/client";
import type { DocEvidenceRuntime, SearchInput } from "./runtime";

function failure(error: unknown, response?: Response): Error {
  if (error && typeof error === "object" && "message" in error) {
    return new Error(String(error.message));
  }
  return new Error(
    response ? `Local API request failed (${response.status})` : "Local API request failed",
  );
}

export function createHttpRuntime(baseUrl: string, launchToken: string): DocEvidenceRuntime {
  const client = createGeneratedClient(baseUrl, launchToken);
  return {
    async getWorkspace(signal) {
      const { data, error, response } = await client.GET("/api/v1/workspace", { signal });
      if (!data) throw failure(error, response);
      return data;
    },
    async listDocuments(offset, limit, signal) {
      const { data, error, response } = await client.GET("/api/v1/documents", {
        params: { query: { offset, limit } },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async getDocument(documentId, signal) {
      const { data, error, response } = await client.GET("/api/v1/documents/{document_id}", {
        params: { path: { document_id: documentId } },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async search(input: SearchInput, signal) {
      const { data, error, response } = await client.GET("/api/v1/search", {
        params: {
          query: { query: input.query, mode: input.mode, limit: input.limit ?? 40 },
        },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async getPageGroups(documentId, page, signal) {
      const { data, error, response } = await client.GET(
        "/api/v1/documents/{document_id}/pages/{page}/groups",
        {
          params: { path: { document_id: documentId, page } },
          signal,
        },
      );
      if (!data) throw failure(error, response);
      return data;
    },
    async compare(input, signal) {
      const { data, error, response } = await client.POST("/api/v1/comparisons", {
        body: input,
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async getPageRender(documentId, page, signal) {
      const { data, error, response } = await client.GET(
        "/api/v1/documents/{document_id}/pages/{page}/render",
        {
          params: { path: { document_id: documentId, page } },
          parseAs: "blob",
          signal,
        },
      );
      if (!(data instanceof Blob)) throw failure(error, response);
      return data;
    },
    async getArtifact(artifactId, signal) {
      const { data, error, response } = await client.GET("/api/v1/artifacts/{artifact_id}", {
        params: { path: { artifact_id: artifactId } },
        parseAs: "blob",
        signal,
      });
      if (!(data instanceof Blob)) throw failure(error, response);
      return data;
    },
    async getDiagnostics(signal) {
      const { data, error, response } = await client.GET("/api/v1/diagnostics", { signal });
      if (!data) throw failure(error, response);
      return data;
    },
  };
}
