import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../lib/auth-context';
import { apiFetch } from '../lib/api';
import { Project } from '../lib/types';
import { Plus, FolderKanban, LogOut, ArrowUpRight, Clock, X } from 'lucide-react';

interface Page<T> {
  data: T[];
}

const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'Unable to complete the request.';

export const DashboardPage: React.FC = () => {
  const { user, organizationId, logout } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
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

  return (
    <div className="min-h-screen bg-black text-white flex flex-col selection:bg-white selection:text-black">
      {/* Header */}
      <header className="border-b border-white/10 bg-black/60 backdrop-blur-xl sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-6 h-20 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-white text-black flex items-center justify-center font-bold tracking-tighter text-lg">
              AW
            </div>
            <span className="font-semibold tracking-tight text-lg">API Weaver Workspace</span>
          </div>

          <div className="flex items-center gap-6">
            <div className="text-right hidden sm:block">
              <div className="text-sm font-medium">{user?.full_name || user?.email || 'Operator'}</div>
              <div className="text-xs text-neutral-400">SOC2 Verified Tier</div>
            </div>
            <button
              onClick={logout}
              className="p-2.5 rounded-xl glass-pill hover:bg-white/10 text-neutral-300 hover:text-white transition-colors"
              title="Sign out"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-6 py-12 flex-1 w-full">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-12">
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
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {projects.map(proj => (
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
      </main>

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
