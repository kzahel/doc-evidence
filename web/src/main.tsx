import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { consumeLaunchToken } from "./api/auth";
import { createHttpRuntime } from "./api/httpRuntime";
import { RuntimeProvider } from "./api/RuntimeProvider";
import { FailureState } from "./components/AsyncState";
import { ErrorBoundary } from "./components/ErrorBoundary";
import "./styles/global.css";

const container = document.getElementById("root");
if (!container) throw new Error("Application root is missing");
const root = createRoot(container);

try {
  const launchToken = consumeLaunchToken();
  const runtime = createHttpRuntime(window.location.origin, launchToken);
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
            <App />
          </QueryClientProvider>
        </RuntimeProvider>
      </ErrorBoundary>
    </StrictMode>,
  );
} catch (error) {
  root.render(<FailureState title="Secure local launch required" error={error} />);
}
