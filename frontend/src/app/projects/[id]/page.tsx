"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { ApiError, type Project } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { AppShell } from "@/components/AppShell";
import { Card, CardTitle } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";

interface Endpoint {
  id: string;
  method: string;
  path: string;
  summary?: string | null;
  deprecated?: boolean;
  is_destructive?: boolean;
  confidence_score?: number | null;
}

export default function ProjectOverviewPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const { notify } = useToast();

  const [project, setProject] = useState<Project | null>(null);
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
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

  return (
    <AppShell projectId={projectId}>
      <div className="mb-4 flex items-center gap-3">
        <h1 className="text-2xl font-bold">{project.name}</h1>
        <StatusBadge status={project.status} />
      </div>

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

      <div className="mt-8">
        <h2 className="mb-4 text-lg font-semibold">Endpoints</h2>
        {endpoints.length === 0 ? (
          <Card className="text-center text-text-secondary">
            No endpoints discovered yet. Upload an API spec to get started.
          </Card>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full border-collapse text-sm">
              <thead className="bg-bg-tertiary text-left text-text-secondary">
                <tr>
                  <th className="px-4 py-3 font-semibold">Method</th>
                  <th className="px-4 py-3 font-semibold">Path</th>
                  <th className="px-4 py-3 font-semibold">Summary</th>
                  <th className="px-4 py-3 font-semibold">Flags</th>
                </tr>
              </thead>
              <tbody>
                {endpoints.map((ep) => (
                  <tr key={ep.id} className="border-t border-border">
                    <td className="px-4 py-3">
                      <span className="font-mono text-xs font-semibold text-brand-primary">
                        {ep.method}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">{ep.path}</td>
                    <td className="px-4 py-3">{ep.summary ?? "—"}</td>
                    <td className="px-4 py-3">
                      <span className="flex gap-1">
                        {ep.deprecated && (
                          <span className="rounded bg-warning/10 px-1.5 py-0.5 text-xs text-warning">
                            deprecated
                          </span>
                        )}
                        {ep.is_destructive && (
                          <span className="rounded bg-error/10 px-1.5 py-0.5 text-xs text-error">
                            destructive
                          </span>
                        )}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AppShell>
  );
}
