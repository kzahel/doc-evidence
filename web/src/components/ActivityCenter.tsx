import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useJobsQuery } from "../api/jobQueries";
import { useRuntime } from "../api/RuntimeProvider";
import type { JobSummary } from "../api/runtime";
import { useWorkspaceStore, type ActivityFilter } from "../state/workspaceStore";
import { FailureState, LoadingState } from "./AsyncState";
import styles from "./ActivityCenter.module.css";

const filters: { value: ActivityFilter; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "queued", label: "Queued" },
  { value: "recent", label: "Recent" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
  { value: "interrupted", label: "Interrupted" },
  { value: "all", label: "All" },
];

function matches(job: JobSummary, filter: ActivityFilter): boolean {
  if (filter === "all") return true;
  if (filter === "active") return ["starting", "running", "cancelling"].includes(job.state);
  if (filter === "recent") return job.state === "succeeded";
  return job.state === filter;
}

function age(timestamp: string | null): string {
  if (!timestamp) return "—";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(timestamp).getTime()) / 1_000));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3_600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3_600)}h`;
}

export function ActivityCenter({ libraryId }: { libraryId: string }) {
  const runtime = useRuntime();
  const queryClient = useQueryClient();
  const jobs = useJobsQuery(libraryId);
  const open = useWorkspaceStore((state) => state.activityOpen);
  const setOpen = useWorkspaceStore((state) => state.setActivityOpen);
  const filter = useWorkspaceStore((state) => state.activityFilter);
  const setFilter = useWorkspaceStore((state) => state.setActivityFilter);
  const selectedJobId = useWorkspaceStore((state) => state.selectedJobId);
  const setSelectedJobId = useWorkspaceStore((state) => state.setSelectedJobId);
  const advanced = useWorkspaceStore((state) => state.advancedActivity);
  const setAdvanced = useWorkspaceStore((state) => state.setAdvancedActivity);
  const [hiddenRecent, setHiddenRecent] = useState(new Set<string>());
  const [showBatchPreflight, setShowBatchPreflight] = useState(false);
  const batches = useQuery({
    queryKey: ["library", libraryId, "job-batches"],
    queryFn: ({ signal }) => runtime.listBatches(libraryId, 0, 50, signal),
    enabled: open,
    refetchInterval: jobs.data?.counts.active || jobs.data?.counts.queued ? 1_000 : 5_000,
  });
  const queue = useQuery({
    queryKey: ["library", libraryId, "job-queue"],
    queryFn: ({ signal }) => runtime.getQueueState(libraryId, signal),
    enabled: open,
    refetchInterval: open ? 2_000 : false,
  });
  const batchPreflight = useQuery({
    queryKey: ["library", libraryId, "batch-preflight", "image-only-ocr"],
    queryFn: ({ signal }) => runtime.preflightImageOnlyOcr(libraryId, signal),
    enabled: open && showBatchPreflight,
  });
  const selected = useQuery({
    queryKey: ["library", libraryId, "job", selectedJobId],
    queryFn: ({ signal }) => runtime.getJob(libraryId, selectedJobId!, signal),
    enabled: open && selectedJobId !== null,
    refetchInterval: (query) => {
      const state = query.state.data?.job.state;
      return state && ["queued", "starting", "running", "cancelling"].includes(state) ? 1_000 : false;
    },
  });
  const latestAttemptId = selected.data?.attempts.at(-1)?.attempt_id ?? null;
  const events = useQuery({
    queryKey: ["library", libraryId, "job", selectedJobId, "events"],
    queryFn: ({ signal }) => runtime.getJobEvents(libraryId, selectedJobId!, 0, 500, signal),
    enabled: open && selectedJobId !== null && advanced,
    refetchInterval: selected.data?.job.state && ["queued", "starting", "running", "cancelling"].includes(selected.data.job.state)
      ? 1_000
      : false,
  });
  const attemptDiagnostics = useQuery({
    queryKey: ["library", libraryId, "job", selectedJobId, "attempt", latestAttemptId, "diagnostics"],
    queryFn: ({ signal }) => runtime.getAttemptDiagnostics(libraryId, selectedJobId!, latestAttemptId!, signal),
    enabled: open && selectedJobId !== null && latestAttemptId !== null && advanced,
    refetchInterval: selected.data?.job.state && ["starting", "running", "cancelling"].includes(selected.data.job.state)
      ? 2_000
      : false,
  });
  const cancel = useMutation({
    mutationFn: (jobId: string) => runtime.cancelJob(libraryId, jobId),
    onSuccess: async (result) => {
      queryClient.setQueryData(["library", libraryId, "job", result.job.job_id], result);
      await queryClient.invalidateQueries({ queryKey: ["library", libraryId, "jobs"] });
    },
  });
  const retry = useMutation({
    mutationFn: (jobId: string) => runtime.retryJob(libraryId, jobId),
    onSuccess: async (result) => {
      queryClient.setQueryData(["library", libraryId, "job", result.job.job_id], result);
      await queryClient.invalidateQueries({ queryKey: ["library", libraryId, "jobs"] });
    },
  });
  const repair = useMutation({
    mutationFn: (jobId: string) => runtime.repairJobProjection(libraryId, jobId),
    onSuccess: async (result) => {
      queryClient.setQueryData(["library", libraryId, "job", result.job.job_id], result);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["library", libraryId, "jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["library", libraryId, "documents"] }),
      ]);
    },
  });
  const updateQueue = useMutation({
    mutationFn: (paused: boolean) => runtime.setQueuePaused(libraryId, paused),
    onSuccess: (result) => {
      queryClient.setQueryData(["library", libraryId, "job-queue"], result);
      void queryClient.invalidateQueries({ queryKey: ["library", libraryId, "jobs"] });
    },
  });
  const createBatch = useMutation({
    mutationFn: () => {
      const preflight = batchPreflight.data;
      if (!preflight) throw new Error("Batch preflight is not ready");
      return runtime.createExtractionBatch(
        libraryId,
        {
          document_ids: preflight.document_ids,
          extractor_ids: [preflight.extractor_id],
          settings: {},
          execution_mode: "reuse_or_execute",
          confirmed: true,
        },
        `image-ocr-${Date.now()}`,
      );
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["library", libraryId, "jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["library", libraryId, "job-batches"] }),
        queryClient.invalidateQueries({ queryKey: ["library", libraryId, "batch-preflight"] }),
      ]);
    },
  });
  const cancelBatch = useMutation({
    mutationFn: ({ batchId, cancelRunning }: { batchId: string; cancelRunning: boolean }) =>
      runtime.cancelBatch(libraryId, batchId, cancelRunning),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["library", libraryId, "jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["library", libraryId, "job-batches"] }),
      ]);
    },
  });
  const visible = useMemo(
    () =>
      (jobs.data?.items ?? []).filter(
        (job) => matches(job, filter) && !(filter === "recent" && hiddenRecent.has(job.job_id)),
      ),
    [filter, hiddenRecent, jobs.data?.items],
  );
  const counts = jobs.data?.counts ?? { active: 0, queued: 0, failed: 0 };
  const resourceCounts = (jobs.data?.items ?? []).reduce(
    (current, job) => {
      if (["starting", "running", "cancelling"].includes(job.state)) current[job.resource_class] += 1;
      return current;
    },
    { light: 0, ocr: 0, model_heavy: 0 },
  );

  return (
    <div className={styles.root}>
      <button
        aria-expanded={open}
        className={styles.trigger}
        type="button"
        onClick={() => setOpen(!open)}
      >
        Activity
        <span>{counts.active} active · {counts.queued} queued · {counts.failed} failed</span>
      </button>
      {open && (
        <aside aria-label="Extraction activity" className={styles.panel}>
          <header>
            <div>
              <p>Library operations</p>
              <h2>Extraction activity</h2>
            </div>
            <button aria-label="Close activity" type="button" onClick={() => setOpen(false)}>×</button>
          </header>
          <div className={styles.counts}>
            <span><strong>{counts.active}</strong> active</span>
            <span><strong>{counts.queued}</strong> queued</span>
            <span className={counts.failed ? styles.attention : ""}><strong>{counts.failed}</strong> failed</span>
          </div>
          <div className={styles.queueControl}>
            <span>Queue is {queue.data?.paused ? "paused" : "accepting claims"}</span>
            <button
              disabled={queue.isLoading || updateQueue.isPending}
              type="button"
              onClick={() => updateQueue.mutate(!(queue.data?.paused ?? false))}
            >
              {queue.data?.paused ? "Resume queue" : "Pause queue"}
            </button>
          </div>
          <nav aria-label="Activity filters" className={styles.filters}>
            {filters.map((item) => (
              <button
                aria-pressed={filter === item.value}
                key={item.value}
                type="button"
                onClick={() => setFilter(item.value)}
              >
                {item.label}
              </button>
            ))}
          </nav>
          {filter === "recent" && visible.length > 0 && (
            <button
              className={styles.clear}
              type="button"
              onClick={() => setHiddenRecent(new Set(visible.map((job) => job.job_id)))}
            >
              Clear visual recent list
            </button>
          )}
          {jobs.isLoading && <LoadingState label="Loading activity" />}
          {jobs.error && <FailureState title="Activity unavailable" error={jobs.error} />}
          <div className={styles.jobs}>
            {visible.map((job) => (
              <button
                aria-current={selectedJobId === job.job_id ? "true" : undefined}
                key={job.job_id}
                type="button"
                onClick={() => setSelectedJobId(job.job_id)}
              >
                <div>
                  <strong>{job.extractor_id}</strong>
                  <span className={`${styles.state} ${styles[job.state]}`}>{job.state}</span>
                </div>
                <span>{job.document_id.slice(0, 18)}… · {job.resource_class}</span>
                <span>{job.outcome === "cache_hit" ? "Fulfilled from exact cache; no worker started" : job.error_summary ?? job.outcome ?? job.queue_reason ?? "Waiting for scheduler"}</span>
                <span>{age(job.started_at ?? job.queued_at)} elapsed</span>
              </button>
            ))}
            {!jobs.isLoading && visible.length === 0 && <p>No jobs match this filter.</p>}
          </div>
          <section className={styles.batchPreflight}>
            <div>
              <strong>Image-only PDFs missing exact OCR</strong>
              <span>Bounded policy · OCR lane concurrency 1 · maximum 200</span>
            </div>
            <button type="button" onClick={() => setShowBatchPreflight(!showBatchPreflight)}>
              {showBatchPreflight ? "Hide preflight" : "Preflight batch"}
            </button>
            {showBatchPreflight && batchPreflight.isLoading && <LoadingState label="Checking OCR coverage" />}
            {showBatchPreflight && batchPreflight.error && <FailureState title="Batch preflight failed" error={batchPreflight.error} />}
            {showBatchPreflight && batchPreflight.data && (
              <div className={styles.preflightResult}>
                <span>{batchPreflight.data.candidate_count} image-only PDF candidates</span>
                <span>{batchPreflight.data.cache_hit_count} exact cache hits</span>
                <span>{batchPreflight.data.execution_count} actual OCR executions</span>
                <span>{batchPreflight.data.unsupported_count} unsupported · {batchPreflight.data.missing_dependency_count} blocked by dependencies</span>
                <span>{batchPreflight.data.resource_class} resource · {batchPreflight.data.concurrency_limit} at a time</span>
                {batchPreflight.data.over_limit_count > 0 && <strong>{batchPreflight.data.over_limit_count} documents exceed the 200-document maximum.</strong>}
                <button
                  disabled={
                    createBatch.isPending ||
                    batchPreflight.data.execution_count === 0 ||
                    batchPreflight.data.missing_dependency_count > 0 ||
                    batchPreflight.data.over_limit_count > 0
                  }
                  title={batchPreflight.data.missing_dependency_count > 0 ? "Install OCR dependencies before confirming" : "Create the confirmed batch and child jobs"}
                  type="button"
                  onClick={() => createBatch.mutate()}
                >
                  {createBatch.isPending ? "Creating batch…" : `Confirm ${batchPreflight.data.execution_count} OCR executions`}
                </button>
                {createBatch.error && <strong>{createBatch.error.message}</strong>}
              </div>
            )}
          </section>
          <details className={styles.batches}>
            <summary>Recent batches · {batches.data?.total ?? 0}</summary>
            {batches.data?.items.map((batch) => (
              <div key={batch.batch_id}>
                <strong>{batch.status}</strong>
                <span>{batch.child_count} jobs · {batch.cache_hit_count} cache hits · {batch.failed_count} failed</span>
                {!["succeeded", "failed", "cancelled", "partially_failed"].includes(batch.status) && (
                  <span>
                    <button
                      disabled={cancelBatch.isPending}
                      type="button"
                      onClick={() => cancelBatch.mutate({ batchId: batch.batch_id, cancelRunning: false })}
                    >Cancel pending</button>
                    <button
                      disabled={cancelBatch.isPending}
                      type="button"
                      onClick={() => {
                        if (window.confirm("Cancel pending children and request cancellation of running children?")) {
                          cancelBatch.mutate({ batchId: batch.batch_id, cancelRunning: true });
                        }
                      }}
                    >Cancel including running…</button>
                  </span>
                )}
              </div>
            ))}
          </details>
          {selectedJobId && (
            <section className={styles.detail}>
              {selected.isLoading && <LoadingState label="Loading job detail" />}
              {selected.error && <FailureState title="Job detail unavailable" error={selected.error} />}
              {selected.data && (
                <>
                  <header>
                    <div>
                      <p>Selected job</p>
                      <h3>{selected.data.job.extractor_id} · {selected.data.job.state}</h3>
                    </div>
                    <button type="button" onClick={() => setSelectedJobId(null)}>Close detail</button>
                  </header>
                  <dl>
                    <div><dt>Run key</dt><dd><code>{selected.data.job.run_key ?? "pending"}</code></dd></div>
                    <div><dt>Mode</dt><dd>{selected.data.job.execution_mode.replaceAll("_", " ")}</dd></div>
                    <div><dt>Outcome</dt><dd>{selected.data.job.outcome ?? "pending"}</dd></div>
                    <div><dt>Queue</dt><dd>{selected.data.job.queue_reason ?? "claimed or complete"}</dd></div>
                    {selected.data.job.error_summary && <div><dt>Attention</dt><dd>{selected.data.job.error_summary}</dd></div>}
                  </dl>
                  <div className={styles.detailActions}>
                    <button
                      disabled={!(["queued", "starting", "running"].includes(selected.data.job.state)) || cancel.isPending}
                      title={["queued", "starting", "running"].includes(selected.data.job.state) ? "Cancel queued or active work" : "This job is already terminal"}
                      type="button"
                      onClick={() => cancel.mutate(selected.data.job.job_id)}
                    >Cancel</button>
                    <button
                      disabled={!(["failed", "interrupted"].includes(selected.data.job.state)) || retry.isPending}
                      title={["failed", "interrupted"].includes(selected.data.job.state) ? "Add a technical retry attempt" : "Only failed or interrupted jobs can retry"}
                      type="button"
                      onClick={() => retry.mutate(selected.data.job.job_id)}
                    >Retry</button>
                    <button
                      disabled={selected.data.job.outcome !== "published_projection_failed" || repair.isPending}
                      title={selected.data.job.outcome === "published_projection_failed" ? "Validate the canonical artifact and rebuild its catalog projection" : "No projection repair is required"}
                      type="button"
                      onClick={() => repair.mutate(selected.data.job.job_id)}
                    >Repair catalog projection</button>
                    <button type="button" onClick={() => setAdvanced(!advanced)}>{advanced ? "Hide debug" : "Advanced debug"}</button>
                    <button type="button" onClick={() => void navigator.clipboard?.writeText(JSON.stringify({ job: selected.data, attempt: attemptDiagnostics.data }, null, 2))}>Copy diagnostics</button>
                  </div>
                  {advanced && (
                    <div className={styles.debug}>
                      <h4>Resource lanes</h4>
                      <p>Light {resourceCounts.light}/2 · OCR {resourceCounts.ocr}/1 · Model-heavy {resourceCounts.model_heavy}/1</p>
                      <h4>Scheduler lease</h4>
                      <p>
                        {queue.data?.scheduler_instance_id ?? "No active owner"} · heartbeat {age(queue.data?.heartbeat_at ?? null)} ago · {queue.data?.paused ? "paused" : "claiming enabled"}
                      </p>
                      <h4>Attempts</h4>
                      {selected.data.attempts.map((attempt) => (
                        <article key={attempt.attempt_id}>
                          <strong>Attempt {attempt.attempt_number} · {attempt.state}</strong>
                          <span>PID {attempt.worker_pid ?? "—"} · group {attempt.process_group_id ?? "—"}</span>
                          <span>
                            {attempt.process_alive === true
                              ? `Process alive · quiet for ${Math.floor(attempt.heartbeat_age_seconds ?? 0)}s`
                              : attempt.process_alive === false
                                ? "Process not alive"
                                : "Process not launched or liveness unavailable"}
                            {attempt.deadline_expired ? " · deadline expired" : " · within deadline"}
                          </span>
                          <span>Heartbeat {age(attempt.heartbeat_at)} ago · deadline {attempt.deadline_at}</span>
                          <span>Exit {attempt.exit_code ?? "—"} · publication {attempt.publication_outcome ?? "pending"}</span>
                          {attempt.failure_class && <span>{attempt.failure_class}: {attempt.error_summary}</span>}
                        </article>
                      ))}
                      <h4>Attempt diagnostics</h4>
                      {attemptDiagnostics.isLoading && <LoadingState label="Loading bounded attempt logs" />}
                      {attemptDiagnostics.error && <FailureState title="Attempt diagnostics unavailable" error={attemptDiagnostics.error} />}
                      {attemptDiagnostics.data && (
                        <article>
                          <span>{attemptDiagnostics.data.staging_status} staging · {attemptDiagnostics.data.validation_status} validation</span>
                          <span>{attemptDiagnostics.data.publication_status} publication · {attemptDiagnostics.data.projection_status} projection</span>
                          <span>Environment {Object.entries(attemptDiagnostics.data.environment).map(([name, value]) => `${name} ${value}`).join(" · ")}</span>
                          <details>
                            <summary>stdout tail · {attemptDiagnostics.data.stdout_truncated_bytes} earlier bytes truncated</summary>
                            <pre>{attemptDiagnostics.data.stdout_tail || "No retained stdout."}</pre>
                          </details>
                          <details>
                            <summary>stderr tail · {attemptDiagnostics.data.stderr_truncated_bytes} earlier bytes truncated</summary>
                            <pre>{attemptDiagnostics.data.stderr_tail || "No retained stderr."}</pre>
                          </details>
                        </article>
                      )}
                      <h4>Event timeline</h4>
                      {events.data?.items.map((event) => (
                        <div className={styles.event} key={event.sequence}>
                          <span>{event.sequence}</span>
                          <strong>{event.stage}</strong>
                          <span>{event.event_type}</span>
                          <time>{event.created_at}</time>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </section>
          )}
        </aside>
      )}
    </div>
  );
}
