import type { DesktopUpdateRuntime } from "../updater/runtime";
import { progressPercent } from "../updater/state";
import { useDesktopUpdater } from "../updater/useDesktopUpdater";
import styles from "./DesktopUpdater.module.css";

export function DesktopUpdater({
  runtime,
}: {
  readonly runtime: DesktopUpdateRuntime | null;
}) {
  const updater = useDesktopUpdater(runtime);
  if (!runtime) return null;
  if (updater.state.phase === "idle") {
    return (
      <button
        className={styles.checkButton}
        type="button"
        onClick={() => void updater.check("manual")}
      >
        Check for updates
      </button>
    );
  }

  const progress = progressPercent(updater.state);
  return (
    <aside aria-live="polite" className={styles.notice}>
      {updater.state.phase === "checking" && <strong>Checking for updates…</strong>}
      {updater.state.phase === "up-to-date" && (
        <>
          <strong>Doc Evidence is up to date.</strong>
          <button type="button" onClick={updater.dismiss}>Close</button>
        </>
      )}
      {updater.state.phase === "available" && (
        <>
          <strong>Doc Evidence {updater.state.version} is available.</strong>
          {updater.state.notes && <span>{updater.state.notes}</span>}
          <span className={styles.actions}>
            <button type="button" onClick={() => void updater.install()}>
              Install and restart
            </button>
            <button type="button" onClick={updater.dismiss}>Later</button>
          </span>
        </>
      )}
      {updater.state.phase === "downloading" && (
        <>
          <strong>Downloading Doc Evidence {updater.state.version}…</strong>
          <progress max={100} value={progress} aria-label="Update download progress" />
        </>
      )}
      {updater.state.phase === "installing" && (
        <strong>Installing Doc Evidence {updater.state.version}…</strong>
      )}
      {updater.state.phase === "error" && (
        <>
          <strong>Update {updater.state.operation} failed.</strong>
          <span>{updater.state.message}</span>
          <span className={styles.actions}>
            <button type="button" onClick={() => void updater.check("manual")}>
              Try again
            </button>
            <button type="button" onClick={updater.dismiss}>Close</button>
          </span>
        </>
      )}
    </aside>
  );
}
