import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Last-line-of-defense boundary — if a component throws during render,
 * we show a small banner with a reset button instead of letting React
 * unmount the entire app. The banner does not try to be pretty; it's
 * here purely so the chat surface never disappears silently.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: { componentStack?: string }): void {
    // eslint-disable-next-line no-console
    console.error("ErrorBoundary caught:", error, info?.componentStack);
  }

  reset = () => this.setState({ error: null });

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="error-boundary">
        <h2>Something went wrong rendering the chat.</h2>
        <pre>{this.state.error.message}</pre>
        <button type="button" className="btn-secondary" onClick={this.reset}>
          Try again
        </button>
        <button
          type="button"
          className="btn-secondary"
          onClick={() => window.location.reload()}
        >
          Reload page
        </button>
      </div>
    );
  }
}
