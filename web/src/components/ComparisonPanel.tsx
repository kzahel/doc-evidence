import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import { useRuntime } from "../api/RuntimeProvider";
import type { ComparisonResult, DiffToken, OutputGroup } from "../api/runtime";
import {
  resolveTextPresentation,
  type ResolvedTextPresentation,
} from "../presentation/textPresentation";
import { useWorkspaceStore } from "../state/workspaceStore";
import { EmptyState, FailureState, LoadingState } from "./AsyncState";
import styles from "./ComparisonPanel.module.css";

function groupLabel(group: OutputGroup, index: number): string {
  const names = group.runs.map((run) => run.extractor_id).join(" + ");
  return `${index + 1}. ${names}${group.runs.length > 1 ? " (identical)" : ""}`;
}

function Tokens({ tokens }: { tokens: DiffToken[] }) {
  return (
    <>
      {tokens.map((token, index) => (
        <span className={token.kind === "numeric" ? styles.numeric : undefined} key={`${index}:${token.text}`}>
          {token.text}
        </span>
      ))}
    </>
  );
}

function DiffView({
  result,
  presentation,
}: {
  result: ComparisonResult;
  presentation: ResolvedTextPresentation;
}) {
  const mode = useWorkspaceStore((state) => state.diffMode);
  const numericIndex = useWorkspaceStore((state) => state.numericIndex);
  const setNumericIndex = useWorkspaceStore((state) => state.setNumericIndex);
  const discrepancies = result.numeric_discrepancies;

  useEffect(() => {
    if (numericIndex >= discrepancies.length && discrepancies.length > 0) {
      setNumericIndex(discrepancies.length - 1);
    }
  }, [discrepancies.length, numericIndex, setNumericIndex]);

  function move(delta: number) {
    if (discrepancies.length === 0) return;
    const next = (numericIndex + delta + discrepancies.length) % discrepancies.length;
    setNumericIndex(next);
    const target = document.getElementById(`diff-segment-${discrepancies[next]?.segment_index}`);
    target?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }

  if (result.equivalent) {
    return <EmptyState>The selected outputs are exactly identical.</EmptyState>;
  }
  return (
    <div className={styles.diff}>
      <div className={styles.numericToolbar}>
        <strong>
          {discrepancies.length} numeric discrepanc{discrepancies.length === 1 ? "y" : "ies"}
        </strong>
        {discrepancies.length > 0 && (
          <>
            <button type="button" onClick={() => move(-1)} aria-label="Previous numeric discrepancy">
              ←
            </button>
            <span>
              {numericIndex + 1} / {discrepancies.length}
            </span>
            <button type="button" onClick={() => move(1)} aria-label="Next numeric discrepancy">
              →
            </button>
          </>
        )}
      </div>
      <div className={styles.segments}>
        {result.segments.map((segment) => {
          if (segment.operation === "equal" && mode === "differences") {
            const count = segment.left.length;
            return (
              <div className={styles.collapsed} key={segment.index}>
                <span>{count} unchanged token{count === 1 ? "" : "s"}</span>
              </div>
            );
          }
          const focused = discrepancies[numericIndex]?.segment_index === segment.index;
          return (
            <div
              id={`diff-segment-${segment.index}`}
              className={`${styles.segment} ${styles[segment.operation]} ${focused ? styles.focused : ""}`}
              key={segment.index}
            >
              <div className={styles.operation}>{segment.operation}</div>
              {segment.operation === "equal" ? (
                <pre className={styles[presentation]} data-presentation={presentation}>
                  <Tokens tokens={segment.left} />
                </pre>
              ) : (
                <div className={styles.sides}>
                  <div>
                    <span className={styles.sideLabel}>Baseline</span>
                    <pre className={styles[presentation]} data-presentation={presentation}>
                      <Tokens tokens={segment.left} />
                    </pre>
                  </div>
                  <div>
                    <span className={styles.sideLabel}>Comparison</span>
                    <pre className={styles[presentation]} data-presentation={presentation}>
                      <Tokens tokens={segment.right} />
                    </pre>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function RawView({
  baseline,
  comparison,
  presentation,
}: {
  baseline: OutputGroup;
  comparison: OutputGroup;
  presentation: ResolvedTextPresentation;
}) {
  return (
    <div className={styles.rawGrid} aria-label="Raw extractor outputs">
      {[
        { group: baseline, label: "Baseline" },
        { group: comparison, label: "Comparison" },
      ].map(({ group, label }) => (
        <article className={styles.rawCard} key={`${label}:${group.group_id}`}>
          <header>
            <span>{label}</span>
            <strong>{group.runs.map((run) => run.extractor_id).join(" + ")}</strong>
          </header>
          <pre className={styles[presentation]} data-presentation={presentation}>
            {group.text || "(No normalized text on this page)"}
          </pre>
        </article>
      ))}
    </div>
  );
}

interface Props {
  documentId: string;
  page: number;
  groups: OutputGroup[];
}

export function ComparisonPanel({ documentId, page, groups }: Props) {
  const runtime = useRuntime();
  const libraryId = useWorkspaceStore((state) => state.activeLibraryId);
  const baselineId = useWorkspaceStore((state) => state.baselineGroupId);
  const comparisonId = useWorkspaceStore((state) => state.comparisonGroupId);
  const setGroups = useWorkspaceStore((state) => state.setComparisonGroups);
  const mode = useWorkspaceStore((state) => state.diffMode);
  const setMode = useWorkspaceStore((state) => state.setDiffMode);
  const comparisonView = useWorkspaceStore((state) => state.comparisonView);
  const setComparisonView = useWorkspaceStore((state) => state.setComparisonView);
  const selectedPresentation = useWorkspaceStore((state) => state.textPresentationMode);
  const presentation = resolveTextPresentation(
    selectedPresentation,
    groups.map((group) => group.text),
  );

  const baseline = groups.find((group) => group.group_id === baselineId) ?? groups[0];
  const requestedComparison = groups.find((group) => group.group_id === comparisonId);
  const comparison =
    requestedComparison && requestedComparison.group_id !== baseline?.group_id
      ? requestedComparison
      : groups.find((group) => group.group_id !== baseline?.group_id);
  const request =
    baseline && comparison
      ? {
          document_id: documentId,
          page,
          left_run_ref: baseline.representative_run_ref,
          right_run_ref: comparison.representative_run_ref,
        }
      : null;
  const query = useQuery({
    queryKey: ["library", libraryId, "comparison", request],
    queryFn: ({ signal }) => runtime.compare(libraryId!, request!, signal),
    enabled: request !== null && comparisonView === "diff" && libraryId !== null,
  });

  useEffect(() => {
    if (
      baseline &&
      comparison &&
      (baselineId !== baseline.group_id || comparisonId !== comparison.group_id)
    ) {
      setGroups(baseline.group_id, comparison.group_id);
    }
  }, [baseline, baselineId, comparison, comparisonId, setGroups]);

  return (
    <section className={styles.panel} aria-label="Extractor comparison">
      <header>
        <div>
          <p className={styles.eyebrow}>Pairwise evidence</p>
          <h2>Extractor comparison</h2>
          <p>Deterministic token alignment · no correctness winner is inferred</p>
        </div>
        <div className={styles.headerControls}>
          <div className={styles.mode} role="group" aria-label="Comparison view">
            <button
              aria-pressed={comparisonView === "diff"}
              type="button"
              className={comparisonView === "diff" ? styles.active : ""}
              onClick={() => setComparisonView("diff")}
            >
              Diff
            </button>
            <button
              aria-pressed={comparisonView === "raw"}
              type="button"
              className={comparisonView === "raw" ? styles.active : ""}
              onClick={() => setComparisonView("raw")}
            >
              Raw two-up
            </button>
          </div>
          {comparisonView === "diff" && (
            <div className={styles.mode} role="group" aria-label="Diff density">
              <button
                type="button"
                className={mode === "differences" ? styles.active : ""}
                onClick={() => setMode("differences")}
              >
                Differences only
              </button>
              <button
                type="button"
                className={mode === "full" ? styles.active : ""}
                onClick={() => setMode("full")}
              >
                Full aligned output
              </button>
            </div>
          )}
        </div>
      </header>
      {groups.length < 2 ? (
        <EmptyState>
          {groups.length === 1
            ? (groups[0]?.runs.length ?? 0) === 1
              ? "Only one cached extractor run is available for this page. This view does not launch missing extractors."
              : `Only one unique output remains after collapsing ${groups[0]?.runs.length ?? 0} identical cached runs.`
            : "No successful extractor output is cached for this page."}
        </EmptyState>
      ) : (
        <>
          <div className={styles.selectors}>
            <label>
              Baseline
              <select
                aria-label="Baseline output"
                value={baseline?.group_id}
                onChange={(event) => setGroups(event.target.value, comparison?.group_id ?? null)}
              >
                {groups.map((group, index) => (
                  <option
                    disabled={group.group_id === comparison?.group_id}
                    key={group.group_id}
                    value={group.group_id}
                  >
                    {groupLabel(group, index)}
                  </option>
                ))}
              </select>
            </label>
            <button
              aria-label="Swap comparison direction"
              className={styles.swap}
              type="button"
              onClick={() => setGroups(comparison?.group_id ?? null, baseline?.group_id ?? null)}
            >
              ⇄
            </button>
            <label>
              Comparison
              <select
                aria-label="Comparison output"
                value={comparison?.group_id}
                onChange={(event) => setGroups(baseline?.group_id ?? null, event.target.value)}
              >
                {groups.map((group, index) => (
                  <option
                    disabled={group.group_id === baseline?.group_id}
                    key={group.group_id}
                    value={group.group_id}
                  >
                    {groupLabel(group, index)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {comparisonView === "raw" && baseline && comparison && (
            <RawView
              baseline={baseline}
              comparison={comparison}
              presentation={presentation.mode}
            />
          )}
          {comparisonView === "diff" && query.isLoading && (
            <LoadingState label="Aligning extractor outputs" />
          )}
          {comparisonView === "diff" && query.error && (
            <FailureState title="Comparison failed" error={query.error} />
          )}
          {comparisonView === "diff" && query.data && (
            <DiffView result={query.data} presentation={presentation.mode} />
          )}
        </>
      )}
    </section>
  );
}
