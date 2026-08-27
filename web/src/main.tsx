import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { consumeLaunchToken } from "./api/auth";
import { createHttpRuntime } from "./api/httpRuntime";
import { RuntimeProvider } from "./api/RuntimeProvider";
import { FailureState } from "./components/AsyncState";
import { DesktopUpdater } from "./components/DesktopUpdater";
import { ErrorBoundary } from "./components/ErrorBoundary";
import type { DesktopUpdateRuntime } from "./updater/runtime";
import "./styles/global.css";

const container = document.getElementById("root");
if (!container) throw new Error("Application root is missing");
const root = createRoot(container);

function renderApplication(
  runtime: import("./api/runtime").DocEvidenceRuntime,
  updater: DesktopUpdateRuntime | null = null,
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: 1, staleTime: 15_000 },
    },
  });
  root.render(
    <StrictMode>
      <ErrorBoundary>
        <RuntimeProvider runtime={runtime}>
          <QueryClientProvider client={queryClient}>
            <DesktopUpdater runtime={updater} />
            <App />
          </QueryClientProvider>
        </RuntimeProvider>
      </ErrorBoundary>
    </StrictMode>,
  );
}

async function bootstrap() {
  try {
    if ("__TAURI_INTERNALS__" in window) {
      const { createDesktopRuntime } = await import("./api/desktopRuntime");
      const desktop = await createDesktopRuntime();
      renderApplication(desktop.runtime, desktop.updater);
      await desktop.monitor((message) => {
        root.render(<FailureState title="Desktop engine stopped" error={message} />);
      });
      return;
    }
    const launchToken = consumeLaunchToken();
    renderApplication(createHttpRuntime(window.location.origin, launchToken));
  } catch (error) {
    root.render(<FailureState title="Secure local launch required" error={error} />);
  }
}

void bootstrap();
