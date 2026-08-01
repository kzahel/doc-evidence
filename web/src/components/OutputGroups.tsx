import { useEffect, useState } from "react";

import { useRuntime } from "../api/RuntimeProvider";
import type { OutputGroup, PageGroups } from "../api/runtime";
import {
  resolveTextPresentation,
  type ResolvedTextPresentation,
  type TextPresentationMode,
} from "../presentation/textPresentation";
import {
  useWorkspaceStore,
  type ReviewMode,
} from "../state/workspaceStore";
import { ComparisonPanel } from "./ComparisonPanel";
import { EmptyState } from "./AsyncState";
import styles from "./OutputGroups.module.css";

const categoryLabels = {
  native_text: "Native text",
  ocr_preprocessing: "OCR / preprocessing",
  layout_parser: "Layout parser",
  other: "Other representation",
};

function ArtifactButton({ artifactId, label }: { artifactId: string; label: string }) {
  const runtime = useRuntime();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ mediaType: string; url: string } | null>(null);
  useEffect(() => {
    return () => {
      if (preview) URL.revokeObjectURL(preview.url);
    };
  }, [preview]);
  async function open() {
    setBusy(true);
    setError(null);
    try {
      const blob = await runtime.getArtifact(artifactId);
      const url = URL.createObjectURL(blob);
      setPreview({ mediaType: blob.type || "application/octet-stream", url });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <button className={styles.artifact} type="button" disabled={busy} onClick={open}>
        {busy ? "Opening…" : label}
      </button>
      {error && <span className={styles.artifactError}>{error}</span>}
      {preview && (
        <div className={styles.previewBackdrop} role="presentation">
          <section
            aria-label={`Raw artifact: ${label}`}
            aria-modal="true"
            className={styles.previewDialog}
            role="dialog"
          >
            <header>
              <div>
                <strong>{label}</strong>
                <span>{preview.mediaType}</span>
              </div>
              <div>
                <a download={label.split(" · ")[0] ?? "artifact"} href={preview.url}>
                  Download
                </a>
                <button type="button" onClick={() => setPreview(null)}>
                  Close
                </button>
              </div>
            </header>
            <iframe sandbox="" src={preview.url} title={`Raw artifact preview: ${label}`} />
          </section>
        </div>
      )}
    </>
  );
}

