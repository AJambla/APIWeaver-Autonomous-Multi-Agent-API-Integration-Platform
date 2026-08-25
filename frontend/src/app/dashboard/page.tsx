"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, type Page, type Project } from "@/lib/api";
import { ApiError } from "@/lib/types";
import { useAuth } from "@/lib/auth-context";
import { useToast } from "@/components/Toast";
import { AppShell } from "@/components/AppShell";
import { Button } from "@/components/Button";
import { Card, CardTitle } from "@/components/Card";
import { Table, type Column } from "@/components/Table";
import { Modal } from "@/components/Modal";
import { StatusBadge } from "@/components/StatusBadge";

export default function DashboardPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const { notify } = useToast();

  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const page = await apiFetch<Page<Project>>("/projects?limit=50");
      setProjects(page.data);
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Failed to load projects", "error");
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    if (!authLoading) load();
  }, [authLoading, load]);

  const columns: Array<Column<Project>> = [
    { key: "name", header: "Name", render: (p) => <span className="font-medium">{p.name}</span> },
    { key: "status", header: "Status", render: (p) => <StatusBadge status={p.status} /> },
    {
      key: "endpoint_count",
      header: "Endpoints",
      render: (p) => p.endpoint_count ?? 0,
    },
    {
      key: "created_at",
      header: "Created",
      render: (p) => new Date(p.created_at).toLocaleDateString(),
    },
  ];

  return (
    <AppShell>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Projects</h1>
          <p className="text-sm text-text-secondary">
            {user?.organization_name ? `Organization: ${user.organization_name}` : "Your API integrations"}
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>+ New Project</Button>
      </div>

      {loading ? (
        <Card>Loading projects…</Card>
      ) : projects.length === 0 ? (
        <Card className="text-center">
          <p className="mb-3 text-text-secondary">You have no projects yet.</p>
          <Button onClick={() => setCreateOpen(true)}>Create your first project</Button>
        </Card>
      ) : (
        <Table
          columns={columns}
          rows={projects}
          rowHref={(p) => `/projects/${p.id}`}
          emptyMessage="No projects yet."
        />
      )}

      <CreateProjectModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(id) => router.push(`/projects/${id}`)}
      />
    </AppShell>
  );
}

function CreateProjectModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const { user } = useAuth();
  const { notify } = useToast();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!user?.organization_id) {
      notify("No organization selected or user session missing", "error");
      return;
    }
    setBusy(true);
    try {
      const project = await apiFetch<Project>("/projects", {
        method: "POST",
        body: {
          name,
          organization_id: user.organization_id,
        },
      });
      notify("Project created", "success");
      onCreated(project.id);
    } catch (err) {
      notify(
        err instanceof ApiError ? err.message : "Failed to create project",
        "error",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="New Project">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-text-secondary">Project name</span>
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border border-border bg-bg-primary px-3 py-2 text-sm"
            placeholder="Stripe Payments Integration"
          />
        </label>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={busy}>
            Create
          </Button>
        </div>
      </form>
    </Modal>
  );
}
