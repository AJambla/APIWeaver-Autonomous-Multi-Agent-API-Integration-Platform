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

type HistoryItem = {
  id: string;
  workflow_run_id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  total_tokens: number | null;
};

type VersionItem = {
  id: string;
  artifact_type: string;
  version_number: number;
  created_at: string;
  diff_ref: string | null;
  is_active: boolean;
};

export default function HistoryPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const { notify } = useToast();
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [versions, setVersions] = useState<VersionItem[]>([]);
  const [tab, setTab] = useState("history");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [h, v] = await Promise.all([
        apiFetch<{ data: HistoryItem[] }>(`/projects/${projectId}/history?limit=50`),
        apiFetch<{ data: VersionItem[] }>(`/projects/${projectId}/versions?limit=50`),
      ]);
      setHistory(h.data ?? []);
      setVersions(v.data ?? []);
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Failed to load history", "error");
    } finally {
      setLoading(false);
    }
  }, [projectId, notify]);

  useEffect(() => {
    load();
  }, [load]);

  const rollback = useCallback(async (versionId: string) => {
    try {
      await apiFetch(`/projects/${projectId}/versions/${versionId}/rollback`, {
        method: "POST",
        body: { confirm: true },
      });
      notify("Rolled back successfully", "success");
      await load();
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Rollback failed", "error");
    }
  }, [projectId, notify, load]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">History</h1>
        <p className="text-sm text-text-secondary">
          Workflow run timeline and artifact versioning.
        </p>
      </div>

      <Tabs
        tabs={[
          { id: "history", label: "Workflow History" },
          { id: "versions", label: "Versions" },
        ]}
        active={tab}
        onChange={setTab}
      />

      {loading && <Card>Loading…</Card>}

      {tab === "history" && !loading && (
        <div className="space-y-3">
          {history.length === 0 && (
            <Card className="text-sm text-text-secondary">No workflow runs yet.</Card>
          )}
          {history.map((item) => (
            <Card key={item.id} className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">
                  <StatusBadge status={item.status} />
                </p>
                <p className="text-xs text-text-secondary">
                  Started: {new Date(item.started_at).toLocaleString()}
                </p>
              </div>
              <div className="text-xs text-text-secondary">
                {item.total_tokens ?? 0} tokens
              </div>
            </Card>
          ))}
        </div>
      )}

      {tab === "versions" && !loading && (
        <div className="space-y-3">
          {versions.length === 0 && (
            <Card className="text-sm text-text-secondary">No versions yet.</Card>
          )}
          {versions.map((v) => (
            <Card key={v.id} className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">
                  {v.artifact_type} v{v.version_number}
                </p>
                <p className="text-xs text-text-secondary">
                  {new Date(v.created_at).toLocaleString()}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {v.is_active && (
                  <span className="text-xs text-success">Active</span>
                )}
                {!v.is_active && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => rollback(v.id)}
                  >
                    Rollback
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
