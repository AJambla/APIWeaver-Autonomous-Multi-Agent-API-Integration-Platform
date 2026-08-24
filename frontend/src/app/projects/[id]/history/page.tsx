"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { ApiError, type HistoryItem, type VersionItem } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/Button";
import { Card, CardTitle } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs } from "@/components/Tabs";
import { Modal } from "@/components/Modal";
import { HistoryTimeline } from "@/components/HistoryTimeline";
import { RunComparisonView } from "@/components/RunComparisonView";

export default function HistoryPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const { notify } = useToast();

  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [versions, setVersions] = useState<VersionItem[]>([]);
  const [tab, setTab] = useState("history");
  const [loading, setLoading] = useState(true);

  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [compareOpen, setCompareOpen] = useState(false);
  const [rollbackTarget, setRollbackTarget] = useState<VersionItem | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [h, v] = await Promise.all([
        apiFetch<{ data: HistoryItem[] }>(`/projects/${projectId}/history?limit=50`).catch(
          () => ({ data: [] }),
        ),
        apiFetch<{ data: VersionItem[] }>(`/projects/${projectId}/versions?limit=50`).catch(
          () => ({ data: [] }),
        ),
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

  const rollback = useCallback(
    async (versionId: string) => {
      try {
        await apiFetch(`/projects/${projectId}/versions/${versionId}/rollback`, {
          method: "POST",
          body: { confirm: true },
        });
        notify("Rolled back successfully", "success");
        setRollbackTarget(null);
        await load();
      } catch (err) {
        notify(err instanceof ApiError ? err.message : "Rollback failed", "error");
      }
    },
    [projectId, notify, load],
  );

  const toggleCompare = (id: string) => {
    setCompareIds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= 2) return [prev[1], id];
      return [...prev, id];
    });
  };

  const compareVersions = compareIds
    .map((id) => versions.find((v) => v.id === id))
    .filter((v): v is VersionItem => Boolean(v));

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
        <Card>
          {history.length === 0 ? (
            <p className="text-sm text-text-secondary">No workflow runs yet.</p>
          ) : (
            <HistoryTimeline items={history} />
          )}
        </Card>
      )}

      {tab === "versions" && !loading && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs text-text-secondary">
              Select up to two versions to compare.
            </p>
            <Button
              variant="secondary"
              size="sm"
              disabled={compareVersions.length !== 2}
              onClick={() => setCompareOpen(true)}
            >
              Compare ({compareVersions.length}/2)
            </Button>
          </div>

          {versions.length === 0 && (
            <Card className="text-sm text-text-secondary">No versions yet.</Card>
          )}
          {versions.map((v) => (
            <Card key={v.id} className="flex items-center justify-between">
              <label className="flex flex-1 items-center gap-3">
                <input
                  type="checkbox"
                  checked={compareIds.includes(v.id)}
                  onChange={() => toggleCompare(v.id)}
                  className="h-4 w-4 accent-[var(--color-brand-primary)]"
                />
                <div>
                  <p className="text-sm font-medium">
                    {v.artifact_type} v{v.version_number}
                  </p>
                  <p className="text-xs text-text-secondary">
                    {new Date(v.created_at).toLocaleString()}
                  </p>
                </div>
              </label>
              <div className="flex items-center gap-2">
                {v.is_active && <span className="text-xs text-success">Active</span>}
                {!v.is_active && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setRollbackTarget(v)}
                  >
                    Rollback
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal
        open={compareOpen}
        onClose={() => setCompareOpen(false)}
        title="Compare Versions"
      >
        {compareVersions.length === 2 ? (
          <RunComparisonView base={compareVersions[0]} compare={compareVersions[1]} />
        ) : (
          <p className="text-sm text-text-secondary">Select two versions to compare.</p>
        )}
      </Modal>

      <Modal
        open={rollbackTarget !== null}
        onClose={() => setRollbackTarget(null)}
        title="Confirm Rollback"
      >
        {rollbackTarget && (
          <>
            <p className="text-sm text-text-secondary">
              Roll back to{" "}
              <span className="font-mono">
                {rollbackTarget.artifact_type} v{rollbackTarget.version_number}
              </span>
              ? This sets it as the active version and deactivates others of the same type.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setRollbackTarget(null)}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                onClick={() => rollback(rollbackTarget.id)}
              >
                Rollback
              </Button>
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}
