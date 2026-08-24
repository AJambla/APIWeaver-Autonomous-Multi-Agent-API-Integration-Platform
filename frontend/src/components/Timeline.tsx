"use client";

import { cn } from "@/lib/cn";
import { StatusBadge } from "@/components/StatusBadge";

export interface TimelineEntry {
  id: string;
  title: string;
  subtitle?: string;
  status?: string;
  timestamp?: string | null;
  meta?: React.ReactNode;
  children?: React.ReactNode;
  accent?: string;
}

export function Timeline({
  entries,
  orientation = "vertical",
}: {
  entries: TimelineEntry[];
  orientation?: "vertical" | "horizontal";
}) {
  if (entries.length === 0) {
    return (
      <p className="rounded-lg border border-border bg-bg-secondary p-6 text-center text-sm text-text-secondary">
        Nothing to show yet.
      </p>
    );
  }

  if (orientation === "horizontal") {
    return (
      <ol className="flex flex-col gap-4 md:flex-row md:gap-0">
        {entries.map((e, i) => (
          <li key={e.id} className="relative flex-1">
            <div className="flex flex-col items-center px-2 text-center">
              <span
                className={cn(
                  "z-10 flex h-8 w-8 items-center justify-center rounded-full text-sm font-semibold",
                  e.accent ?? "bg-brand-primary text-white",
                )}
              >
                {i + 1}
              </span>
              <p className="mt-2 text-sm font-medium text-text-primary">{e.title}</p>
              {e.subtitle && (
                <p className="text-xs text-text-secondary">{e.subtitle}</p>
              )}
              {e.status && (
                <span className="mt-1">
                  <StatusBadge status={e.status} />
                </span>
              )}
            </div>
            {i < entries.length - 1 && (
              <span
                className="absolute left-1/2 top-4 hidden h-0.5 w-full -translate-y-1/2 bg-border md:block"
                aria-hidden="true"
              />
            )}
          </li>
        ))}
      </ol>
    );
  }

  return (
    <ol className="relative space-y-4 border-l border-border pl-6">
      {entries.map((e) => (
        <li key={e.id} className="relative">
          <span
            className={cn(
              "absolute -left-[31px] top-1 h-3 w-3 rounded-full ring-4 ring-bg-primary",
              e.accent ?? "bg-brand-primary",
            )}
            aria-hidden="true"
          />
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm font-medium text-text-primary">{e.title}</p>
            {e.timestamp && (
              <time className="text-xs text-text-secondary">
                {new Date(e.timestamp).toLocaleString()}
              </time>
            )}
          </div>
          {e.subtitle && (
            <p className="text-xs text-text-secondary">{e.subtitle}</p>
          )}
          {e.status && (
            <div className="mt-1">
              <StatusBadge status={e.status} />
            </div>
          )}
          {e.meta && <div className="mt-2">{e.meta}</div>}
          {e.children && <div className="mt-2">{e.children}</div>}
        </li>
      ))}
    </ol>
  );
}
