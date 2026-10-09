import React from 'react';
import { useLocation } from 'react-router-dom';

interface State {
  error: Error | null;
}

/** Catches render errors below it. Without one, a single malformed spec or event payload
 * in ProjectWorkspace unmounted the whole app and left a blank page. */
class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
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
export const RouteErrorBoundary: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const location = useLocation();
  return <ErrorBoundary key={location.pathname}>{children}</ErrorBoundary>;
};
