import type { PropsWithChildren, ReactNode } from "react";

import styles from "./AsyncState.module.css";

export function LoadingState({ label = "Loading workspace" }: { label?: string }) {
  return (
    <div className={styles.state} role="status">
      <span className={styles.spinner} aria-hidden="true" />
      {label}
    </div>
  );
}

export function FailureState({ error, title = "Could not load" }: { error: unknown; title?: string }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className={`${styles.state} ${styles.failure}`} role="alert">
      <strong>{title}</strong>
      <span>{message}</span>
    </div>
  );
}

export function EmptyState({ children }: PropsWithChildren): ReactNode {
  return <div className={`${styles.state} ${styles.empty}`}>{children}</div>;
}
