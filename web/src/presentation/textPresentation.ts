export type TextPresentationMode = "auto" | "reading" | "aligned";
export type ResolvedTextPresentation = Exclude<TextPresentationMode, "auto">;

export interface TextPresentationRecommendation {
  mode: ResolvedTextPresentation;
  reason: string;
}

const MAX_SAMPLE_LINES = 500;
const MAX_LINE_LENGTH = 2_000;

export function recommendTextPresentation(
  texts: readonly string[],
): TextPresentationRecommendation {
  const lines = texts
    .flatMap((text) => text.split(/\r?\n/))
    .filter((line) => line.trim().length > 0)
    .slice(0, MAX_SAMPLE_LINES)
    .map((line) => line.slice(0, MAX_LINE_LENGTH));

  if (lines.length < 3) {
    return { mode: "reading", reason: "too few non-empty lines to infer columns" };
  }

  let delimitedLines = 0;
  let multiSpaceLines = 0;
  const boundaryPositions = new Map<number, number>();

  for (const line of lines) {
    const pipeCount = line.match(/\|/g)?.length ?? 0;
    if (line.includes("\t") || pipeCount >= 2) delimitedLines += 1;
    if (/\S[ \t]{2,}\S/.test(line)) multiSpaceLines += 1;

    for (const match of line.matchAll(/ {2,}(?=\S)/g)) {
      const position = (match.index ?? 0) + match[0].length;
      boundaryPositions.set(position, (boundaryPositions.get(position) ?? 0) + 1);
    }
  }

  const strongestBoundary = Math.max(0, ...boundaryPositions.values());
  if (delimitedLines >= 3) {
    return { mode: "aligned", reason: "repeated tabs or table delimiters were detected" };
  }

  const spacingThreshold = Math.max(3, Math.ceil(lines.length * 0.18));
  if (multiSpaceLines >= spacingThreshold && strongestBoundary >= 3) {
    return {
      mode: "aligned",
      reason: "repeated multi-space columns align at a shared position",
    };
  }

  if (multiSpaceLines >= Math.max(4, Math.ceil(lines.length * 0.3))) {
    return { mode: "aligned", reason: "many lines use spacing that may encode columns" };
  }

  return { mode: "reading", reason: "no stable whitespace or table-column pattern was detected" };
}

export function resolveTextPresentation(
  selected: TextPresentationMode,
  texts: readonly string[],
): TextPresentationRecommendation {
  if (selected === "auto") return recommendTextPresentation(texts);
  return {
    mode: selected,
    reason:
      selected === "aligned"
        ? "manual alignment-preserving mode"
        : "manual proportional reading mode",
  };
}
