export type UpdateCheckReason = "startup" | "periodic" | "manual";

export interface UpdateCandidate {
  readonly version: string;
  readonly notes?: string;
}

export type UpdateDownloadEvent =
  | { readonly phase: "started"; readonly totalBytes?: number }
  | { readonly phase: "progress"; readonly chunkBytes: number }
  | { readonly phase: "finished" };

export interface DesktopUpdateRuntime {
  check(reason: UpdateCheckReason): Promise<UpdateCandidate | null>;
  install(onEvent: (event: UpdateDownloadEvent) => void): Promise<void>;
  relaunch(): Promise<void>;
  close(): Promise<void>;
}
