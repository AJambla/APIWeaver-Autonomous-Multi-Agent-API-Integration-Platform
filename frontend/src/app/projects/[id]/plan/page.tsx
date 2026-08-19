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

type PlanStatus = "idle" | "loading" | "ready" | "approved" | "error";

export default function PlanPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const { notify } = useToast();
  const [status, setStatus] = useState<PlanStatus>("idle");
  const [plan, setPlan] = useState<any>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const runs = await apiFetch<any[]>(`/workflows?project_id=${projectId}&limit=1`);
      const latest = runs?.[0];
      if (!latest) {
        setPlan(null);
        setStatus("ready");
        return;
      }
      setPlan(latest);
      setStatus(latest.status === "paused_for_approval" ? "ready" : "ready");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load plan");
      setStatus("error");
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  const approve = useCallback(async () => {
    try {
      await apiFetch(`/workflows/${plan.id}/approve`, {
        method: "POST",
        body: { approved: true, notes: "Approved from UI" },
      });
      setStatus("approved");
      notify("Plan approved. Starting generation…", "success");
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Approval failed", "error");
    }
  }, [plan, notify]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Execution Plan</h1>
        <p className="text-sm text-text-secondary">
          Review the generated execution plan before code generation begins.
        </p>
      </div>

      {status === "loading" && <Card>Loading plan…</Card>}
      {status === "error" && <Card className="text-error">{error}</Card>}

      {status === "ready" && plan && (
        <div className="space-y-4">
          <Card>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Workflow Run</CardTitle>
                <p className="mt-1 text-sm text-text-secondary">
                  Status: <StatusBadge status={plan.status} />
                </p>
              </div>
              {plan.status === "paused_for_approval" && (
                <Button onClick={approve}>Approve Plan</Button>
              )}
            </div>
          </Card>

          <Card>
            <CardTitle>Dependencies</CardTitle>
            <p className="mt-2 text-sm text-text-secondary">
              Endpoint dependency graph is available on the Dependency Graph screen.
            </p>
          </Card>
        </div>
      )}

      {status === "approved" && (
        <Card>
          <p className="text-sm text-text-secondary">Plan approved. Redirecting to Build…</p>
        </Card>
      )}
    </div>
  );
}
