import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useJobsQuery } from "../api/jobQueries";
import { useRuntime } from "../api/RuntimeProvider";
import type { ExtractorCapability } from "../api/runtime";
import { useWorkspaceStore } from "../state/workspaceStore";
import { FailureState, LoadingState } from "./AsyncState";
import styles from "./ExtractionPanel.module.css";

const categoryLabels = {
  native_text: "Native text",
  ocr_preprocessing: "OCR / preprocessing",
  layout_parser: "Layout parsing",
  other: "Other",
};

function requestKey(): string {
  return `ui-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function supportsLanguages(extractor: ExtractorCapability): boolean {
  const properties = extractor.settings_schema.properties;
  return typeof properties === "object" && properties !== null && "languages" in properties;
}

function defaultLanguages(extractor: ExtractorCapability): string {
  const value = extractor.default_settings.languages;
  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? value.join("+")
    : "eng";
}

export function ExtractionPanel({
  documentId,
  onRepresentationReady,
}: {
  documentId: string;
  onRepresentationReady: (extractorId: string) => void;
}) {
  const runtime = useRuntime();
  const queryClient = useQueryClient();
  const libraryId = useWorkspaceStore((state) => state.activeLibraryId);
  const jobs = useJobsQuery(libraryId);
  const priorCompleted = useRef(new Set<string>());
  const [languages, setLanguages] = useState<Record<string, string>>({});
  const capabilities = useQuery({
    queryKey: ["library", libraryId, "extractors", documentId],
    queryFn: ({ signal }) => runtime.getExtractors(libraryId!, documentId, signal),
    enabled: libraryId !== null,
    staleTime: 30_000,
  });
  const currentJobs = useMemo(
    () => jobs.data?.items.filter((job) => job.document_id === documentId) ?? [],
    [documentId, jobs.data?.items],
  );
  const create = useMutation({
    mutationFn: ({
      extractor,
      mode,
    }: {
      extractor: ExtractorCapability;
      mode: "reuse_or_execute" | "fresh_verification";
    }) => {
      if (!libraryId) throw new Error("No active library");
      const languageValue = languages[extractor.extractor_id]?.trim();
      const settings = supportsLanguages(extractor)
        ? { languages: (languageValue || defaultLanguages(extractor)).split(/[+,\s]+/).filter(Boolean) }
        : {};
      return runtime.createExtraction(
        libraryId,
        {
          document_id: documentId,
          extractor_id: extractor.extractor_id,
          settings,
          execution_mode: mode,
        },
        requestKey(),
      );
    },
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["library", libraryId, "jobs"] });
      if (result.job.state === "succeeded") {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["library", libraryId, "extractors", documentId] }),
          queryClient.invalidateQueries({ queryKey: ["library", libraryId, "page-groups", documentId] }),
          queryClient.invalidateQueries({ queryKey: ["library", libraryId, "document", documentId] }),
        ]);
        onRepresentationReady(result.job.extractor_id);
      }
    },
  });
  const cancel = useMutation({
    mutationFn: (jobId: string) => runtime.cancelJob(libraryId!, jobId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["library", libraryId, "jobs"] }),
  });
  const retry = useMutation({
    mutationFn: (jobId: string) => runtime.retryJob(libraryId!, jobId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["library", libraryId, "jobs"] }),
  });

  useEffect(() => {
    const completed = currentJobs.filter((job) => job.state === "succeeded");
    for (const job of completed) {
      if (!priorCompleted.current.has(job.job_id)) {
        priorCompleted.current.add(job.job_id);
        void Promise.all([
          queryClient.invalidateQueries({ queryKey: ["library", libraryId, "extractors", documentId] }),
          queryClient.invalidateQueries({ queryKey: ["library", libraryId, "page-groups", documentId] }),
          queryClient.invalidateQueries({ queryKey: ["library", libraryId, "document", documentId] }),
        ]);
        onRepresentationReady(job.extractor_id);
      }
    }
  }, [currentJobs, documentId, libraryId, onRepresentationReady, queryClient]);

  if (capabilities.isLoading) return <LoadingState label="Checking extractor coverage" />;
  if (capabilities.error) return <FailureState title="Extractor capabilities unavailable" error={capabilities.error} />;
  const items = capabilities.data?.items ?? [];
  return (
    <details className={styles.panel} open>
      <summary>
        <span>Extraction</span>
        <strong>{items.filter((item) => item.cached).length}/{items.length} exact runs cached</strong>
      </summary>
      <p className={styles.passive}>Work starts only from the explicit actions below.</p>
      <div className={styles.groups}>
        {Object.entries(categoryLabels).map(([category, label]) => {
          const extractors = items.filter((item) => item.category === category);
          if (extractors.length === 0) return null;
          return (
            <section key={category}>
              <h3>{label}</h3>
              {extractors.map((extractor) => {
                const supported = extractor.document_supported !== false;
                const canRun = extractor.available && supported;
                const active = currentJobs.find(
                  (job) =>
                    job.extractor_id === extractor.extractor_id &&
                    ["queued", "starting", "running", "cancelling"].includes(job.state),
                );
                const failed = currentJobs.find(
                  (job) =>
                    job.extractor_id === extractor.extractor_id &&
                    ["failed", "interrupted"].includes(job.state),
                );
                return (
                  <article className={extractor.recommended ? styles.recommended : ""} key={extractor.extractor_id}>
                    <div className={styles.identity}>
                      <div>
                        <strong>{extractor.display_name}</strong>
                        {extractor.recommended && <span className={styles.recommendation}>Recommended</span>}
                      </div>
                      <span>{extractor.version_label ?? "Version unavailable"}</span>
                      <span>{extractor.resource_class} · {extractor.default_timeout_seconds}s deadline</span>
                      {extractor.run_key && <code title={extractor.run_key}>{extractor.run_key.slice(0, 14)}…</code>}
                    </div>
                    <div className={styles.coverage}>
                      <span className={extractor.cached ? styles.cached : styles.missing}>
                        {extractor.cached ? "Exact run cached" : "Exact run not cached"}
                      </span>
                      {!supported && <span>Unsupported for this media type</span>}
                      {!extractor.available && <span>{extractor.unavailable_reason ?? "Dependencies unavailable"}</span>}
                    </div>
                    {supportsLanguages(extractor) && (
                      <label className={styles.setting}>
                        OCR languages
                        <input
                          aria-label={`${extractor.display_name} languages`}
                          value={languages[extractor.extractor_id] ?? defaultLanguages(extractor)}
                          onChange={(event) =>
                            setLanguages((current) => ({ ...current, [extractor.extractor_id]: event.target.value }))
                          }
                        />
                      </label>
                    )}
                    <div className={styles.actions}>
                      <button
                        disabled={!canRun || Boolean(active) || create.isPending}
                        type="button"
                        onClick={() => create.mutate({ extractor, mode: "reuse_or_execute" })}
                      >
                        {extractor.cached ? "Use cached result" : "Run extraction"}
                      </button>
                      <button
                        disabled={!canRun || Boolean(active) || create.isPending}
                        type="button"
                        onClick={() => create.mutate({ extractor, mode: "fresh_verification" })}
                      >
                        Verify fresh
                      </button>
                      {active && (
                        <button
                          disabled={active.state === "cancelling" || cancel.isPending}
                          type="button"
                          onClick={() => cancel.mutate(active.job_id)}
                        >
                          {active.state === "cancelling" ? "Cancelling…" : `Cancel ${active.state}`}
                        </button>
                      )}
                      {failed && (
                        <button disabled={retry.isPending} type="button" onClick={() => retry.mutate(failed.job_id)}>
                          Retry failed
                        </button>
                      )}
                    </div>
                    {active && <p className={styles.jobState}>{active.state} · {active.queue_reason ?? active.resource_class}</p>}
                    {failed?.error_summary && <p className={styles.error}>{failed.error_summary}</p>}
                  </article>
                );
              })}
            </section>
          );
        })}
      </div>
      {create.error && <p className={styles.error}>{create.error.message}</p>}
    </details>
  );
}
