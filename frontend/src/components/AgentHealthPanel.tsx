"use client";

import { Card, CardTitle } from "@/components/Card";
import { Table, type Column } from "@/components/Table";
import { StatusBadge } from "@/components/StatusBadge";
import type { WorkflowRun } from "@/lib/types";

function duration(run: WorkflowRun): string {
  if (!run.started_at) return "—";
  const end = run.completed_at ? new Date(run.completed_at) : new Date();
  const mins = (end.getTime() - new Date(run.started_at).getTime()) / 60000;
  return mins > 0 ? `${mins.toFixed(1)} min` : "<1 min";
}

/**
 * Agent health is derived from real workflow-run history: each run represents an
 * agent execution pipeline, so the activity feed + aggregate error/latency
 * figures reflect actual platform behavior.
 */
export function AgentHealthPanel({ runs }: { runs: WorkflowRun[] }) {
  const total = runs.length;
  const completed = runs.filter((r) => r.status === "completed").length;
  const failed = runs.filter((r) => r.status === "failed").length;
  const errorRate = total > 0 ? failed / total : 0;
  const avgLatency =
    total > 0
      ? runs.reduce((s, r) => {
          if (!r.started_at) return s;
          const end = r.completed_at ? new Date(r.completed_at) : new Date();
          return s + (end.getTime() - new Date(r.started_at).getTime()) / 60000;
        }, 0) / total
      : 0;

  const columns: Array<Column<WorkflowRun>> = [
    {
      key: "status",
      header: "Status",
      render: (r) => <StatusBadge status={r.status} />,
    },
    {
      key: "current_node",
      header: "Agent / Stage",
      render: (r) => (
        <span className="font-mono text-xs">
          {r.current_node ?? (r.status === "completed" ? "pipeline" : "—")}
        </span>
      ),
    },
    { key: "duration", header: "Latency", render: (r) => duration(r) },
    {
      key: "total_tokens_used",
      header: "Tokens",
      render: (r) => r.total_tokens_used?.toLocaleString() ?? "—",
    },
  ];

  return (
    <Card className="space-y-4">
      <div className="flex items-center justify-between">
        <CardTitle>Agent Health</CardTitle>
        <div className="flex gap-4 text-xs text-text-secondary">
          <span>
            Error rate:{" "}
            <span className={errorRate > 0.2 ? "text-error" : "text-success"}>
              {(errorRate * 100).toFixed(0)}%
            </span>
          </span>
          <span>Avg latency: {avgLatency.toFixed(1)} min</span>
        </div>
      </div>
      <Table
        columns={columns}
        rows={runs.slice(0, 10)}
        emptyMessage="No agent activity recorded yet."
      />
    </Card>
  );
}
