"use client";

import { useEffect } from "react";
import Link from "next/link";
import { Button } from "@/components/Button";

/**
 * Route-level error boundary. Distinguishes platform errors (our fault, retry
 * available) from target-API errors (the user's API returned an error). The
 * error payload from apiFetch carries a `code` we can inspect.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { code?: string; status?: number };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error(error);
  }, [error]);

  const isTargetApiError = error?.code === "TARGET_API_ERROR" || error?.status === 502;
  const isPlatform = !isTargetApiError;

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-8 text-center">
      <p className="text-5xl font-bold text-error">
        {isPlatform ? "500" : "502"}
      </p>
      <h1 className="text-xl font-semibold">
        {isPlatform ? "Agent Failure" : "Target API Error"}
      </h1>
      <p className="max-w-md text-sm text-text-secondary">
        {isPlatform
          ? "Something went wrong on our side while running the agent. You can retry the operation."
          : "The target API returned an error. Review the raw response below and check your API configuration."}
      </p>
      {error?.message && (
        <pre className="max-w-lg overflow-x-auto rounded-md border border-border bg-bg-secondary p-3 text-left text-xs">
          {error.message}
        </pre>
      )}
      <div className="flex gap-2">
        {isPlatform && (
          <Button onClick={reset}>Retry</Button>
        )}
        <Link href="/dashboard">
          <Button variant="secondary">Back to Dashboard</Button>
        </Link>
      </div>
    </div>
  );
}
