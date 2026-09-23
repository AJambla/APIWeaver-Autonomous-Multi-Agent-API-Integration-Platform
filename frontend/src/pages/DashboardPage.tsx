import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../lib/auth-context';
import { apiFetch } from '../lib/api';
import { PROJECT_STATUSES, Page, Project, ProjectSummary } from '../lib/types';
import { relativeTime } from '../lib/format';
import {
  btnGhost,
  btnPrimary,
  cardCls,
  EmptyState,
  ErrorBanner,
  FilterSelect,
  inputCls,
  Modal,
  OptionsMenu,
  PageHeader,
  SearchInput,
  Skeleton,
  StatusBadge,
} from '../components/ui';
import { Plus, FolderKanban, ArrowUpRight, Archive, Clock, FileCode2, MoreHorizontal } from 'lucide-react';

const errorMessage = (error: unknown) => (error instanceof Error ? error.message : 'Unable to complete the request.');

export const DashboardPage: React.FC = () => {
  const { organizationId } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [summaries, setSummaries] = useState<Record<string, ProjectSummary>>({});
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const [searchParams, setSearchParams] = useSearchParams();
  const [newProjectName, setNewProjectName] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sortBy, setSortBy] = useState<'updated' | 'name'>('updated');
  const [archivingId, setArchivingId] = useState<string | null>(null);
  const [pendingArchive, setPendingArchive] = useState<Project | null>(null);
  const navigate = useNavigate();

  const isModalOpen = searchParams.get('new') === '1';
  const openModal = () => setSearchParams({ new: '1' });
  const closeModal = () => setSearchParams({});

  const loadProjects = useCallback(() => {
    if (!organizationId) return;
    setLoading(true);
    apiFetch<Page<Project>>(`/projects?limit=100&organization_id=${organizationId}`)
      .then(({ data }) => {
        setProjects(data);
        // Enrich cards with real per-project summary counts.
        Promise.allSettled(data.slice(0, 30).map(p => apiFetch<ProjectSummary>(`/projects/${p.id}`))).then(results => {
          setSummaries(
            Object.fromEntries(
              results
                .filter((r): r is PromiseFulfilledResult<ProjectSummary> => r.status === 'fulfilled')
                .map(r => [r.value.id, r.value]),
            ),
          );
        });
      })
      .catch(err => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  }, [organizationId]);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProjectName.trim() || !organizationId) {
      setError('An organization is required to create a project.');
      return;
    }
    setCreating(true);
    setError('');
    try {
      const created = await apiFetch<Project>('/projects', {
        method: 'POST',
        body: JSON.stringify({ name: newProjectName.trim(), organization_id: organizationId }),
      });
      setProjects(current => [created, ...current]);
      closeModal();
      setNewProjectName('');
      navigate(`/projects/${created.id}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  };

  const handleArchive = async (project: Project) => {
    setArchivingId(project.id);
    setError('');
    try {
      const archived = await apiFetch<Project>(`/projects/${project.id}`, { method: 'DELETE' });
      setProjects(current => current.map(p => (p.id === archived.id ? archived : p)));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setArchivingId(null);
    }
  };

  const visibleProjects = useMemo(() => {
    const term = search.trim().toLowerCase();
    let list = projects;
    if (term) list = list.filter(p => p.name.toLowerCase().includes(term));
    if (statusFilter !== 'all') list = list.filter(p => p.status === statusFilter);
    return [...list].sort((a, b) =>
      sortBy === 'name'
        ? a.name.localeCompare(b.name)
        : new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    );
  }, [projects, search, statusFilter, sortBy]);

  return (
    <div className="px-6 py-10 lg:px-10">
      <PageHeader
        title="Projects & Workspaces"
        subtitle="Manage your autonomous AI agent pipelines and API specification projects."
        actions={
          <button onClick={openModal} className={btnPrimary}>
            <Plus className="h-4 w-4" /> New Project
          </button>
        }
      />

      <div className="mb-8 flex flex-col gap-3 sm:flex-row">
        <SearchInput value={search} onChange={setSearch} placeholder="Search projects..." className="flex-1 sm:max-w-sm" />
        <FilterSelect
          value={statusFilter}
          onChange={setStatusFilter}
          options={[
            { value: 'all', label: 'All statuses' },
            ...PROJECT_STATUSES.map(s => ({ value: s, label: s })),
          ]}
        />
        <FilterSelect
          value={sortBy}
          onChange={v => setSortBy(v as 'updated' | 'name')}
          options={[
            { value: 'updated', label: 'Recently updated' },
            { value: 'name', label: 'Name (A-Z)' },
          ]}
        />
      </div>

      {error && <ErrorBanner message={error} onDismiss={() => setError('')} />}

      {loading ? (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
          {[1, 2, 3, 4, 5, 6].map(i => (
            <Skeleton key={i} className="h-44" />
          ))}
        </div>
      ) : projects.length === 0 ? (
        <EmptyState
          icon={<FolderKanban className="h-6 w-6" />}
          title="No projects found"
          description="Create your first autonomous API pipeline project to get started."
          action={
            <button onClick={openModal} className={btnPrimary}>
              <Plus className="h-4 w-4" /> Create Project
            </button>
          }
        />
      ) : visibleProjects.length === 0 ? (
        <EmptyState
          icon={<MoreHorizontal className="h-6 w-6" />}
          title="No matching projects"
          description="Try a different search term or clear the filters."
          action={
            <button
              onClick={() => {
                setSearch('');
                setStatusFilter('all');
              }}
              className={btnGhost}
            >
              Clear filters
            </button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
          {visibleProjects.map(project => {
            const summary = summaries[project.id];
            return (
              <div
                key={project.id}
                className={`${cardCls} group flex flex-col p-5 hover:bg-white/[0.05] ${project.status === 'archived' ? 'opacity-60' : ''}`}
              >
                <div className="mb-3 flex items-start justify-between gap-2">
                  <StatusBadge status={project.status} />
                  <OptionsMenu
                    items={[
                      { label: 'Open Workspace', onSelect: () => navigate(`/projects/${project.id}`) },
                      {
                        label: project.status === 'archived' ? 'Archived' : 'Archive Project',
                        onSelect: () => project.status !== 'archived' && setPendingArchive(project),
                        danger: true,
                      },
                    ]}
                  />
                </div>

                <Link to={`/projects/${project.id}`} className="min-w-0 flex-1">
                  <h3 className="mb-3 truncate text-base font-medium tracking-tight group-hover:text-white">
                    {project.name}
                  </h3>
                  <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-neutral-500">
                    <span className="inline-flex items-center gap-1.5">
                      <FileCode2 className="h-3.5 w-3.5" />
                      {summary ? `${summary.endpoint_count} endpoints` : '— endpoints'}
                    </span>
                    {summary?.last_run_status && <StatusBadge status={summary.last_run_status} label={`last run: ${summary.last_run_status}`} />}
                  </div>
                </Link>

                <div className="flex items-center justify-between border-t border-white/5 pt-3">
                  <span className="inline-flex items-center gap-1.5 text-xs text-neutral-500">
                    <Clock className="h-3.5 w-3.5" />
                    {relativeTime(project.updated_at)}
                  </span>
                  <Link
                    to={`/projects/${project.id}`}
                    className="inline-flex items-center gap-1 text-xs font-medium text-neutral-300 hover:text-white transition-colors"
                  >
                    Open Workspace <ArrowUpRight className="h-3.5 w-3.5" />
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {isModalOpen && (
        <Modal
          title="Create New Project"
          description="Initialize a new agent pipeline workspace. You can upload an OpenAPI spec in the next step."
          onClose={closeModal}
        >
          <form onSubmit={handleCreateProject} className="space-y-4">
            <div>
              <label className="mb-2 block text-xs font-medium text-neutral-300">Project Name</label>
              <input
                type="text"
                required
                autoFocus
                value={newProjectName}
                onChange={e => setNewProjectName(e.target.value)}
                placeholder="e.g. Acme Billing Engine"
                className={inputCls}
              />
            </div>
            <div className="flex items-center gap-3 pt-2">
              <button type="button" onClick={closeModal} className={`${btnGhost} flex-1`}>
                Cancel
              </button>
              <button type="submit" disabled={creating} className={`${btnPrimary} flex-1`}>
                {creating ? 'Creating...' : 'Create Project'}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {pendingArchive && (
        <Modal
          title="Archive project"
          description={`"${pendingArchive.name}" will be archived. Its specs and run history are preserved.`}
          onClose={() => setPendingArchive(null)}
        >
          <div className="flex items-center gap-3 pt-2">
            <button type="button" onClick={() => setPendingArchive(null)} className={`${btnGhost} flex-1`}>
              Cancel
            </button>
            <button
              type="button"
              onClick={() => {
                handleArchive(pendingArchive);
                setPendingArchive(null);
              }}
              className="flex-1 inline-flex items-center justify-center gap-2 rounded-full bg-red-500/90 text-white text-sm font-medium px-5 h-10 hover:bg-red-500 transition-colors"
            >
              Archive
            </button>
          </div>
        </Modal>
      )}

      {archivingId && (
        <div className="pointer-events-none fixed bottom-6 right-6 rounded-xl border border-white/10 bg-neutral-900 px-4 py-2.5 text-xs text-neutral-300 shadow-xl">
          <span className="inline-flex items-center gap-2">
            <Archive className="h-3.5 w-3.5" /> Archiving project...
          </span>
        </div>
      )}
    </div>
  );
};