function GroupCard({
  group,
  index,
  presentation,
  focused = false,
}: {
  group: OutputGroup;
  index: number;
  presentation: ResolvedTextPresentation;
  focused?: boolean;
}) {
  const baseline = useWorkspaceStore((state) => state.baselineGroupId);
  const comparison = useWorkspaceStore((state) => state.comparisonGroupId);
  const setGroups = useWorkspaceStore((state) => state.setComparisonGroups);
  const setReviewMode = useWorkspaceStore((state) => state.setReviewMode);
  const isBaseline = baseline === group.group_id;
  const isComparison = comparison === group.group_id;
  return (
    <article
      className={`${styles.card} ${focused ? styles.focusedCard : ""} ${
        isBaseline || isComparison ? styles.chosen : ""
      }`}
    >
      <header>
        <div>
          <span className={styles.index}>Representation {index + 1}</span>
          <h3>
            {group.runs.length > 1
              ? `Identical output from ${group.runs.length} runs`
              : group.runs[0]?.extractor_id}
          </h3>
        </div>
        <div className={styles.roleButtons}>
          <button
            type="button"
            className={isBaseline ? styles.active : ""}
            onClick={() => {
              setGroups(group.group_id, isComparison ? baseline : comparison);
              setReviewMode("compare");
            }}
          >
            Baseline
          </button>
          <button
            type="button"
            className={isComparison ? styles.active : ""}
            onClick={() => {
              setGroups(isBaseline ? comparison : baseline, group.group_id);
              setReviewMode("compare");
            }}
          >
            Compare
          </button>
        </div>
      </header>
      <div className={styles.runs}>
        {group.runs.map((run) => (
          <details key={run.run_ref}>
            <summary>
              <span className={`${styles.category} ${styles[run.category]}`}>
                {categoryLabels[run.category]}
              </span>
              <strong>{run.extractor_id}</strong>
              <span>{run.version_label}</span>
              {run.status !== "ok" && <span className={styles.warning}>{run.status}</span>}
            </summary>
            <div className={styles.runDetails}>
              <p>
                <strong>Displayed layer:</strong> normalized page text. This is extractor output,
                not a parsed field or reviewed fact.
              </p>
              <p>
                <strong>Cache identity:</strong> <code>{run.run_key}</code>
              </p>
              {run.warnings.length > 0 && (
                <ul>{run.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
              )}
              {run.raw_artifacts.length > 0 && (
                <div className={styles.artifacts}>
                  <strong>Raw artifacts</strong>
                  {run.raw_artifacts.map((artifact) => (
                    <ArtifactButton
                      key={artifact.artifact_id}
                      artifactId={artifact.artifact_id}
                      label={`${artifact.label} · ${(artifact.size_bytes / 1024).toFixed(1)} KB`}
                    />
                  ))}
                </div>
              )}
              <details>
                <summary>Exact descriptor and options</summary>
                <pre>{JSON.stringify(run.descriptor, null, 2)}</pre>
              </details>
            </div>
          </details>
        ))}
      </div>
      <pre
        className={`${styles.output} ${styles[presentation]}`}
        data-presentation={presentation}
      >
        {group.text || "(No normalized text on this page)"}
      </pre>
    </article>
  );
}

export function OutputGroups({ data }: { data: PageGroups }) {
  const runCount = data.groups.reduce((total, group) => total + group.runs.length, 0);
  const reviewMode = useWorkspaceStore((state) => state.reviewMode);
  const setReviewMode = useWorkspaceStore((state) => state.setReviewMode);
  const activeGroupId = useWorkspaceStore((state) => state.activeGroupId);
  const setActiveGroupId = useWorkspaceStore((state) => state.setActiveGroupId);
  const selectedPresentation = useWorkspaceStore((state) => state.textPresentationMode);
  const setSelectedPresentation = useWorkspaceStore(
    (state) => state.setTextPresentationMode,
  );
  const presentation = resolveTextPresentation(
    selectedPresentation,
    data.groups.map((group) => group.text),
  );
  const options: { label: string; mode: TextPresentationMode; title: string }[] = [
    {
      label: "Auto",
      mode: "auto",
      title: "Choose a reading or aligned layout from the extracted text",
    },
    {
      label: "Reading",
      mode: "reading",
      title: "Use a proportional font and wrap long lines",
    },
    {
      label: "Aligned",
      mode: "aligned",
      title: "Preserve spacing in monospace and scroll long lines horizontally",
    },
  ];
  const reviewOptions: { label: string; mode: ReviewMode; title: string }[] = [
    {
      label: "Focused",
      mode: "focused",
      title: "Inspect one selected representation",
    },
    {
      label: "Stacked",
      mode: "stacked",
      title: "Review every representation in one scrollable pane",
    },
    {
      label: "Compare",
      mode: "compare",
      title: "Compare two selected representations",
    },
  ];
  const activeGroup =
    data.groups.find((group) => group.group_id === activeGroupId) ?? data.groups[0];

  useEffect(() => {
    if (activeGroup && activeGroup.group_id !== activeGroupId) {
      setActiveGroupId(activeGroup.group_id);
    }
  }, [activeGroup, activeGroupId, setActiveGroupId]);

  return (
    <section className={styles.section} aria-label="Extractor representations">
      <div className={styles.chrome}>
        <div className={styles.intro}>
          <div>
            <p className={styles.eyebrow}>Representation layer 5</p>
            <h2>Normalized extractor text</h2>
          </div>
          <p>
            {runCount} cached run{runCount === 1 ? "" : "s"} · {data.groups.length} unique
            representation{data.groups.length === 1 ? "" : "s"}. Cached only; agreement is not
            correctness.
          </p>
        </div>
        <div className={styles.workbenchToolbar}>
          <div className={styles.toolbarGroup}>
            <strong>View</strong>
            <div className={styles.segmented} role="group" aria-label="Review mode">
              {reviewOptions.map((option) => (
                <button
                  aria-pressed={reviewMode === option.mode}
                  className={reviewMode === option.mode ? styles.activeOption : ""}
                  disabled={option.mode === "compare" && data.groups.length < 2}
                  key={option.mode}
                  title={option.title}
                  type="button"
                  onClick={() => setReviewMode(option.mode)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          <div className={styles.toolbarGroup}>
            <strong>Text</strong>
            <div className={styles.segmented} role="group" aria-label="Extraction text layout">
              {options.map((option) => (
                <button
                  aria-pressed={selectedPresentation === option.mode}
                  className={selectedPresentation === option.mode ? styles.activeOption : ""}
                  key={option.mode}
                  title={option.title}
                  type="button"
                  onClick={() => setSelectedPresentation(option.mode)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          <span className={styles.presentationHint}>
            {selectedPresentation === "auto"
              ? `Auto chose ${presentation.mode}: ${presentation.reason}.`
              : `${presentation.reason}.`}
          </span>
        </div>
      </div>
      <div className={styles.content} data-review-mode={reviewMode}>
        {reviewMode === "focused" && data.groups.length > 0 && (
          <>
            <nav className={styles.representationStrip} aria-label="Representations">
              {data.groups.map((group, index) => (
                <button
                  aria-pressed={activeGroup?.group_id === group.group_id}
                  className={activeGroup?.group_id === group.group_id ? styles.activeRepresentation : ""}
                  key={group.group_id}
                  title={group.runs.map((run) => `${run.extractor_id} ${run.version_label}`).join(" · ")}
                  type="button"
                  onClick={() => setActiveGroupId(group.group_id)}
                >
                  <strong>{index + 1}</strong>
                  <span>{group.runs.map((run) => run.extractor_id).join(" + ")}</span>
                  {group.runs.length > 1 && <small>{group.runs.length} identical runs</small>}
                </button>
              ))}
            </nav>
            {activeGroup && (
              <div className={`${styles.stack} ${styles.focusedStack}`}>
                <GroupCard
                  focused
                  group={activeGroup}
                  index={data.groups.indexOf(activeGroup)}
                  presentation={presentation.mode}
                />
              </div>
            )}
          </>
        )}
        {reviewMode === "stacked" && (
          <div className={styles.stack}>
            {data.groups.map((group, index) => (
              <GroupCard
                key={group.group_id}
                group={group}
                index={index}
                presentation={presentation.mode}
              />
            ))}
          </div>
        )}
        {reviewMode === "compare" && (
          <ComparisonPanel
            documentId={data.document_id}
            page={data.page}
            groups={data.groups}
          />
        )}
        {data.groups.length === 0 && (
          <EmptyState>No successful extractor output is cached for this page.</EmptyState>
        )}
        {data.assertions.length > 0 && (
          <section className={styles.assertions}>
            <h3>Manually verified spot checks</h3>
            <p>Sparse benchmark checks are focused evidence, not full-page accuracy scores.</p>
            <ul>
              {data.assertions.map((assertion) => (
                <li key={`${assertion.extractor_id}:${assertion.assertion_id}`}>
                  <span className={assertion.passed ? styles.pass : styles.fail}>
                    {assertion.passed ? "Pass" : "Miss"}
                  </span>
                  <strong>{assertion.extractor_id}</strong> · {assertion.assertion_id} · expected{" "}
                  <code>{String(assertion.expected)}</code>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </section>
  );
}
