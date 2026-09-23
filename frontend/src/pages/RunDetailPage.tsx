import React, { useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { apiFetch } from '../lib/api';
import { Page, ToolCall, WorkflowRunInfo } from '../lib/types';
import { duration, formatNumber, relativeTime } from '../lib/format';
import {
  cardCls,
  ErrorBanner,
  PageHeader,
  rowCls,
  Skeleton,
  StatusBadge,
  tableCls,
  Tabs,
  Td,
  Th,
} from '../components/ui';
import { ChevronLeft } from 'lucide-react';

const STAGES = ['plan', 'generate', 'test', 'export'];

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'tool-calls', label: 'Tool Calls' },
  { id: 'logs', label: 'Logs' },
  { id: 'metadata', label: 'Metadata' },
];

const stageState = (run: WorkflowRunInfo, index: number): 'done' | 'current' | 'pending' => {
  if (run.status === 'completed') return 'done';
  const reached = Math.floor((run.progress_percent / 100) * STAGES.length);
  if (index < reached) return 'done';
  if (index === reached && run.status === 'running') return 'current';
  return 'pending';
};

export const RunDetailPage: React.FC = () => {
  const { runId } = useParams<{ runId: string }>();
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get('project');

  const [run, setRun] = useState<WorkflowRunInfo | null>(null);
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const [logs, setLogs] = useState<Record<string, unknown>[]>([]);
  const [active, setActive] = useState('overview');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    setLoading(true);
    Promise.allSettled([
      apiFetch<WorkflowRunInfo>(`/workflows/${runId}`),
      apiFetch<ToolCall[]>(`/workflows/${runId}/tool-calls`),
      projectId ? apiFetch<Page<Record<string, unknown>>>(`/projects/${projectId}/logs?limit=100`) : Promise.resolve(null),
    ]).then(([r, t, l]) => {
      if (cancelled) return;
      if (r.status === 'fulfilled') setRun(r.value);
      else setError('Run not found or access denied.');
      if (t.status === 'fulfilled') setToolCalls(t.value);
      if (l && l.status === 'fulfilled' && l.value) setLogs(l.value.data);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [runId, projectId]);

  const meta = useMemo(() => (run ? { ...run } : null), [run]);

  if (loading) {
    return (
      <div className="px-6 py-10 lg:px-10">
        <Skeleton className="mb-8 h-10 w-72" />
        <Skeleton className="h-48" />
      </div>
    );
  }

  return (
    <div className="px-6 py-10 lg:px-10">
      <Link
        to="/dashboard/runs"
        className="mb-6 inline-flex items-center gap-1 text-xs text-neutral-400 hover:text-white transition-colors"
      >
        <ChevronLeft className="h-3.5 w-3.5" /> Back to runs
      </Link>

      <PageHeader
        title={`Run ${runId?.slice(0, 8)}`}
        subtitle={projectId ? `Project: ${projectId.slice(0, 8)}…` : undefined}
        actions={run ? <StatusBadge status={run.status} /> : undefined}
      />

      {error && <ErrorBanner message={error} onDismiss={() => setError('')} />}

      {run && (
        <>
          {/* Execution timeline */}
          <div className={`${cardCls} mb-8 p-6 hover:border-white/10`}>
            <div className="mb-4 flex items-center justify-between text-xs text-neutral-400">
              <span>Execution progress</span>
              <span>{run.progress_percent}%</span>
            </div>
            <div className="mb-6 h-1.5 overflow-hidden rounded-full bg-neutral-900">
              <div className="h-full rounded-full bg-blue-500 transition-all duration-500" style={{ width: `${run.progress_percent}%` }} />
            </div>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-0">
              {STAGES.map((stage, i) => {
                const state = stageState(run, i);
                return (
                  <React.Fragment key={stage}>
                    <div className="flex flex-1 items-center gap-2.5">
                      <span
                        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
                          state === 'done'
                            ? 'bg-emerald-500/15 text-emerald-400'
                            : state === 'current'
                              ? 'bg-blue-500/15 text-blue-400 animate-pulse'
                              : 'bg-white/5 text-neutral-600'
                        }`}
                      >
                        {i + 1}
                      </span>
                      <span className={`text-sm capitalize ${state === 'pending' ? 'text-neutral-600' : 'text-neutral-200'}`}>
                        {stage}
                        {state === 'current' && run.current_node ? (
                          <span className="block text-xs text-neutral-500">node: {run.current_node}</span>
                        ) : null}
                      </span>
                    </div>
                    {i < STAGES.length - 1 && <div className="hidden h-px flex-1 bg-white/10 sm:block" />}
                  </React.Fragment>
                );
              })}
            </div>
          </div>

          <div className="mb-6">
            <Tabs tabs={TABS} active={active} onChange={setActive} />
          </div>

          {active === 'overview' && (
            <div className={`${cardCls} max-w-2xl p-6 hover:border-white/10`}>
              <div className="grid grid-cols-2 gap-6 text-sm">
                <div>
                  <div className="text-xs text-neutral-500">Started</div>
                  <div className="mt-1">{run.started_at ? relativeTime(run.started_at) : '—'}</div>
                </div>
                <div>
                  <div className="text-xs text-neutral-500">Completed</div>
                  <div className="mt-1">{run.completed_at ? relativeTime(run.completed_at) : 'running'}</div>
                </div>
                <div>
                  <div className="text-xs text-neutral-500">Duration</div>
                  <div className="mt-1">{duration(run.started_at, run.completed_at)}</div>
                </div>
                <div>
                  <div className="text-xs text-neutral-500">Tokens used</div>
                  <div className="mt-1">{formatNumber(run.total_tokens_used)}</div>
                </div>
              </div>
            </div>
          )}

          {active === 'tool-calls' && (
            <div className={`${cardCls} overflow-x-auto hover:border-white/10`}>
              {toolCalls.length === 0 ? (
                <div className="p-8 text-center text-sm text-neutral-500">No tool calls recorded for this run.</div>
              ) : (
                <table className={tableCls}>
                  <thead>
                    <tr>
                      <Th>#</Th>
                      <Th>Tool</Th>
                      <Th>Duration</Th>
                      <Th>Result</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {toolCalls.map(call => (
                      <tr key={call.id} className={rowCls}>
                        <Td className="text-neutral-500">{call.id}</Td>
                        <Td className="font-mono text-xs">{call.tool_name}</Td>
                        <Td>{call.duration_ms !== null ? `${call.duration_ms} ms` : '—'}</Td>
                        <Td className="max-w-md">
                          <span className="block truncate font-mono text-xs text-neutral-400">
                            {call.result ? JSON.stringify(call.result) : '—'}
                          </span>
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {active === 'logs' && (
            <div className={`${cardCls} p-6 hover:border-white/10`}>
              {!projectId ? (
                <div className="text-sm text-neutral-500">Open this run from the Runs list to load project logs.</div>
              ) : logs.length === 0 ? (
                <div className="text-sm text-neutral-500">No log entries recorded.</div>
              ) : (
                <div className="max-h-[480px] space-y-1.5 overflow-y-auto font-mono text-xs text-neutral-400">
                  {logs.map((entry, i) => (
                    <div key={i} className="rounded-lg bg-white/[0.02] px-3 py-2">
                      {JSON.stringify(entry)}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {active === 'metadata' && (
            <div className={`${cardCls} p-6 hover:border-white/10`}>
              <pre className="overflow-x-auto font-mono text-xs leading-relaxed text-neutral-300">
                {JSON.stringify(meta, null, 2)}
              </pre>
            </div>
          )}
        </>
      )}
    </div>
  );
};
