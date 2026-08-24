"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { ApiError, type ProjectMetrics, type WorkflowRun } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { Card, CardTitle } from "@/components/Card";
import { MetricsDashboard } from "@/components/MetricsDashboard";
import { AgentHealthPanel } from "@/components/AgentHealthPanel";
import { cn } from "@/lib/cn";

const RANGES = [
  { days: 7, label: "7d" },
  { days: 30, label: "30d" },
  { days: 90, label: "90d" },
];

export default function MonitoringPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const { notify } = useToast();

  const [days, setDays] = useState(30);
  const [metrics, setMetrics] = useState<ProjectMetrics | null>(null);
  const [spendSeries, setSpendSeries] = useState<Array<{ label: string; spend: number }>>([]);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [m, windows, wf] = await Promise.all([
        apiFetch<ProjectMetrics>(`/projects/${projectId}/metrics?days=${days}`),
        Promise.all(
          RANGES.map((r) =>
            apiFetch<ProjectMetrics>(`/projects/${projectId}/metrics?days=${r.days}`).catch(
              () => null,
            ),
          ),
        ),
        apiFetch<WorkflowRun[]>(`/workflows?project_id=${projectId}&limit=20`).catch(() => []),
      ]);
      setMetrics(m);
      setSpendSeries(
        RANGES.map((r, i) => ({
          label: r.label,
          spend: windows[i]?.monthly_token_spend_usd ?? 0,
        })),
      );
      setRuns(wf ?? []);
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Failed to load monitoring", "error");
    } finally {
      setLoading(false);
    }
  }, [projectId, days, notify]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Monitoring</h1>
          <p className="text-sm text-text-secondary">
            Operational metrics and agent health for this integration.
          </p>
        </div>
        <div className="flex gap-1 rounded-md border border-border bg-bg-secondary p-1">
          {RANGES.map((r) => (
            <button
              key={r.days}
              onClick={() => setDays(r.days)}
              className={cn(
                "rounded px-3 py-1 text-sm font-medium transition-colors",
                days === r.days
                  ? "bg-brand-primary text-white"
                  : "text-text-secondary hover:bg-bg-tertiary",
              )}
              aria-pressed={days === r.days}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {loading && <Card>Loading metrics…</Card>}

      {!loading && metrics && (
        <>
          <MetricsDashboard metrics={metrics} spendSeries={spendSeries} runs={runs.length} />
          <AgentHealthPanel runs={runs} />
        </>
      )}

      {!loading && !metrics && (
        <Card className="text-sm text-text-secondary">
          No metrics available for this project yet.
        </Card>
      )}
    </div>
  );
}
