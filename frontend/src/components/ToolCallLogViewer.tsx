"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";

export interface ToolCall {
  id: string | number;
  tool_name: string;
  arguments?: Record<string, any> | null;
  result?: Record<string, any> | null;
  duration_ms?: number | null;
}

function JsonNode({ data, name, depth }: { data: any; name?: string; depth?: number }) {
  const [open, setOpen] = useState(depth !== undefined && depth < 1);
  const isObject = data !== null && typeof data === "object";

  if (!isObject) {
    return (
      <div className="ml-4 text-xs">
        {name !== undefined && <span className="text-brand-accent">{name}: </span>}
        <span className="text-text-primary">{JSON.stringify(data)}</span>
      </div>
    );
  }

  const entries = Array.isArray(data)
    ? data.map((v, i) => [i, v] as const)
    : Object.entries(data);

  return (
    <div className="ml-4 text-xs">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="font-mono text-text-secondary hover:text-text-primary"
        aria-expanded={open}
      >
        <span className="inline-block w-3">{open ? "▾" : "▸"}</span>
        {name !== undefined && <span className="text-brand-accent">{name}</span>}
        <span className="text-text-secondary">
          {" "}
          {Array.isArray(data) ? `[${entries.length}]` : `{${entries.length}}`}
        </span>
      </button>
      {open && (
        <div className="border-l border-border pl-2">
          {entries.map(([k, v]) => (
            <JsonNode key={String(k)} name={String(k)} data={v} depth={(depth ?? 0) + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

export function ToolCallLogViewer({ calls }: { calls: ToolCall[] }) {
  if (calls.length === 0) {
    return (
      <p className="text-sm text-text-secondary">No tool calls recorded for this run.</p>
    );
  }

  return (
    <div className="space-y-2">
      {calls.map((c) => (
        <details
          key={c.id}
          className="group rounded-md border border-border bg-bg-secondary"
        >
          <summary className="flex cursor-pointer items-center justify-between px-3 py-2 text-sm">
            <span className="font-mono font-medium text-text-primary">{c.tool_name}</span>
            <span className="text-xs text-text-secondary">
              {c.duration_ms != null ? `${c.duration_ms}ms` : "—"}
            </span>
          </summary>
          <div className="space-y-2 border-t border-border px-3 py-2">
            {c.arguments != null && (
              <div>
                <p className="mb-1 text-xs font-semibold text-text-secondary">Arguments</p>
                <JsonNode data={c.arguments} />
              </div>
            )}
            {c.result != null && (
              <div>
                <p className="mb-1 text-xs font-semibold text-text-secondary">Result</p>
                <JsonNode data={c.result} />
              </div>
            )}
          </div>
        </details>
      ))}
    </div>
  );
}
