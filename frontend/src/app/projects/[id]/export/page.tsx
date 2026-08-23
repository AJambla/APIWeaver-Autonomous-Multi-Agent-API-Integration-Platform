"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { ApiError } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/Button";
import { Card, CardTitle } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";

type ExportType = "sdk" | "client" | "fastapi" | "docker" | "github" | "mcp" | "docs" | "cicd";

export default function ExportPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const { notify } = useToast();
  const [selected, setSelected] = useState<ExportType[]>(["sdk"]);
  const [githubRepo, setGithubRepo] = useState("");
  const [busy, setBusy] = useState(false);
  const [exports, setExports] = useState<any[]>([]);

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<any[]>(`/projects/${projectId}/exports?limit=20`);
      setExports(data ?? []);
    } catch {
      // ignore
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  const toggle = (type: ExportType) => {
    setSelected((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type],
    );
  };

  const submit = useCallback(async () => {
    setBusy(true);
    try {
      await apiFetch(`/projects/${projectId}/export`, {
        method: "POST",
        body: {
          export_types: selected,
          github: selected.includes("github") ? { repo_full_name: githubRepo } : undefined,
        },
      });
      notify("Export started", "success");
      await load();
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Export failed", "error");
    } finally {
      setBusy(false);
    }
  }, [projectId, selected, githubRepo, notify, load]);

  const exportMCP = useCallback(async () => {
    setBusy(true);
    try {
      const res = await apiFetch<{ tools_generated: number }>(`/projects/${projectId}/export/mcp`, { method: "POST" });
      notify(`MCP export ready: ${res.tools_generated} tools`, "success");
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "MCP export failed", "error");
    } finally {
      setBusy(false);
    }
  }, [projectId, notify]);

  const EXPORT_OPTIONS: { type: ExportType; label: string }[] = [
    { type: "sdk", label: "SDK" },
    { type: "client", label: "Client" },
    { type: "fastapi", label: "FastAPI" },
    { type: "docker", label: "Docker" },
    { type: "github", label: "GitHub" },
    { type: "mcp", label: "MCP" },
    { type: "docs", label: "Docs" },
    { type: "cicd", label: "CI/CD" },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Export</h1>
        <p className="text-sm text-text-secondary">
          Package generated artifacts for deployment or distribution.
        </p>
      </div>

      <Card>
        <CardTitle>Export Types</CardTitle>
        <div className="mt-3 flex flex-wrap gap-2">
          {EXPORT_OPTIONS.map((opt) => (
            <button
              key={opt.type}
              onClick={() => toggle(opt.type)}
              className={`rounded-md border px-3 py-1.5 text-sm transition-colors ${
                selected.includes(opt.type)
                  ? "border-brand-primary bg-brand-primary/10 text-brand-primary"
                  : "border-border hover:bg-bg-tertiary"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {selected.includes("github") && (
          <div className="mt-4">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-text-secondary">GitHub repository (owner/repo)</span>
              <input
                value={githubRepo}
                onChange={(e) => setGithubRepo(e.target.value)}
                placeholder="myorg/stripe-integration"
                className="w-full rounded-md border border-border bg-bg-primary px-3 py-2 text-sm"
              />
            </label>
          </div>
        )}

        <div className="mt-4 flex gap-2">
          <Button onClick={submit} loading={busy}>
            Export Selected
          </Button>
          <Button variant="secondary" onClick={exportMCP} loading={busy}>
            Export MCP Only
          </Button>
        </div>
      </Card>

      <div className="space-y-2">
        <CardTitle>Recent Exports</CardTitle>
        {exports.length === 0 && (
          <Card className="text-sm text-text-secondary">No exports yet.</Card>
        )}
        {exports.map((ex) => (
          <Card key={ex.id} className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">{ex.export_type}</p>
              <p className="text-xs text-text-secondary">
                {new Date(ex.created_at).toLocaleString()}
              </p>
            </div>
            <StatusBadge status={ex.status} />
          </Card>
        ))}
      </div>
    </div>
  );
}
