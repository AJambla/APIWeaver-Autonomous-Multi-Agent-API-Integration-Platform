"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { ApiError, type Project } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { AppShell } from "@/components/AppShell";
import { Card, CardTitle } from "@/components/Card";
import { Tabs } from "@/components/Tabs";
import { StatusBadge } from "@/components/StatusBadge";
import { Table, type Column } from "@/components/Table";

interface Endpoint {
  id: string;
  method: string;
  path: string;
  summary?: string | null;
  deprecated?: boolean;
  is_destructive?: boolean;
  confidence_score?: number | null;
}

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "spec", label: "Spec" },
  { id: "workflows", label: "Workflows" },
  { id: "code", label: "Code" },
  { id: "tests", label: "Tests" },
  { id: "exports", label: "Exports" },
];

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const { notify } = useToast();

  const [project, setProject] = useState<Project | null>(null);
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [tab, setTab] = useState("overview");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, eps] = await Promise.all([
        apiFetch<Project>(`/projects/${projectId}`),
        apiFetch<Endpoint[]>(`/projects/${projectId}/endpoints?limit=200`),
      ]);
      setProject(p);
      setEndpoints(eps);
    } catch (err) {
      notify(
        err instanceof ApiError ? err.message : "Failed to load project",
        "error",
      );
    } finally {
      setLoading(false);
    }
  }, [projectId, notify]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !project) {
    return (
      <AppShell projectId={projectId}>
        <Card>Loading project…</Card>
      </AppShell>
    );
  }

  if (!project) {
    return (
      <AppShell projectId={projectId}>
        <Card className="text-center">
          <p className="text-text-secondary">
            This project doesn’t exist or you don’t have access.
          </p>
        </Card>
      </AppShell>
    );
  }

  const endpointColumns: Array<Column<Endpoint>> = [
    {
      key: "method",
      header: "Method",
      render: (e) => (
        <span className="font-mono text-xs font-semibold text-brand-primary">{e.method}</span>
      ),
    },
    { key: "path", header: "Path", render: (e) => <span className="font-mono text-xs">{e.path}</span> },
    { key: "summary", header: "Summary", render: (e) => e.summary ?? "—" },
    {
      key: "deprecated",
      header: "Flags",
      render: (e) => (
        <span className="flex gap-1">
          {e.deprecated && (
            <span className="rounded bg-warning/10 px-1.5 py-0.5 text-xs text-warning">
              deprecated
            </span>
          )}
          {e.is_destructive && (
            <span className="rounded bg-error/10 px-1.5 py-0.5 text-xs text-error">
              destructive
            </span>
          )}
        </span>
      ),
    },
  ];

  return (
    <AppShell projectId={projectId}>
      <div className="mb-4 flex items-center gap-3">
        <h1 className="text-2xl font-bold">{project.name}</h1>
        <StatusBadge status={project.status} />
      </div>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      <div className="mt-6">
        {tab === "overview" && (
          <div className="grid gap-4 md:grid-cols-3">
            <Card>
              <CardTitle>Endpoints</CardTitle>
              <p className="text-3xl font-bold">{endpoints.length}</p>
            </Card>
            <Card>
              <CardTitle>Last run</CardTitle>
              <p className="text-3xl font-bold">
                {project.last_run_status ? (
                  <StatusBadge status={project.last_run_status} />
                ) : (
                  "—"
                )}
              </p>
            </Card>
            <Card>
              <CardTitle>Status</CardTitle>
              <p className="text-3xl font-bold">
                <StatusBadge status={project.status} />
              </p>
            </Card>
          </div>
        )}

        {tab === "spec" && (
          <Table
            columns={endpointColumns}
            rows={endpoints}
            emptyMessage="No endpoints discovered yet. Upload an API spec to get started."
          />
        )}

        {tab !== "overview" && tab !== "spec" && (
          <Card className="text-center text-text-secondary">
            The {TABS.find((t) => t.id === tab)?.label} view is coming soon.
          </Card>
        )}
      </div>
    </AppShell>
  );
}
