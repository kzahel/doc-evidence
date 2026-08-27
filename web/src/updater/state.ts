import type { UpdateCheckReason } from "./runtime";

export type UpdaterState =
  | { readonly phase: "idle"; readonly lastReason?: UpdateCheckReason }
  | { readonly phase: "checking" }
  | { readonly phase: "up-to-date" }
  | {
      readonly phase: "available";
      readonly version: string;
      readonly notes?: string;
    }
  | {
      readonly phase: "downloading";
      readonly version: string;
      readonly downloadedBytes: number;
      readonly totalBytes?: number;
    }
  | { readonly phase: "installing"; readonly version: string }
  | {
      readonly phase: "error";
      readonly operation: "check" | "install";
      readonly message: string;
      readonly version?: string;
    };

export function progressPercent(state: UpdaterState): number | undefined {
  if (
    state.phase !== "downloading" ||
    !state.totalBytes ||
    state.totalBytes <= 0
  ) {
    return undefined;
  }
  return Math.min(
    100,
    Math.round((state.downloadedBytes / state.totalBytes) * 100),
  );
}
