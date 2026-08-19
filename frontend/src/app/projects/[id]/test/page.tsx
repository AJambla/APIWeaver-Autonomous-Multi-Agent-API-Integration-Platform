"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { ApiError } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/Button";
import { Card, CardTitle } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs } from "@/components/Tabs";

type TestRun = {
  id: string;
  status: string;
  environment: string;
  summary: { passed: number; failed: number; skipped: number; total: number } | null;
  created_at: string;
};

type TestResult = {
  id: string;
  endpoint_id: string;
  status: string;
  status_code: number | null;
  latency_ms: number | null;
  response_snapshot: any;
};

type RepairAttempt = {
  id: string;
  attempt_number: number;
  failure_classification: string | null;
  outcome: string | null;
};

export default function TestPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const { notify } = useToast();
  const [runs, setRuns] = useState<TestRun[]>([]);
  const [activeRun, setActiveRun] = useState<TestRun | null>(null);
  const [results, setResults] = useState<TestResult[]>([]);
  const [repairs, setRepairs] = useState<RepairAttempt[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [tab, setTab] = useState("runs");

  const loadRuns = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<TestRun[]>(`/projects/${projectId}/test-runs?limit=20`);
      setRuns(data ?? []);
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Failed to load test runs", "error");
    } finally {
      setLoading(false);
    }
  }, [projectId, notify]);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  const runTests = useCallback(async () => {
    setRunning(true);
    try {
      const res = await apiFetch<{ test_run_id: string }>(`/projects/${projectId}/test`, {
        method: "POST",
        body: { environment: "sandbox" },
      });
      notify("Test run started", "success");
      await loadRuns();
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Failed to start tests", "error");
    } finally {
      setRunning(false);
    }
  }, [projectId, notify, loadRuns]);

  const selectRun = useCallback(async (run: TestRun) => {
    setActiveRun(run);
    setTab("results");
    try {
      const [r, p] = await Promise.all([
        apiFetch<TestResult[]>(`/projects/${projectId}/test-runs/${run.id}/results?limit=100`).catch(() => []),
        apiFetch<RepairAttempt[]>(`/projects/${projectId}/test-runs/${run.id}/repairs?limit=100`).catch(() => []),
      ]);
      setResults(r ?? []);
      setRepairs(p ?? []);
    } catch {
      // ignore partial failures
    }
  }, [projectId]);

  const passed = results.filter((r) => r.status === "passed").length;
  const failed = results.filter((r) => r.status === "failed").length;
  const skipped = results.filter((r) => r.status === "skipped").length;
  const total = results.length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Testing</h1>
          <p className="text-sm text-text-secondary">
            Run automated tests and review self-healing repairs.
          </p>
        </div>
        <Button onClick={runTests} loading={running}>
          Run All Tests
        </Button>
      </div>

      <Tabs tabs={[{ id: "runs", label: "Runs" }, { id: "results", label: "Results" }]} active={tab} onChange={setTab} />

      {tab === "runs" && (
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
                {results.map((r) => (
                  <Card key={r.id} className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium">
                        <StatusBadge status={r.status} />{" "}
                        <span className="font-mono text-xs">{r.endpoint_id}</span>
                      </p>
                      <p className="text-xs text-text-secondary">
                        {r.status_code ?? "—"} · {r.latency_ms ?? "—"}ms
                      </p>
                    </div>
                  </Card>
                ))}
              </div>

              {repairs.length > 0 && (
                <Card>
                  <CardTitle>Repair Attempts</CardTitle>
                  <div className="mt-2 space-y-2">
                    {repairs.map((rp) => (
                      <div key={rp.id} className="text-sm">
                        <span className="font-medium">#{rp.attempt_number}</span>{" "}
                        <span className="text-text-secondary">{rp.failure_classification}</span>{" "}
                        <StatusBadge status={rp.outcome ?? "unknown"} />
                      </div>
                    ))}
                  </div>
                </Card>
              )}
            </>
          ) : (
            <Card className="text-sm text-text-secondary">Select a test run to view results.</Card>
          )}
        </div>
      )}
    </div>
  );
}
