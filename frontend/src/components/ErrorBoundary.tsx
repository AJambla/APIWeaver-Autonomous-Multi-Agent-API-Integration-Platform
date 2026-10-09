import React from 'react';
import { useLocation } from 'react-router-dom';

interface State {
  error: Error | null;
}

interface Props {
  children: React.ReactNode;
  compact?: boolean;
}

/** Catches render errors below it. Without one, a single malformed spec or event payload
 * in ProjectWorkspace unmounted the whole app and left a blank page. */
export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
  }

  render() {
    if (!this.state.error) return this.props.children;
    if (this.props.compact) {
      return (
        <div className="p-8 text-white flex flex-col items-center justify-center gap-3 text-center rounded-lg border border-red-500/20 bg-red-950/10 my-4">
          <h2 className="text-base font-semibold text-red-400">Failed to load this section</h2>
          <p className="max-w-md text-xs text-neutral-400">
            {this.state.error.message || 'An unexpected rendering error occurred in this view.'}
          </p>
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            className="rounded-md border border-white/20 px-3 py-1.5 text-xs hover:bg-white/5"
          >
            Try Again
          </button>
        </div>
      );
    }
    return (
      <div className="min-h-screen bg-black text-white flex flex-col items-center justify-center gap-4 px-4 text-center">
        <h1 className="text-lg font-semibold">Something went wrong on this page.</h1>
        <p className="max-w-md text-sm text-neutral-400">
          The rest of the app is fine. Reload to try again, or go back to the dashboard.
        </p>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded-md bg-white px-4 py-2 text-sm font-medium text-black hover:bg-neutral-200"
          >
            Reload
          </button>
          <a href="/dashboard" className="rounded-md border border-white/20 px-4 py-2 text-sm hover:bg-white/5">
            Dashboard
          </a>
        </div>
      </div>
    );
  }
}

/** Resets on navigation, so leaving a broken page recovers without a reload. */
export const RouteErrorBoundary: React.FC<{ children: React.ReactNode; compact?: boolean }> = ({ children, compact }) => {
  const location = useLocation();
  return <ErrorBoundary key={location.pathname} compact={compact}>{children}</ErrorBoundary>;
};
