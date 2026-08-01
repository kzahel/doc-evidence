import { createGeneratedClient } from "./generated/client";
import {
  NativeHostUnavailableError,
  unavailableHostCapabilities,
  type DocEvidenceRuntime,
  type SearchInput,
} from "./runtime";

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
    hostCapabilities: unavailableHostCapabilities,
    async createManagedLibrary() {
      throw new NativeHostUnavailableError("Native library creation is unavailable in this host.");
    },
    async registerExistingLibrary() {
      throw new NativeHostUnavailableError("Native library registration is unavailable in this host.");
    },
    async addCollection() {
      throw new NativeHostUnavailableError("Native collection selection is unavailable in this host.");
    },
    async getApp(signal) {
      const { data, error, response } = await client.GET("/api/v1/app", { signal });
      if (!data) throw failure(error, response);
      return data;
    },
    async listLibraries(signal) {
      const { data, error, response } = await client.GET("/api/v1/libraries", { signal });
      if (!data) throw failure(error, response);
      return data;
    },
    async getLibrary(libraryId, signal) {
      const { data, error, response } = await client.GET("/api/v1/libraries/{library_id}", {
        params: { path: { library_id: libraryId } },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async activateLibrary(libraryId, signal) {
      const { data, error, response } = await client.POST(
        "/api/v1/libraries/{library_id}/activate",
        { params: { path: { library_id: libraryId } }, signal },
      );
      if (!data) throw failure(error, response);
      return data;
    },
    async getWorkspace(libraryId, signal) {
      const { data, error, response } = await client.GET(
        "/api/v1/libraries/{library_id}/workspace",
        { params: { path: { library_id: libraryId } }, signal },
      );
      if (!data) throw failure(error, response);
      return data;
    },
    async listDocuments(libraryId, offset, limit, signal) {
      const { data, error, response } = await client.GET(
        "/api/v1/libraries/{library_id}/documents",
        {
        params: { path: { library_id: libraryId }, query: { offset, limit } },
        signal,
        },
      );
      if (!data) throw failure(error, response);
      return data;
    },
    async getDocument(libraryId, documentId, signal) {
      const { data, error, response } = await client.GET(
        "/api/v1/libraries/{library_id}/documents/{document_id}",
        { params: { path: { library_id: libraryId, document_id: documentId } }, signal },
      );
      if (!data) throw failure(error, response);
      return data;
    },
    async search(libraryId, input: SearchInput, signal) {
      const { data, error, response } = await client.GET("/api/v1/libraries/{library_id}/search", {
        params: {
          path: { library_id: libraryId },
          query: { query: input.query, mode: input.mode, limit: input.limit ?? 40 },
        },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async getPageGroups(libraryId, documentId, page, signal) {
      const { data, error, response } = await client.GET(
        "/api/v1/libraries/{library_id}/documents/{document_id}/pages/{page}/groups",
        {
          params: { path: { library_id: libraryId, document_id: documentId, page } },
          signal,
        },
      );
      if (!data) throw failure(error, response);
      return data;
    },
    async compare(libraryId, input, signal) {
      const { data, error, response } = await client.POST("/api/v1/libraries/{library_id}/comparisons", {
        params: { path: { library_id: libraryId } },
        body: input,
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async getPageRender(libraryId, documentId, page, signal) {
      const { data, error, response } = await client.GET(
        "/api/v1/libraries/{library_id}/documents/{document_id}/pages/{page}/render",
        {
          params: { path: { library_id: libraryId, document_id: documentId, page } },
          parseAs: "blob",
          signal,
        },
      );
      if (!(data instanceof Blob)) throw failure(error, response);
      return data;
    },
    async getArtifact(libraryId, artifactId, signal) {
      const { data, error, response } = await client.GET("/api/v1/libraries/{library_id}/artifacts/{artifact_id}", {
        params: { path: { library_id: libraryId, artifact_id: artifactId } },
        parseAs: "blob",
        signal,
      });
      if (response.ok && response.headers.get("content-length") === "0") {
        return new Blob([], {
          type: response.headers.get("content-type") ?? "application/octet-stream",
        });
      }
      if (!(data instanceof Blob)) throw failure(error, response);
      return data;
    },
    async getDiagnostics(libraryId, signal) {
      const { data, error, response } = await client.GET("/api/v1/libraries/{library_id}/diagnostics", {
        params: { path: { library_id: libraryId } }, signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async getExtractors(libraryId, documentId, signal) {
      const { data, error, response } = await client.GET("/api/v1/libraries/{library_id}/extractors", {
        params: { path: { library_id: libraryId }, query: { document_id: documentId } },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async createExtraction(libraryId, input, idempotencyKey, signal) {
      const { data, error, response } = await client.POST("/api/v1/libraries/{library_id}/jobs/extractions", {
        params: { path: { library_id: libraryId } },
        body: input,
        headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async createExtractionBatch(libraryId, input, idempotencyKey, signal) {
      const { data, error, response } = await client.POST("/api/v1/libraries/{library_id}/jobs/extraction-batches", {
        params: { path: { library_id: libraryId } },
        body: input,
        headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async preflightImageOnlyOcr(libraryId, signal) {
      const { data, error, response } = await client.GET("/api/v1/libraries/{library_id}/jobs/extraction-batches/preflight", {
        params: { path: { library_id: libraryId } },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async listJobs(libraryId, state, offset = 0, limit = 50, signal) {
      const { data, error, response } = await client.GET("/api/v1/libraries/{library_id}/jobs", {
        params: { path: { library_id: libraryId }, query: { state, offset, limit } },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async getJob(libraryId, jobId, signal) {
      const { data, error, response } = await client.GET("/api/v1/libraries/{library_id}/jobs/{job_id}", {
        params: { path: { library_id: libraryId, job_id: jobId } },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async getJobEvents(libraryId, jobId, after = 0, limit = 200, signal) {
      const { data, error, response } = await client.GET("/api/v1/libraries/{library_id}/jobs/{job_id}/events", {
        params: { path: { library_id: libraryId, job_id: jobId }, query: { after, limit } },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async cancelJob(libraryId, jobId, signal) {
      const { data, error, response } = await client.POST("/api/v1/libraries/{library_id}/jobs/{job_id}/cancel", {
        params: { path: { library_id: libraryId, job_id: jobId } },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async retryJob(libraryId, jobId, signal) {
      const { data, error, response } = await client.POST("/api/v1/libraries/{library_id}/jobs/{job_id}/retry", {
        params: { path: { library_id: libraryId, job_id: jobId } },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async repairJobProjection(libraryId, jobId, signal) {
      const { data, error, response } = await client.POST("/api/v1/libraries/{library_id}/jobs/{job_id}/repair-projection", {
        params: { path: { library_id: libraryId, job_id: jobId } },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async getAttemptDiagnostics(libraryId, jobId, attemptId, signal) {
      const { data, error, response } = await client.GET("/api/v1/libraries/{library_id}/jobs/{job_id}/attempts/{attempt_id}/diagnostics", {
        params: { path: { library_id: libraryId, job_id: jobId, attempt_id: attemptId } },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async listBatches(libraryId, offset = 0, limit = 50, signal) {
      const { data, error, response } = await client.GET("/api/v1/libraries/{library_id}/jobs/extraction-batches", {
        params: { path: { library_id: libraryId }, query: { offset, limit } },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async cancelBatch(libraryId, batchId, cancelRunning, signal) {
      const { data, error, response } = await client.POST("/api/v1/libraries/{library_id}/jobs/extraction-batches/{batch_id}/cancel", {
        params: { path: { library_id: libraryId, batch_id: batchId } },
        body: { cancel_running: cancelRunning },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async getQueueState(libraryId, signal) {
      const { data, error, response } = await client.GET("/api/v1/libraries/{library_id}/jobs/queue", {
        params: { path: { library_id: libraryId } },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
    async setQueuePaused(libraryId, paused, signal) {
      const { data, error, response } = await client.POST("/api/v1/libraries/{library_id}/jobs/queue", {
        params: { path: { library_id: libraryId } },
        body: { paused },
        signal,
      });
      if (!data) throw failure(error, response);
      return data;
    },
  };
}
