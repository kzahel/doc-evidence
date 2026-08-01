import { createContext, type PropsWithChildren, useContext } from "react";

import type { DocEvidenceRuntime } from "./runtime";

const RuntimeContext = createContext<DocEvidenceRuntime | null>(null);

export function RuntimeProvider({
  runtime,
  children,
}: PropsWithChildren<{ runtime: DocEvidenceRuntime }>) {
  return <RuntimeContext.Provider value={runtime}>{children}</RuntimeContext.Provider>;
}

export function useRuntime(): DocEvidenceRuntime {
  const runtime = useContext(RuntimeContext);
  if (!runtime) throw new Error("DocEvidenceRuntime provider is missing");
  return runtime;
}
