import { useCallback, useEffect, useRef, useState } from "react";

import { scheduleAutomaticChecks } from "./schedule";
import type {
  DesktopUpdateRuntime,
  UpdateCheckReason,
  UpdateDownloadEvent,
} from "./runtime";
import type { UpdaterState } from "./state";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export interface DesktopUpdater {
  readonly state: UpdaterState;
  check(reason?: UpdateCheckReason): Promise<void>;
  install(): Promise<void>;
  dismiss(): void;
}

export function useDesktopUpdater(
  runtime: DesktopUpdateRuntime | null,
): DesktopUpdater {
  const [state, setState] = useState<UpdaterState>({ phase: "idle" });
  const checkRef = useRef<Promise<void> | null>(null);

  const check = useCallback(
    async (reason: UpdateCheckReason = "manual") => {
      if (!runtime) return;
      if (checkRef.current) {
        await checkRef.current;
        return;
      }
      const request = (async () => {
        if (reason === "manual") setState({ phase: "checking" });
        try {
          const candidate = await runtime.check(reason);
          if (candidate) {
            setState({
              phase: "available",
              version: candidate.version,
              notes: candidate.notes,
            });
          } else if (reason === "manual") {
            setState({ phase: "up-to-date" });
          } else {
            setState({ phase: "idle", lastReason: reason });
          }
        } catch (error) {
          if (reason === "manual") {
            setState({
              phase: "error",
              operation: "check",
              message: errorMessage(error),
            });
          } else {
            console.error(`Automatic ${reason} update check failed`, error);
          }
        } finally {
          checkRef.current = null;
        }
      })();
      checkRef.current = request;
      await request;
    },
    [runtime],
  );

  const install = useCallback(async () => {
    if (!runtime || state.phase !== "available") return;
    const version = state.version;
    let downloadedBytes = 0;
    let totalBytes: number | undefined;
    setState({ phase: "downloading", version, downloadedBytes });
    try {
      await runtime.install((event: UpdateDownloadEvent) => {
        if (event.phase === "started") {
          downloadedBytes = 0;
          totalBytes = event.totalBytes;
        } else if (event.phase === "progress") {
          downloadedBytes += event.chunkBytes;
        } else {
          setState({ phase: "installing", version });
          return;
        }
        setState({
          phase: "downloading",
          version,
          downloadedBytes,
          totalBytes,
        });
      });
      setState({ phase: "installing", version });
      await runtime.relaunch();
    } catch (error) {
      setState({
        phase: "error",
        operation: "install",
        message: errorMessage(error),
        version,
      });
    }
  }, [runtime, state]);

  const dismiss = useCallback(() => {
    if (runtime) void runtime.close().catch(console.error);
    setState({ phase: "idle" });
  }, [runtime]);

  useEffect(() => {
    if (!runtime) return;
    return scheduleAutomaticChecks((reason) => void check(reason));
  }, [check, runtime]);
  useEffect(() => () => void runtime?.close().catch(console.error), [runtime]);

  return { state, check, install, dismiss };
}
