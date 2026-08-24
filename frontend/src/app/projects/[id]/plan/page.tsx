"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import {
  ApiError,
  type DependencyGraph,
  type WorkflowRun,
  type WorkflowStage,
} from "@/lib/types";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/Button";
import { Card, CardTitle } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs } from "@/components/Tabs";
import { Modal } from "@/components/Modal";
import { ProgressStepper } from "@/components/ProgressStepper";
import { DependencyGraphView } from "@/components/DependencyGraphView";
import { CodeBlock } from "@/components/CodeBlock";

function mapStage(currentNode: string | null | undefined, status: string): WorkflowStage | null {
  if (status === "paused_for_approval") return "plan";
  if (!currentNode) return null;
  const node = currentNode.toLowerCase();
  if (node.includes("plan")) return "plan";
  if (node.includes("generat") || node.includes("build")) return "generate";
  if (node.includes("test")) return "test";
  if (node.includes("export")) return "export";
  return null;
}

function buildPlanText(graph: DependencyGraph, run: WorkflowRun | null): string {
  const lines: string[] = [];
  lines.push("# Execution Plan");
  lines.push("");
  lines.push(`workflow_run_id: ${run?.id ?? "pending"}`);
  lines.push("stages:");
  lines.push("  - plan");
  lines.push("  - generate");
  lines.push("  - test");
  lines.push("  - export");
  lines.push("");
  lines.push(`endpoints_discovered: ${graph.nodes.length}`);
  lines.push("");
  lines.push("endpoints:");
  graph.nodes
    .slice(0, 50)
    .forEach((n) =>
      lines.push(
        `  - ${n.method} ${n.path}${n.is_destructive ? "  # destructive" : ""}`,
      ),
    );
  if (graph.nodes.length === 0) lines.push("  (none yet — upload API docs to generate a spec)");
  lines.push("");
  lines.push("dependencies:");
  graph.edges
    .slice(0, 50)
    .forEach((e) =>
      lines.push(
        `  - ${e.from_id} -> ${e.to_id} (${e.relationship})`,
      ),
    );
  return lines.join("\n");
}

export default function PlanPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const { notify } = useToast();

  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [graph, setGraph] = useState<DependencyGraph>({ nodes: [], edges: [] });
  const [tab, setTab] = useState("plan");
  const [loading, setLoading] = useState(true);
  const [approveOpen, setApproveOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [runs, g] = await Promise.all([
        apiFetch<WorkflowRun[]>(`/workflows?project_id=${projectId}&limit=1`).catch(() => []),
        apiFetch<DependencyGraph>(`/projects/${projectId}/dependency-graph`).catch(
          () => ({ nodes: [], edges: [] }),
        ),
      ]);
      setRun(runs?.[0] ?? null);
      setGraph(g);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load plan");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  const decide = useCallback(
    async (approved: boolean) => {
      if (!run) return;
      setBusy(true);
      try {
        await apiFetch(`/workflows/${run.id}/approve`, {
          method: "POST",
          body: {
            approved,
            notes: approved ? "Approved from UI" : "Changes requested from UI",
          },
        });
        notify(
          approved ? "Plan approved. Starting generation…" : "Changes requested.",
          approved ? "success" : "info",
        );
        setApproveOpen(false);
        await load();
      } catch (err) {
        notify(err instanceof ApiError ? err.message : "Action failed", "error");
      } finally {
        setBusy(false);
      }
    },
    [run, notify, load],
  );

  const stage = mapStage(run?.current_node, run?.status ?? "queued");
  const planText = buildPlanText(graph, run);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Execution Plan</h1>
        <p className="text-sm text-text-secondary">
          Review the dependency graph and approve the plan before code generation.
        </p>
      </div>

      {loading && <Card>Loading plan…</Card>}
      {error && !loading && <Card className="text-error">{error}</Card>}

      {!loading && (
        <>
          <Card>
            <CardTitle>Pipeline Progress</CardTitle>
            <div className="mt-4">
              <ProgressStepper currentStage={stage} status={run?.status ?? "queued"} />
            </div>
            {run && (
              <div className="mt-4 flex items-center gap-3 text-sm text-text-secondary">
                <StatusBadge status={run.status} />
                <span>{run.current_node ?? "Awaiting start"}</span>
              </div>
            )}
          </Card>

          <Tabs
            tabs={[
              { id: "plan", label: "Plan" },
              { id: "graph", label: `Dependency Graph (${graph.nodes.length})` },
            ]}
            active={tab}
            onChange={setTab}
          />

          {tab === "plan" && (
            <Card className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Proposed Execution Plan</CardTitle>
                  <p className="mt-1 text-sm text-text-secondary">
                    {graph.nodes.length} endpoints · {graph.edges.length} dependencies detected.
                  </p>
                </div>
                {run?.status === "paused_for_approval" && (
                  <Button onClick={() => setApproveOpen(true)}>Review &amp; Approve</Button>
                )}
              </div>
              <CodeBlock code={planText} language="yaml" height={320} />
              {run?.status === "paused_for_approval" && (
                <div className="flex justify-end gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => decide(false)}
                    loading={busy}
                  >
                    Request Changes
                  </Button>
                  <Button onClick={() => decide(true)} loading={busy}>
                    Approve Plan
                  </Button>
                </div>
              )}
            </Card>
          )}

          {tab === "graph" && (
            <DependencyGraphView graph={graph} />
          )}
        </>
      )}

      <Modal
        open={approveOpen}
        onClose={() => setApproveOpen(false)}
        title="Approve Execution Plan"
      >
        <p className="mb-3 text-sm text-text-secondary">
          Review the generated plan below. Approving begins code generation. Requesting
          changes stops the workflow so you can adjust the spec.
        </p>
        <CodeBlock code={planText} language="yaml" height={300} />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => decide(false)} loading={busy}>
            Request Changes
          </Button>
          <Button onClick={() => decide(true)} loading={busy}>
            Approve Plan
          </Button>
        </div>
      </Modal>
    </div>
  );
}
