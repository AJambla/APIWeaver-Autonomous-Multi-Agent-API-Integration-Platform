import React, { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../lib/auth-context';
import { apiFetch } from '../lib/api';
import { Project } from '../lib/types';
import { Plus, FolderKanban, ArrowUpRight, Clock, X, Search } from 'lucide-react';

interface Page<T> {
  data: T[];
}

const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'Unable to complete the request.';

export const DashboardPage: React.FC = () => {
  const { organizationId } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sortBy, setSortBy] = useState<'updated' | 'name'>('updated');
  const navigate = useNavigate();

  useEffect(() => {
    apiFetch<Page<Project>>('/projects')
      .then(({ data }) => setProjects(data))
      .catch(error => setError(errorMessage(error)))
      .finally(() => setLoading(false));
  }, []);

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
      setProjects(currentProjects => [created, ...currentProjects]);
      setIsModalOpen(false);
      setNewProjectName('');
      navigate(`/projects/${created.id}`);
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setCreating(false);
    }
  };

  const statuses = useMemo(
    () => Array.from(new Set(projects.map(p => (p.status || 'Active').toLowerCase()))),
    [projects],
  );

  const visibleProjects = useMemo(() => {
    const term = search.trim().toLowerCase();
    let list = projects;
    if (term) {
      list = list.filter(p =>
        p.name.toLowerCase().includes(term) || (p.description || '').toLowerCase().includes(term),
      );
    }
    if (statusFilter !== 'all') {
      list = list.filter(p => (p.status || 'Active').toLowerCase() === statusFilter);
    }
    return [...list].sort((a, b) =>
      sortBy === 'name'
        ? a.name.localeCompare(b.name)
        : new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    );
  }, [projects, search, statusFilter, sortBy]);

  return (
    <div className="px-6 lg:px-12 py-12">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-8">
        <div>
          <h1 className="text-3xl md:text-4xl font-normal tracking-tight mb-2">Projects & Workspaces</h1>
          <p className="text-neutral-400 text-sm">Manage your autonomous AI agent pipelines and specification specs.</p>
        </div>
        <button
          onClick={() => setIsModalOpen(true)}
          className="px-6 py-3 rounded-full bg-white text-black text-sm font-medium hover:bg-neutral-200 transition-all flex items-center gap-2 shadow-[0_0_25px_rgba(255,255,255,0.2)] self-start md:self-auto"
        >
          <Plus className="w-4 h-4" />
          <span>New Project</span>
        </button>
      </div>

      {/* Search / Filter / Sort toolbar */}
      <div className="flex flex-col sm:flex-row gap-3 mb-10">
        <div className="relative flex-1">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500" />
          <input
            type="search"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search projects..."
            className="w-full bg-neutral-900 border border-white/15 rounded-xl px-4 py-2.5 pl-11 text-sm text-white placeholder-neutral-600 focus:outline-none focus:border-white transition-colors"
          />
        </div>
        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          className="bg-neutral-900 border border-white/15 rounded-xl px-4 py-2.5 text-sm text-neutral-300 focus:outline-none focus:border-white transition-colors capitalize"
        >
          <option value="all">All statuses</option>
          {statuses.map(s => (
            <option key={s} value={s} className="capitalize">{s}</option>
          ))}
        </select>
        <select
          value={sortBy}
          onChange={e => setSortBy(e.target.value as 'updated' | 'name')}
          className="bg-neutral-900 border border-white/15 rounded-xl px-4 py-2.5 text-sm text-neutral-300 focus:outline-none focus:border-white transition-colors"
        >
          <option value="updated">Recently updated</option>
          <option value="name">Name (A-Z)</option>
        </select>
      </div>

        {error && (
          <div role="alert" className="mb-6 rounded-xl border border-red-500/30 bg-red-950/40 p-4 text-xs text-red-300">
            {error}
          </div>
        )}

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {[1, 2, 3].map(i => (
              <div key={i} className="glass-card p-6 rounded-2xl h-48 animate-pulse bg-white/5" />
            ))}
          </div>
        ) : projects.length === 0 ? (
          <div className="glass-card p-16 rounded-3xl text-center flex flex-col items-center justify-center border border-white/10">
            <FolderKanban className="w-12 h-12 text-neutral-500 mb-4" />
            <h3 className="text-lg font-medium mb-2">No projects found</h3>
            <p className="text-neutral-400 text-sm max-w-sm mb-6">Get started by creating your first autonomous API pipeline project.</p>
            <button
              onClick={() => setIsModalOpen(true)}
              className="px-6 py-3 rounded-full bg-white text-black text-sm font-medium hover:bg-neutral-200 transition-all flex items-center gap-2"
            >
              <Plus className="w-4 h-4" />
              <span>Create Project</span>
            </button>
          </div>
        ) : visibleProjects.length === 0 ? (
          <div className="glass-card p-12 rounded-3xl text-center border border-white/10">
            <h3 className="text-lg font-medium mb-2">No matching projects</h3>
            <p className="text-neutral-400 text-sm">Try a different search term or clear the filters.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {visibleProjects.map(proj => (
              <Link
                key={proj.id}
                to={`/projects/${proj.id}`}
                className="glass-card p-6 rounded-2xl border border-white/10 hover:border-white/30 transition-all flex flex-col justify-between group relative overflow-hidden"
              >
                <div className="absolute top-0 right-0 w-32 h-32 bg-white/5 rounded-full blur-2xl group-hover:bg-white/10 transition-colors pointer-events-none" />

                <div>
                  <div className="flex items-center justify-between mb-4">
                    <span className="px-3 py-1 rounded-full bg-white/10 text-xs font-medium text-neutral-200 capitalize">
                      {proj.status || 'Active'}
                    </span>
                    <ArrowUpRight className="w-4 h-4 text-neutral-500 group-hover:text-white group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-all" />
                  </div>

                  <h3 className="text-xl font-medium mb-2 tracking-tight">{proj.name}</h3>
                  <p className="text-neutral-400 text-xs line-clamp-2 leading-relaxed mb-6">
                    {proj.description || 'No description provided.'}
                  </p>
                </div>

                <div>
                  {proj.progress !== undefined && (
                    <div className="mb-4">
                      <div className="flex justify-between text-xs text-neutral-400 mb-1.5">
                        <span>Workflow Progress</span>
                        <span>{proj.progress}%</span>
                      </div>
                      <div className="w-full bg-neutral-900 h-1.5 rounded-full overflow-hidden">
                        <div className="bg-white h-full rounded-full transition-all duration-500" style={{ width: `${proj.progress}%` }} />
                      </div>
                    </div>
                  )}

                  <div className="flex items-center gap-2 text-xs text-neutral-500 pt-4 border-t border-white/10">
                    <Clock className="w-3.5 h-3.5" />
                    <span>Updated {new Date(proj.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}

      {/* New Project Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-6">
          <div className="max-w-md w-full glass-card p-8 rounded-3xl border border-white/20 appear-scale relative">
            <button
              onClick={() => setIsModalOpen(false)}
              className="absolute top-6 right-6 p-2 rounded-xl text-neutral-400 hover:text-white transition-colors"
            >
              <X className="w-4 h-4" />
            </button>

            <h2 className="text-2xl font-normal tracking-tight mb-2">Create New Project</h2>
            <p className="text-neutral-400 text-xs mb-6">Initialize a new agent pipeline workspace from specs or scratch.</p>

            <form onSubmit={handleCreateProject} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-neutral-300 mb-2">Project Name</label>
                <input
                  type="text"
                  required
                  value={newProjectName}
                  onChange={e => setNewProjectName(e.target.value)}
                  placeholder="e.g. Acme Billing Engine"
                  className="w-full bg-neutral-900 border border-white/15 rounded-xl px-4 py-3 text-sm text-white placeholder-neutral-600 focus:outline-none focus:border-white transition-colors"
                />
              </div>

              <div className="flex items-center gap-3 pt-4">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="flex-1 py-3 rounded-xl glass-pill text-sm font-medium hover:bg-white/10 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="flex-1 py-3 rounded-xl bg-white text-black text-sm font-medium hover:bg-neutral-200 transition-all shadow-[0_0_20px_rgba(255,255,255,0.2)] disabled:opacity-50"
                >
                  {creating ? 'Creating...' : 'Initialize'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
