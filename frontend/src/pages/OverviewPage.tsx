import React, { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../lib/auth-context';
import { apiFetch } from '../lib/api';
import { HistoryItem, OrgMetrics, Page, Project, ProjectSummary } from '../lib/types';
import { formatNumber, formatPercent, formatUsd, relativeTime } from '../lib/format';
import {
  cardCls,
  btnPrimary,
  ErrorBanner,
  PageHeader,
  Skeleton,
  StatCard,
  StatusBadge,
  EmptyState,
} from '../components/ui';
import {
  FolderKanban,
  FileCode2,
  Activity,
  Target,
  Plus,
  Upload,
  Play,
  ListChecks,
  ArrowRight,
  ChevronRight,
} from 'lucide-react';

const errorMessage = (error: unknown) => (error instanceof Error ? error.message : 'Unable to load the dashboard.');

const SectionTitle: React.FC<{ children: React.ReactNode; action?: React.ReactNode }> = ({ children, action }) => (
  <div className="mb-4 flex items-center justify-between">
    <h2 className="text-sm font-medium uppercase tracking-wider text-neutral-400">{children}</h2>
    {action}
  </div>
);

export const OverviewPage: React.FC = () => {
  const { organizationId, organizations } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [summaries, setSummaries] = useState<Record<string, ProjectSummary>>({});
  const [metrics, setMetrics] = useState<OrgMetrics | null>(null);
  const [activity, setActivity] = useState<Array<HistoryItem & { projectName: string }>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const orgName = organizations.find(o => o.organization_id === organizationId)?.organization_name;

  useEffect(() => {
    if (!organizationId) return;
    let cancelled = false;
    setLoading(true);
    setError('');

    (async () => {
      try {
        const [projectPage, orgMetrics] = await Promise.all([
          apiFetch<Page<Project>>(`/projects?limit=25&organization_id=${organizationId}`),
          apiFetch<OrgMetrics>(`/org/${organizationId}/metrics`).catch(() => null),
        ]);
        if (cancelled) return;
        setProjects(projectPage.data);
        setMetrics(orgMetrics);

        const recent = projectPage.data.slice(0, 10);
        const summaryResults = await Promise.allSettled(
          recent.map(p => apiFetch<ProjectSummary>(`/projects/${p.id}`)),
        );
        if (cancelled) return;
        setSummaries(
          Object.fromEntries(
            summaryResults
              .filter((r): r is PromiseFulfilledResult<ProjectSummary> => r.status === 'fulfilled')
              .map(r => [r.value.id, r.value]),
          ),
        );

        const historyProjects = recent.slice(0, 3);
        const historyResults = await Promise.allSettled(
          historyProjects.map(p =>
            apiFetch<Page<HistoryItem>>(`/projects/${p.id}/history?limit=5`).then(page =>
              page.data.map(item => ({ ...item, projectName: p.name })),
            ),
          ),
        );
        if (cancelled) return;
        setActivity(
          historyResults
            .filter((r): r is PromiseFulfilledResult<Array<HistoryItem & { projectName: string }>> => r.status === 'fulfilled')
            .map(r => r.value)
            .flat()
            .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime())
            .slice(0, 6),
        );
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [organizationId]);

  const stats = useMemo(() => {
    const summaryList = Object.values(summaries);
    const specCount = summaryList.filter(s => s.endpoint_count > 0).length;
    const totalEndpoints = summaryList.reduce((sum, s) => sum + s.endpoint_count, 0);
    const archived = projects.filter(p => p.status === 'archived').length;
    return { specCount, totalEndpoints, archived };
  }, [summaries, projects]);

  const quickActions = [
    { label: 'New Project', description: 'Start an integration pipeline', icon: Plus, onClick: () => navigate('/dashboard?new=1') },
    { label: 'Upload API Spec', description: 'Import an OpenAPI document', icon: Upload, onClick: () => navigate('/dashboard') },
    { label: 'Run Agent', description: 'Trigger plan → build → test', icon: Play, onClick: () => navigate('/dashboard') },
    { label: 'View Recent Runs', description: 'Monitor executions', icon: ListChecks, onClick: () => navigate('/dashboard/runs') },
  ];

  return (
    <div className="px-6 py-10 lg:px-10">
      <PageHeader
        title="Overview"
        subtitle={orgName ? `Workspace health for ${orgName}.` : 'Workspace health at a glance.'}
        actions={
          <Link to="/dashboard?new=1" className={btnPrimary}>
            <Plus className="h-4 w-4" /> New Project
          </Link>
        }
      />

      {error && <ErrorBanner message={error} onDismiss={() => setError('')} />}

      {/* Stats row */}
      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {loading ? (
          [1, 2, 3, 4].map(i => <Skeleton key={i} className="h-[118px]" />)
        ) : (
          <>
            <StatCard
              icon={<FolderKanban className="h-4 w-4" />}
              label="Total Projects"
              value={String(metrics?.projects_count ?? projects.length)}
              sub={`${stats.archived} archived`}
            />
            <StatCard
              icon={<FileCode2 className="h-4 w-4" />}
              label="API Specifications"
              value={String(stats.specCount)}
              sub={`${formatNumber(stats.totalEndpoints)} endpoints discovered`}
            />
            <StatCard
              icon={<Activity className="h-4 w-4" />}
              label="Agent Runs"
              value={formatNumber(metrics?.total_workflow_runs ?? 0)}
              sub={`Limit ${formatNumber(metrics?.tier_limit_workflow_triggers_hour ?? 0)}/hr`}
            />
            <StatCard
              icon={<Target className="h-4 w-4" />}
              label="Success Rate"
              value={formatPercent(metrics?.avg_test_pass_rate)}
              sub={`${formatUsd(metrics?.monthly_token_spend_usd ?? 0)} token spend this month`}
            />
          </>
        )}
      </div>

      <div className="grid grid-cols-1 gap-8 xl:grid-cols-3">
        {/* Recent projects */}
        <div className="xl:col-span-2">
          <SectionTitle
            action={
              <Link to="/dashboard" className="flex items-center gap-1 text-xs text-neutral-400 hover:text-white transition-colors">
                View all <ChevronRight className="h-3.5 w-3.5" />
              </Link>
            }
          >
            Recent Projects
          </SectionTitle>
          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3].map(i => <Skeleton key={i} className="h-16" />)}
            </div>
          ) : projects.length === 0 ? (
            <EmptyState
              icon={<FolderKanban className="h-6 w-6" />}
              title="No projects yet"
              description="Create your first project to start building an autonomous API integration pipeline."
              action={
                <Link to="/dashboard?new=1" className={btnPrimary}>
                  <Plus className="h-4 w-4" /> New Project
                </Link>
              }
            />
          ) : (
            <div className="space-y-2">
              {projects.slice(0, 4).map(project => {
                const summary = summaries[project.id];
                return (
                  <Link
                    key={project.id}
                    to={`/projects/${project.id}`}
                    className={`${cardCls} group flex items-center gap-4 p-4 hover:bg-white/[0.05]`}
                  >
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/5 text-neutral-300">
                      <FolderKanban className="h-4 w-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{project.name}</div>
                      <div className="text-xs text-neutral-500">
                        {summary ? `${summary.endpoint_count} endpoints · ` : ''}
                        Updated {relativeTime(project.updated_at)}
                      </div>
                    </div>
                    {summary?.last_run_status && <StatusBadge status={summary.last_run_status} label={`last run: ${summary.last_run_status}`} />}
                    <StatusBadge status={project.status} />
                    <ArrowRight className="h-4 w-4 shrink-0 text-neutral-600 group-hover:translate-x-0.5 group-hover:text-white transition-all" />
                  </Link>
                );
              })}
            </div>
          )}

          {/* Recent activity */}
          <div className="mt-10">
            <SectionTitle
              action={
                <Link to="/dashboard/runs" className="flex items-center gap-1 text-xs text-neutral-400 hover:text-white transition-colors">
                  All runs <ChevronRight className="h-3.5 w-3.5" />
                </Link>
              }
            >
              Recent Activity
            </SectionTitle>
            {loading ? (
              <div className="space-y-2">
                {[1, 2].map(i => <Skeleton key={i} className="h-12" />)}
              </div>
            ) : activity.length === 0 ? (
              <div className={`${cardCls} p-6 text-sm text-neutral-500`}>
                No agent runs recorded yet. Trigger a pipeline from a project workspace to see activity here.
              </div>
            ) : (
              <div className={`${cardCls} divide-y divide-white/5`}>
                {activity.map(item => (
                  <div key={item.id} className="flex items-center gap-4 px-4 py-3">
                    <StatusBadge status={item.status} />
                    <span className="min-w-0 flex-1 truncate text-sm text-neutral-300">
                      <span className="font-medium text-white">{item.projectName}</span>
                      {' · '}
                      {item.stages.join(' → ')}
                    </span>
                    <span className="shrink-0 text-xs text-neutral-500">{relativeTime(item.started_at)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right column */}
        <div className="space-y-8">
          <div>
            <SectionTitle>Quick Actions</SectionTitle>
            <div className="space-y-2">
              {quickActions.map(action => {
                const Icon = action.icon;
                return (
                  <button
                    key={action.label}
                    onClick={action.onClick}
                    className={`${cardCls} group flex w-full items-center gap-3 p-4 text-left hover:bg-white/[0.05]`}
                  >
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/5 text-neutral-300 group-hover:bg-white group-hover:text-black transition-colors">
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-medium">{action.label}</div>
                      <div className="truncate text-xs text-neutral-500">{action.description}</div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <SectionTitle>Agent Performance</SectionTitle>
            <div className={`${cardCls} p-5`}>
              {loading ? (
                <Skeleton className="h-24" />
              ) : (
                <>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="text-neutral-400">Test pass rate</span>
                    <span className="font-medium">{formatPercent(metrics?.avg_test_pass_rate)}</span>
                  </div>
                  <div className="mb-5 h-1.5 overflow-hidden rounded-full bg-neutral-900">
                    <div
                      className="h-full rounded-full bg-emerald-500 transition-all duration-500"
                      style={{ width: `${Math.round((metrics?.avg_test_pass_rate ?? 0) * 100)}%` }}
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <div className="text-lg font-semibold">{formatNumber(metrics?.total_workflow_runs ?? 0)}</div>
                      <div className="text-xs text-neutral-500">Total runs</div>
                    </div>
                    <div>
                      <div className="text-lg font-semibold">{formatUsd(metrics?.monthly_token_spend_usd ?? 0)}</div>
                      <div className="text-xs text-neutral-500">Token spend (month)</div>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
