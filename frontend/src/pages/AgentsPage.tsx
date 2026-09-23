import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../lib/auth-context';
import { apiFetch } from '../lib/api';
import { Page, Project, ProjectSummary } from '../lib/types';
import { relativeTime } from '../lib/format';
import { cardCls, ErrorBanner, PageHeader, Skeleton, StatusBadge } from '../components/ui';
import { FileUp, Network, Code2, FlaskConical, PackageOpen, ChevronDown } from 'lucide-react';

/* The pipeline mirrors the real agent_worker task modules:
   document_tasks → planner_tasks → codegen_tasks → testing_tasks → export_tasks */
const PIPELINE = [
  {
    name: 'Document Ingestion',
    icon: FileUp,
    description: 'Parses uploaded OpenAPI/Swagger documents and raw documentation into a normalized operation model.',
  },
  {
    name: 'Planning Agent',
    icon: Network,
    description: 'Builds the topological DAG of operations with dependency ordering and rollback points.',
  },
  {
    name: 'Code Generation',
    icon: Code2,
    description: 'Generates client code for each DAG node across the selected target languages.',
  },
  {
    name: 'Testing Agent',
    icon: FlaskConical,
    description: 'Executes the generated test suite; failures trigger bounded self-healing repair loops.',
  },
  {
    name: 'Export Agent',
    icon: PackageOpen,
    description: 'Compiles validated output into SDKs, Docker services, GitHub repos, or MCP servers.',
  },
];

const errorMessage = (error: unknown) => (error instanceof Error ? error.message : 'Unable to load project activity.');

export const AgentsPage: React.FC = () => {
  const { organizationId } = useAuth();
  const [summaries, setSummaries] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!organizationId) return;
    let cancelled = false;
    apiFetch<Page<Project>>(`/projects?limit=25&organization_id=${organizationId}`)
      .then(async ({ data }) => {
        const results = await Promise.allSettled(data.map(p => apiFetch<ProjectSummary>(`/projects/${p.id}`)));
        if (!cancelled)
          setSummaries(results.filter(r => r.status === 'fulfilled').map(r => r.value));
      })
      .catch(err => !cancelled && setError(errorMessage(err)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [organizationId]);

  const running = useMemo(() => summaries.filter(p => ['planning', 'building', 'testing'].includes(p.status)), [summaries]);

  return (
    <div className="px-6 py-10 lg:px-10">
      <PageHeader
        title="AI Agents"
        subtitle="Agents run autonomously inside workflow pipelines. This is the live execution chain every run follows."
      />

      {error && <ErrorBanner message={error} onDismiss={() => setError('')} />}

      {/* Pipeline */}
      <div className="mb-12 flex flex-col gap-2 lg:flex-row lg:items-stretch lg:gap-0">
        {PIPELINE.map((stage, i) => {
          const Icon = stage.icon;
          return (
            <React.Fragment key={stage.name}>
              <div className={`${cardCls} flex-1 p-5 hover:bg-white/[0.05]`}>
                <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg bg-violet-500/10 text-violet-400">
                  <Icon className="h-4.5 w-4.5" />
                </div>
                <div className="mb-1 text-[11px] font-medium uppercase tracking-wider text-neutral-600">
                  Stage {i + 1}
                </div>
                <h3 className="mb-2 text-sm font-medium">{stage.name}</h3>
                <p className="text-xs leading-relaxed text-neutral-400">{stage.description}</p>
              </div>
              {i < PIPELINE.length - 1 && (
                <div className="flex items-center justify-center px-1 text-neutral-700">
                  <ChevronDown className="h-4 w-4 rotate-0 lg:rotate-[-90deg]" />
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Live project activity */}
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-medium uppercase tracking-wider text-neutral-400">Agent Activity by Project</h2>
        <Link to="/dashboard/runs" className="text-xs text-neutral-400 hover:text-white transition-colors">
          View all runs →
        </Link>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[1, 2, 3].map(i => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
      ) : summaries.length === 0 ? (
        <div className={`${cardCls} p-8 text-center text-sm text-neutral-500`}>
          No projects yet. Agents activate as soon as a pipeline is triggered from a project workspace.
        </div>
      ) : (
        <>
          {running.length > 0 && (
            <div className="mb-4 rounded-xl border border-blue-500/20 bg-blue-500/5 px-4 py-3 text-xs text-blue-300">
              {running.length} project{running.length > 1 ? 's have' : ' has'} an agent pipeline in progress right now.
            </div>
          )}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {summaries.map(project => (
              <Link key={project.id} to={`/projects/${project.id}`} className={`${cardCls} block p-5 hover:bg-white/[0.05]`}>
                <div className="mb-3 flex items-center justify-between gap-2">
                  <h3 className="truncate text-sm font-medium">{project.name}</h3>
                  <StatusBadge status={project.status} />
                </div>
                <div className="space-y-1.5 text-xs text-neutral-500">
                  <div className="flex justify-between">
                    <span>Last run</span>
                    {project.last_run_status ? <StatusBadge status={project.last_run_status} /> : <span>—</span>}
                  </div>
                  <div className="flex justify-between">
                    <span>Endpoints wired</span>
                    <span className="text-neutral-300">{project.endpoint_count}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Updated</span>
                    <span className="text-neutral-300">{relativeTime(project.updated_at)}</span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  );
};
