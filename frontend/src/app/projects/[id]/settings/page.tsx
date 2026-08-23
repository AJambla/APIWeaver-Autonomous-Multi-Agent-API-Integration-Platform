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
import { Modal } from "@/components/Modal";

type Project = {
  id: string;
  name: string;
  status: string;
  organization_id: string;
  created_at: string;
};

type AuthConfig = {
  scheme: string;
  config_json: Record<string, any>;
  verified: boolean;
};

type Member = {
  user_id: string;
  email: string;
  full_name: string;
  role: string;
};

export default function SettingsPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const { notify } = useToast();
  const [tab, setTab] = useState("general");
  const [project, setProject] = useState<Project | null>(null);
  const [auth, setAuth] = useState<AuthConfig | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, a] = await Promise.all([
        apiFetch<Project>(`/projects/${projectId}`),
        apiFetch<AuthConfig>(`/projects/${projectId}/auth`).catch(() => null),
      ]);
      setProject(p);
      setAuth(a);
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Failed to load settings", "error");
    } finally {
      setLoading(false);
    }
  }, [projectId, notify]);

  useEffect(() => {
    load();
  }, [load]);

  const saveName = useCallback(async () => {
    if (!project) return;
    setSaving(true);
    try {
      const updated = await apiFetch<Project>(`/projects/${projectId}`, {
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
