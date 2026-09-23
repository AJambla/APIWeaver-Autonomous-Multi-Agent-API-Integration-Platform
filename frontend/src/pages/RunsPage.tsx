import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../lib/auth-context';
import { apiFetch } from '../lib/api';
import { HistoryItem, Page, Project, RUN_STATUSES } from '../lib/types';
import { duration, relativeTime, shortId } from '../lib/format';
import {
  cardCls,
  EmptyState,
  ErrorBanner,
  FilterSelect,
  PageHeader,
  rowCls,
  SearchInput,
  Skeleton,
  StatusBadge,
  tableCls,
  Td,
  Th,
} from '../components/ui';
import { Activity, ChevronRight } from 'lucide-react';

const errorMessage = (error: unknown) => (error instanceof Error ? error.message : 'Unable to load runs.');

type RunRow = HistoryItem & { projectName: string; projectId: string };

export const RunsPage: React.FC = () => {
  const { organizationId } = useAuth();
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [projectFilter, setProjectFilter] = useState('all');

  useEffect(() => {
    if (!organizationId) return;
    let cancelled = false;
    apiFetch<Page<Project>>(`/projects?limit=50&organization_id=${organizationId}`)
      .then(async ({ data }) => {
        if (cancelled) return;
        setProjects(data);
        const results = await Promise.allSettled(
          data.map(p =>
            apiFetch<Page<HistoryItem>>(`/projects/${p.id}/history?limit=15`).then(page =>
              page.data.map(item => ({ ...item, projectName: p.name, projectId: p.id })),
            ),
          ),
        );
        if (!cancelled)
          setRuns(
            results
              .filter(r => r.status === 'fulfilled')
              .flatMap(r => r.value)
              .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime()),
          );
      })
      .catch(err => !cancelled && setError(errorMessage(err)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [organizationId]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return runs
      .filter(r => !term || r.workflow_run_id.toLowerCase().includes(term) || r.projectName.toLowerCase().includes(term))
      .filter(r => statusFilter === 'all' || r.status === statusFilter)
      .filter(r => projectFilter === 'all' || r.projectId === projectFilter);
  }, [runs, search, statusFilter, projectFilter]);

  return (
    <div className="px-6 py-10 lg:px-10">
      <PageHeader title="Runs" subtitle="Monitor API integration pipelines and agent executions." />

      {error && <ErrorBanner message={error} onDismiss={() => setError('')} />}

      <div className="mb-6 flex flex-col gap-3 lg:flex-row">
        <SearchInput value={search} onChange={setSearch} placeholder="Search by run ID or project..." className="flex-1 lg:max-w-sm" />
        <FilterSelect
          value={statusFilter}
          onChange={setStatusFilter}
          options={[
            { value: 'all', label: 'All statuses' },
            ...RUN_STATUSES.map(s => ({ value: s, label: s.replace(/_/g, ' ') })),
          ]}
        />
        <FilterSelect
          value={projectFilter}
          onChange={setProjectFilter}
          options={[
            { value: 'all', label: 'All projects' },
            ...projects.map(p => ({ value: p.id, label: p.name })),
          ]}
        />
      </div>

      {loading ? (
        <Skeleton className="h-64" />
      ) : runs.length === 0 ? (
        <EmptyState
          icon={<Activity className="h-6 w-6" />}
          title="No runs yet"
          description="Trigger a workflow from a project workspace — plan, generate, test, and export runs will appear here."
          action={
            <Link to="/dashboard" className="inline-flex h-10 items-center rounded-full bg-white px-5 text-sm font-medium text-black hover:bg-neutral-200 transition-colors">
              Go to Projects
            </Link>
          }
        />
      ) : (
        <div className={`${cardCls} overflow-x-auto hover:border-white/10`}>
          <table className={tableCls}>
            <thead>
              <tr>
                <Th>Run ID</Th>
                <Th>Project</Th>
                <Th>Status</Th>
                <Th>Stages</Th>
                <Th>Started</Th>
                <Th>Duration</Th>
                <Th>Tokens</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {visible.map(run => (
                <tr key={run.id} className={rowCls}>
                  <Td className="font-mono text-xs">{shortId(run.workflow_run_id)}</Td>
                  <Td className="max-w-[180px] truncate font-medium text-white">{run.projectName}</Td>
                  <Td><StatusBadge status={run.status} /></Td>
                  <Td className="max-w-[260px]">
                    <span className="block truncate text-xs text-neutral-400">{run.stages.join(' → ')}</span>
                  </Td>
                  <Td className="whitespace-nowrap text-neutral-500">{relativeTime(run.started_at)}</Td>
                  <Td className="whitespace-nowrap">{duration(run.started_at, run.completed_at)}</Td>
                  <Td>{run.total_tokens ? run.total_tokens.toLocaleString() : '—'}</Td>
                  <Td>
                    <Link
                      to={`/dashboard/runs/${run.workflow_run_id}?project=${run.projectId}`}
                      className="inline-flex items-center gap-1 text-xs font-medium text-neutral-300 hover:text-white transition-colors"
                    >
                      Details <ChevronRight className="h-3.5 w-3.5" />
                    </Link>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
          {visible.length === 0 && (
            <div className="p-8 text-center text-sm text-neutral-500">No runs match the current filters.</div>
          )}
        </div>
      )}
    </div>
  );
};
