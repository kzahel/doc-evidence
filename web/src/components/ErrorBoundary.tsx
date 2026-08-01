import { Component, type ErrorInfo, type ReactNode } from "react";

import { FailureState } from "./AsyncState";

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("doc-evidence interface error", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      return <FailureState title="The interface stopped unexpectedly" error={this.state.error} />;
    }
    return this.props.children;
  }
}
