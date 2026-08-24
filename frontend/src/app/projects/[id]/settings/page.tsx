"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { ApiError, type OrgMetrics, type RetryPolicy } from "@/lib/types";
import { useAuth } from "@/lib/auth-context";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/Button";
import { Card, CardTitle } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs } from "@/components/Tabs";
import { Modal } from "@/components/Modal";

const DEFAULT_RETRY: RetryPolicy = {
  max_attempts: 3,
  backoff_base_seconds: 2,
  retryable_status_codes: [429, 500, 502, 503, 504],
};

export default function SettingsPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const { user } = useAuth();
  const { notify } = useToast();

  const [tab, setTab] = useState("general");
  const [project, setProject] = useState<{
    id: string;
    name: string;
    status: string;
    organization_id: string;
    created_at: string;
  } | null>(null);
  const [auth, setAuth] = useState<{
    scheme: string;
    config_json: Record<string, any>;
    verified: boolean;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const [retry, setRetry] = useState<RetryPolicy>(DEFAULT_RETRY);
  const [retrySavedLocal, setRetrySavedLocal] = useState(false);
  const [orgMetrics, setOrgMetrics] = useState<OrgMetrics | null>(null);
  const [orgFailed, setOrgFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, a] = await Promise.all([
        apiFetch<{ id: string; name: string; status: string; organization_id: string; created_at: string }>(
          `/projects/${projectId}`,
        ),
        apiFetch<{ scheme: string; config_json: Record<string, any>; verified: boolean }>(
          `/projects/${projectId}/auth`,
        ).catch(() => null),
      ]);
      setProject(p);
      setAuth(a);

      // Load retry policy from the backend (Task 7.3).
      try {
        const rp = await apiFetch<RetryPolicy>(
          `/projects/${projectId}/settings/retry-policy`,
        );
        setRetry(rp);
        setRetrySavedLocal(false);
      } catch {
        /* fall back to defaults */
      }

      if (user?.organization_id) {
        try {
          const om = await apiFetch<OrgMetrics>(
            `/org/${user.organization_id}/metrics?days=30`,
          );
          setOrgMetrics(om);
          setOrgFailed(false);
        } catch (err) {
          if (err instanceof ApiError && err.status === 403) setOrgFailed(true);
        }
      }
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Failed to load settings", "error");
    } finally {
      setLoading(false);
    }
  }, [projectId, user?.organization_id, notify]);

  useEffect(() => {
    load();
  }, [load]);

  const saveName = useCallback(async () => {
    if (!project) return;
    setSaving(true);
    try {
      const updated = await apiFetch<typeof project>(`/projects/${projectId}`, {
        method: "PATCH",
        body: { name: project.name },
      });
      setProject(updated);
      notify("Project updated", "success");
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Failed to update", "error");
    } finally {
      setSaving(false);
    }
  }, [project, projectId, notify]);

  const saveRetry = useCallback(async () => {
    setSaving(true);
    try {
      await apiFetch(`/projects/${projectId}/settings/retry-policy`, {
        method: "PUT",
        body: retry,
      });
      setRetrySavedLocal(false);
      notify("Retry policy saved", "success");
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Failed to save retry policy", "error");
    } finally {
      setSaving(false);
    }
  }, [retry, projectId, notify]);

  const deleteProject = useCallback(async () => {
    setSaving(true);
    try {
      await apiFetch(`/projects/${projectId}`, { method: "DELETE" });
      notify("Project archived", "success");
      window.location.href = "/dashboard";
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Failed to archive", "error");
    } finally {
      setSaving(false);
      setDeleteOpen(false);
    }
  }, [projectId, notify]);

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Settings</h1>
        <Card>Loading…</Card>
      </div>
    );
  }

  if (!project) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Settings</h1>
        <Card className="text-text-secondary">Project not found.</Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-sm text-text-secondary">Manage project configuration and secrets.</p>
      </div>

      <Tabs
        tabs={[
          { id: "general", label: "General" },
          { id: "auth", label: "Auth & Secrets" },
          { id: "retry", label: "Retry Policy" },
          { id: "billing", label: "Billing" },
          { id: "team", label: "Team" },
          { id: "danger", label: "Danger Zone" },
        ]}
        active={tab}
        onChange={setTab}
      />

      {tab === "general" && (
        <Card className="space-y-4">
          <CardTitle>General</CardTitle>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-text-secondary">Project name</span>
            <input
              value={project.name}
              onChange={(e) => setProject({ ...project, name: e.target.value })}
              className="w-full rounded-md border border-border bg-bg-primary px-3 py-2 text-sm"
            />
          </label>
          <div className="flex justify-end">
            <Button onClick={saveName} loading={saving}>
              Save
            </Button>
          </div>
        </Card>
      )}

      {tab === "auth" && (
        <Card className="space-y-4">
          <CardTitle>Auth Configuration</CardTitle>
          {auth ? (
            <div className="space-y-2 text-sm">
              <p>
                <span className="font-medium">Scheme:</span> {auth.scheme}
              </p>
              <p>
                <span className="font-medium">Verified:</span>{" "}
                <StatusBadge status={auth.verified ? "completed" : "failed"} />
              </p>
              <pre className="rounded-md bg-bg-tertiary p-3 text-xs">
                {JSON.stringify(auth.config_json, null, 2)}
              </pre>
            </div>
          ) : (
            <p className="text-sm text-text-secondary">No auth configuration yet.</p>
          )}
        </Card>
      )}

      {tab === "retry" && (
        <Card className="space-y-4">
          <CardTitle>Retry Policy</CardTitle>
          <p className="text-xs text-text-secondary">
            Controls how the testing agent retries failed requests during self-healing.
          </p>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-text-secondary">Max attempts</span>
            <input
              type="number"
              min={1}
              max={10}
              value={retry.max_attempts}
              onChange={(e) =>
                setRetry({ ...retry, max_attempts: Number(e.target.value) || 1 })
              }
              className="w-full rounded-md border border-border bg-bg-primary px-3 py-2 text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-text-secondary">Backoff base (seconds)</span>
            <input
              type="number"
              min={0}
              step={0.5}
              value={retry.backoff_base_seconds}
              onChange={(e) =>
                setRetry({ ...retry, backoff_base_seconds: Number(e.target.value) || 0 })
              }
              className="w-full rounded-md border border-border bg-bg-primary px-3 py-2 text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-text-secondary">Retryable status codes (comma-separated)</span>
            <input
              value={retry.retryable_status_codes.join(", ")}
              onChange={(e) =>
                setRetry({
                  ...retry,
                  retryable_status_codes: e.target.value
                    .split(",")
                    .map((s) => parseInt(s.trim(), 10))
                    .filter((n) => !isNaN(n)),
                })
              }
              className="w-full rounded-md border border-border bg-bg-primary px-3 py-2 text-sm font-mono"
            />
          </label>
          {retrySavedLocal && (
            <p className="text-xs text-warning">
              Stored locally — server-side persistence is pending backend support.
            </p>
          )}
          <div className="flex justify-end">
            <Button onClick={saveRetry} loading={saving}>
              Save Retry Policy
            </Button>
          </div>
        </Card>
      )}

      {tab === "billing" && (
        <div className="space-y-4">
          {orgFailed && (
            <Card className="text-sm text-text-secondary">
              You don&apos;t have permission to view organization billing. Contact an admin.
            </Card>
          )}
          {!orgFailed && orgMetrics && (
            <>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <Card>
                  <CardTitle>Workflow Rate Limit</CardTitle>
                  <p className="text-2xl font-bold text-text-primary">
                    {orgMetrics.tier_limit_workflow_triggers_hour}/hr
                  </p>
                </Card>
                <Card>
                  <CardTitle>Token Spend (30d)</CardTitle>
                  <p className="text-2xl font-bold text-text-primary">
                    ${orgMetrics.monthly_token_spend_usd.toFixed(2)}
                  </p>
                </Card>
                <Card>
                  <CardTitle>Projects</CardTitle>
                  <p className="text-2xl font-bold text-text-primary">
                    {orgMetrics.projects_count}
                  </p>
                </Card>
              </div>
              <Card>
                <CardTitle>Usage Limits</CardTitle>
                <ul className="mt-2 space-y-1 text-sm text-text-secondary">
                  <li>
                    Workflow triggers / hour:{" "}
                    <span className="text-text-primary">
                      {orgMetrics.tier_limit_workflow_triggers_hour}
                    </span>
                  </li>
                  <li>
                    Total workflow runs (30d):{" "}
                    <span className="text-text-primary">
                      {orgMetrics.total_workflow_runs}
                    </span>
                  </li>
                  <li>
                    Avg test pass rate:{" "}
                    <span className="text-text-primary">
                      {orgMetrics.avg_test_pass_rate != null
                        ? `${(orgMetrics.avg_test_pass_rate * 100).toFixed(1)}%`
                        : "—"}
                    </span>
                  </li>
                </ul>
              </Card>
            </>
          )}
        </div>
      )}

      {tab === "team" && (
        <Card>
          <CardTitle>Team Members</CardTitle>
          <p className="mt-2 text-sm text-text-secondary">
            Team management is available on the Organization settings page.
          </p>
        </Card>
      )}

      {tab === "danger" && (
        <Card className="space-y-4">
          <CardTitle>Danger Zone</CardTitle>
          <p className="text-sm text-text-secondary">
            Archiving a project removes it from your dashboard but preserves all data.
          </p>
          <Button variant="destructive" onClick={() => setDeleteOpen(true)}>
            Archive Project
          </Button>
          <Modal open={deleteOpen} onClose={() => setDeleteOpen(false)} title="Archive Project">
            <p className="text-sm text-text-secondary">
              Are you sure you want to archive this project? This action can be undone later.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setDeleteOpen(false)}>
                Cancel
              </Button>
              <Button variant="destructive" onClick={deleteProject} loading={saving}>
                Archive
              </Button>
            </div>
          </Modal>
        </Card>
      )}
    </div>
  );
}
