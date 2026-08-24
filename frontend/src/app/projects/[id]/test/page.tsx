"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import {
  ApiError,
  type DependencyGraph,
  type RepairAttempt,
  type TestResult,
  type TestRun,
} from "@/lib/types";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/Button";
import { Card, CardTitle } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs } from "@/components/Tabs";
import { TestCoverageChart } from "@/components/TestCoverageChart";
import { SelfHealingTimeline } from "@/components/SelfHealingTimeline";
import { useWorkflowEvents } from "@/lib/use-workflow-events";
import { cn } from "@/lib/cn";

type Environment = "sandbox" | "live";

export default function TestPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const { notify } = useToast();

  const [runs, setRuns] = useState<TestRun[]>([]);
  const [activeRun, setActiveRun] = useState<TestRun | null>(null);
  const [results, setResults] = useState<TestResult[]>([]);
  const [repairs, setRepairs] = useState<RepairAttempt[]>([]);
  const [endpoints, setEndpoints] = useState<DependencyGraph["nodes"]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [env, setEnv] = useState<Environment>("sandbox");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [tab, setTab] = useState("runs");

  const loadRuns = useCallback(async () => {
    setLoading(true);
    try {
      const [r, g] = await Promise.all([
        apiFetch<TestRun[]>(`/projects/${projectId}/test-runs?limit=20`).catch(() => []),
        apiFetch<DependencyGraph>(`/projects/${projectId}/dependency-graph`).catch(
          () => ({ nodes: [], edges: [] }),
        ),
      ]);
      setRuns(r ?? []);
      setEndpoints(g.nodes ?? []);
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Failed to load tests", "error");
    } finally {
      setLoading(false);
    }
  }, [projectId, notify]);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  const loadResults = useCallback(
    async (runId: string) => {
      try {
        const [r, p] = await Promise.all([
          apiFetch<TestResult[]>(`/projects/${projectId}/test-runs/${runId}/results?limit=100`).catch(
            () => [],
          ),
          apiFetch<RepairAttempt[]>(
            `/projects/${projectId}/test-runs/${runId}/repairs?limit=100`,
          ).catch(() => []),
        ]);
        setResults(r ?? []);
        setRepairs(p ?? []);
      } catch {
        /* ignore partial failures */
      }
    },
    [projectId],
  );

  const selectRun = useCallback(
    async (run: TestRun) => {
      setActiveRun(run);
      setTab("results");
      await loadResults(run.id);
    },
    [loadResults],
  );

  const { connected } = useWorkflowEvents(activeRun?.id ?? null);

  // Poll results while the active run is still in progress.
  useEffect(() => {
    if (!activeRun || activeRun.status === "completed" || activeRun.status === "failed") return;
    const interval = setInterval(() => loadResults(activeRun.id), 3000);
    return () => clearInterval(interval);
  }, [activeRun, loadResults]);

  const runTests = useCallback(async () => {
    setRunning(true);
    try {
      const res = await apiFetch<{ test_run_id: string }>(`/projects/${projectId}/test`, {
        method: "POST",
        body: {
          environment: env,
          endpoint_ids: selected.size > 0 ? Array.from(selected) : undefined,
        },
      });
      notify("Test run started", "success");
      await loadRuns();
      const created: TestRun = {
        id: res.test_run_id,
        status: "running",
        environment: env,
        summary: null,
        created_at: new Date().toISOString(),
      };
      setActiveRun(created);
      setResults([]);
      setRepairs([]);
      setTab("results");
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Failed to start tests", "error");
    } finally {
      setRunning(false);
    }
  }, [projectId, env, selected, notify, loadRuns]);

  const toggleEndpoint = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const passed = results.filter((r) => r.status === "passed").length;
  const failed = results.filter((r) => r.status === "failed").length;
  const skipped = results.filter((r) => r.status === "skipped").length;
  const total = results.length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Testing</h1>
          <p className="text-sm text-text-secondary">
            Run automated tests and review self-healing repairs.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-1 rounded-md border border-border bg-bg-secondary p-1">
            {(["sandbox", "live"] as Environment[]).map((e) => (
              <button
                key={e}
                onClick={() => setEnv(e)}
                className={cn(
                  "rounded px-3 py-1 text-sm font-medium capitalize transition-colors",
                  env === e
                    ? "bg-brand-primary text-white"
                    : "text-text-secondary hover:bg-bg-tertiary",
                )}
              >
                {e}
              </button>
            ))}
          </div>
          <Button onClick={runTests} loading={running}>
            Run Tests
          </Button>
        </div>
      </div>

      {activeRun && activeRun.status !== "completed" && activeRun.status !== "failed" && (
        <Card className="flex items-center gap-2 text-sm">
          <span
            className={cn(
              "inline-block h-2 w-2 rounded-full",
              connected ? "bg-success animate-pulse" : "bg-warning",
            )}
          />
          Live: {connected ? "connected to event stream" : "connecting…"} ·{" "}
          <StatusBadge status={activeRun.status} />
        </Card>
      )}

      <Tabs
        tabs={[
          { id: "runs", label: "Runs" },
          { id: "results", label: "Results" },
          { id: "coverage", label: "Coverage" },
        ]}
        active={tab}
        onChange={setTab}
      />

      {tab === "runs" && (
        <div className="space-y-4">
          <Card>
            <CardTitle>Targeted Endpoints</CardTitle>
            <p className="mb-2 text-xs text-text-secondary">
              Leave all unselected to test the entire spec.
            </p>
            <div className="flex flex-wrap gap-2">
              {endpoints.length === 0 && (
                <span className="text-xs text-text-secondary">No endpoints discovered.</span>
              )}
              {endpoints.map((ep) => (
                <button
                  key={ep.id}
                  onClick={() => toggleEndpoint(ep.id)}
                  className={cn(
                    "rounded-full border px-2.5 py-1 text-xs font-mono transition-colors",
                    selected.has(ep.id)
                      ? "border-brand-primary bg-brand-primary text-white"
                      : "border-border text-text-secondary hover:bg-bg-tertiary",
                  )}
                >
                  {ep.method} {ep.path}
                </button>
              ))}
            </div>
          </Card>

          <div className="space-y-3">
            {loading && <Card>Loading runs…</Card>}
            {!loading && runs.length === 0 && (
              <Card className="text-sm text-text-secondary">No test runs yet.</Card>
            )}
            {runs.map((run) => (
              <Card key={run.id} className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">
                    <StatusBadge status={run.status} /> {run.environment}
                  </p>
                  <p className="text-xs text-text-secondary">
                    {new Date(run.created_at).toLocaleString()}
                  </p>
                </div>
                <Button variant="secondary" size="sm" onClick={() => selectRun(run)}>
                  View
                </Button>
              </Card>
            ))}
          </div>
        </div>
      )}

      {tab === "results" && (
        <div className="space-y-4">
          {activeRun ? (
            <>
              <div className="grid gap-4 md:grid-cols-4">
                <Card>
                  <CardTitle>Passed</CardTitle>
                  <p className="text-2xl font-bold text-success">{passed}</p>
                </Card>
                <Card>
                  <CardTitle>Failed</CardTitle>
                  <p className="text-2xl font-bold text-error">{failed}</p>
                </Card>
                <Card>
                  <CardTitle>Skipped</CardTitle>
                  <p className="text-2xl font-bold text-warning">{skipped}</p>
                </Card>
                <Card>
                  <CardTitle>Total</CardTitle>
                  <p className="text-2xl font-bold">{total}</p>
                </Card>
              </div>

              <div className="space-y-2">
                {results.length === 0 && (
                  <Card className="text-sm text-text-secondary">
                    No results yet — results stream in as tests execute.
                  </Card>
                )}
                {results.map((r) => (
                  <Card key={r.id} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-medium">
                          <StatusBadge status={r.status} />{" "}
                          <span className="font-mono text-xs">{r.endpoint_id}</span>
                        </p>
                        <p className="text-xs text-text-secondary">
                          {r.status_code ?? "—"} · {r.latency_ms ?? "—"}ms
                          {r.error ? ` · ${r.error}` : ""}
                        </p>
                      </div>
                    </div>
                    {r.status === "failed" && (
                      <SelfHealingTimeline repairs={repairs} testResultId={r.id} />
                    )}
                  </Card>
                ))}
              </div>
            </>
          ) : (
            <Card className="text-sm text-text-secondary">Select a test run to view results.</Card>
          )}
        </div>
      )}

      {tab === "coverage" && (
        <Card>
          <CardTitle>Test Coverage</CardTitle>
          <div className="mt-4 max-w-md">
            <TestCoverageChart passed={passed} failed={failed} skipped={skipped} />
          </div>
        </Card>
      )}
    </div>
  );
}
