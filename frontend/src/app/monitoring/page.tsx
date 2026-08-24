"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { ApiError, type OrgMetrics } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { useAuth } from "@/lib/auth-context";
import { AppShell } from "@/components/AppShell";
import { Card, CardTitle } from "@/components/Card";
import { BarSeriesChart, CHART_COLORS } from "@/components/charts";
import { cn } from "@/lib/cn";

const RANGES = [
  { days: 7, label: "7d" },
  { days: 30, label: "30d" },
  { days: 90, label: "90d" },
];

export default function OrgMonitoringPage() {
  const { user, loading: authLoading } = useAuth();
  const { notify } = useToast();

  const [days, setDays] = useState(30);
  const [metrics, setMetrics] = useState<OrgMetrics | null>(null);
  const [spendSeries, setSpendSeries] = useState<Array<{ label: string; spend: number }>>([]);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);

  const load = useCallback(async () => {
    if (!user?.organization_id) return;
    setLoading(true);
    setForbidden(false);
    try {
      const [m, windows] = await Promise.all([
        apiFetch<OrgMetrics>(`/org/${user.organization_id}/metrics?days=${days}`),
        Promise.all(
          RANGES.map((r) =>
            apiFetch<OrgMetrics>(`/org/${user.organization_id}/metrics?days=${r.days}`).catch(
              () => null,
            ),
          ),
        ),
      ]);
      setMetrics(m);
      setSpendSeries(
        RANGES.map((r, i) => ({
          label: r.label,
          spend: windows[i]?.monthly_token_spend_usd ?? 0,
        })),
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setForbidden(true);
        return;
      }
      notify(err instanceof ApiError ? err.message : "Failed to load org metrics", "error");
    } finally {
      setLoading(false);
    }
  }, [user?.organization_id, days, notify]);

  useEffect(() => {
    if (!authLoading) load();
  }, [authLoading, load]);

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold">Organization Monitoring</h1>
            <p className="text-sm text-text-secondary">
              Cross-project metrics for {user?.organization_name ?? "your organization"}.
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

        {forbidden && (
          <Card className="text-sm text-text-secondary">
            You don&apos;t have permission to view organization billing metrics. Contact an
            organization admin.
          </Card>
        )}

        {loading && <Card>Loading metrics…</Card>}

        {!loading && !forbidden && metrics && (
          <div className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Card>
                <CardTitle>Projects</CardTitle>
                <p className="text-2xl font-bold text-text-primary">{metrics.projects_count}</p>
              </Card>
              <Card>
                <CardTitle>Workflow Runs</CardTitle>
                <p className="text-2xl font-bold text-text-primary">
                  {metrics.total_workflow_runs}
                </p>
              </Card>
              <Card>
                <CardTitle>Token Spend</CardTitle>
                <p className="text-2xl font-bold text-text-primary">
                  ${metrics.monthly_token_spend_usd.toFixed(2)}
                </p>
              </Card>
              <Card>
                <CardTitle>Rate Limit</CardTitle>
                <p className="text-2xl font-bold text-text-primary">
                  {metrics.tier_limit_workflow_triggers_hour}/hr
                </p>
              </Card>
            </div>

            <Card>
              <CardTitle>Avg Test Pass Rate</CardTitle>
              <p className="text-sm text-text-secondary">
                {metrics.avg_test_pass_rate != null
                  ? `${(metrics.avg_test_pass_rate * 100).toFixed(1)}%`
                  : "No test data yet."}
              </p>
            </Card>

            <Card>
              <CardTitle>Token Spend by Window</CardTitle>
              <BarSeriesChart
                data={spendSeries.map((s) => ({ name: s.label, Spend: s.spend }))}
                xKey="name"
                series={[{ key: "Spend", label: "Spend (USD)", color: CHART_COLORS.brand }]}
                height={260}
              />
            </Card>
          </div>
        )}
      </div>
    </AppShell>
  );
}
