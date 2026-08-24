"use client";

import { Card, CardTitle } from "@/components/Card";
import { BarSeriesChart, CHART_COLORS } from "@/components/charts";
import type { ProjectMetrics } from "@/lib/types";

function Kpi({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <Card>
      <CardTitle>{label}</CardTitle>
      <p className="text-2xl font-bold text-text-primary">{value}</p>
      {hint && <p className="mt-1 text-xs text-text-secondary">{hint}</p>}
    </Card>
  );
}

export function MetricsDashboard({
  metrics,
  spendSeries,
  runs,
}: {
  metrics: ProjectMetrics;
  spendSeries: Array<{ label: string; spend: number }>;
  runs: number;
}) {
  const passRate = metrics.test_pass_rate;
  const tti = metrics.avg_time_to_integration_minutes;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi
          label="Test Pass Rate"
          value={passRate != null ? `${(passRate * 100).toFixed(1)}%` : "—"}
          hint="Across completed test runs"
        />
        <Kpi
          label="Avg Time to Integration"
          value={tti != null ? `${tti.toFixed(1)} min` : "—"}
          hint="Completed workflows"
        />
        <Kpi
          label="Token Spend"
          value={
            metrics.monthly_token_spend_usd != null
              ? `$${metrics.monthly_token_spend_usd.toFixed(2)}`
              : "$0.00"
          }
          hint="Trailing window"
        />
        <Kpi label="Workflow Runs" value={String(metrics.total_workflow_runs)} hint={`${metrics.successful_exports} exports`} />
      </div>

      <Card>
        <CardTitle>Token Spend by Window</CardTitle>
        <p className="mb-3 text-xs text-text-secondary">
          Aggregated token spend (USD) across trailing time windows.
        </p>
        <BarSeriesChart
          data={spendSeries.map((s) => ({ name: s.label, Spend: s.spend }))}
          xKey="name"
          series={[{ key: "Spend", label: "Spend (USD)", color: CHART_COLORS.brand }]}
          height={260}
        />
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardTitle>Throughput</CardTitle>
          <p className="text-sm text-text-secondary">
            {runs} workflow run{runs === 1 ? "" : "s"} in the selected window.
          </p>
        </Card>
        <Card>
          <CardTitle>Reliability</CardTitle>
          <p className="text-sm text-text-secondary">
            {metrics.successful_exports} successful export
            {metrics.successful_exports === 1 ? "" : "s"} shipped.
          </p>
        </Card>
        <Card>
          <CardTitle>Quality</CardTitle>
          <p className="text-sm text-text-secondary">
            {passRate != null
              ? `${(passRate * 100).toFixed(1)}% of tests passing.`
              : "No test data yet."}
          </p>
        </Card>
      </div>
    </div>
  );
}
