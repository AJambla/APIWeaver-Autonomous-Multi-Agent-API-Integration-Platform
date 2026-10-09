import React from 'react';
import { RefreshCw } from 'lucide-react';
import { AgentEventLog } from '../../lib/types';
import { btnGhost, FilterSelect, SearchInput } from '../../components/ui';

interface LogsTabProps {
  logs: AgentEventLog[];
  visibleLogs: AgentEventLog[];
  logQuery: string;
  setLogQuery: (q: string) => void;
  logAgent: string;
  setLogAgent: (a: string) => void;
  logType: string;
  setLogType: (t: string) => void;
  agentNames: string[];
  eventTypes: string[];
  loadProjectData: () => void;
  formatEventTime: (iso: string | null) => string;
  eventMessage: (payload: Record<string, unknown> | null) => string;
}

export const LogsTab: React.FC<LogsTabProps> = ({
  logs,
  visibleLogs,
  logQuery,
  setLogQuery,
  logAgent,
  setLogAgent,
  logType,
  setLogType,
  agentNames,
  eventTypes,
  loadProjectData,
  formatEventTime,
  eventMessage,
}) => {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-medium tracking-tight">Real-Time Event Stream</h2>
          <p className="text-xs text-neutral-500">{logs.length} agent event{logs.length === 1 ? '' : 's'} recorded for this project.</p>
        </div>
        <button onClick={loadProjectData} className={btnGhost}>
          <RefreshCw className="h-4 w-4" /> Refresh
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <SearchInput value={logQuery} onChange={setLogQuery} placeholder="Search events…" className="min-w-[220px] flex-1" />
        <FilterSelect
          value={logAgent}
          onChange={setLogAgent}
          options={[{ value: 'all', label: 'All agents' }, ...agentNames.map(n => ({ value: n, label: n }))]}
        />
        <FilterSelect
          value={logType}
          onChange={setLogType}
          options={[{ value: 'all', label: 'All events' }, ...eventTypes.map(t => ({ value: t, label: t.replace(/_/g, ' ') }))]}
        />
      </div>

      <div className="max-h-[520px] overflow-y-auto rounded-2xl border border-white/15 bg-neutral-950 p-4 font-mono text-xs">
        {visibleLogs.length === 0 ? (
          <p className="py-10 text-center text-neutral-500">
            {logs.length === 0
              ? 'No events recorded yet. Upload a specification or run the build pipeline to generate agent events.'
              : 'No events match the current filters.'}
          </p>
        ) : (
          visibleLogs.map(ev => (
            <div key={ev.id} className="flex items-start gap-3 border-b border-white/5 py-2 last:border-0">
              <span className="shrink-0 text-neutral-500">[{formatEventTime(ev.created_at)}]</span>
              {ev.workflow_run_id && (
                <span
                  className="shrink-0 rounded bg-blue-500/10 px-1.5 py-0.5 font-mono text-[10px] text-blue-400"
                  title={`Run ID: ${ev.workflow_run_id}`}
                >
                  {ev.workflow_run_id.slice(0, 8)}
                </span>
              )}
              <span className="shrink-0 rounded bg-white/10 px-2 py-0.5 text-[10px] text-neutral-300">{ev.agent_name || 'System'}</span>
              <span className="shrink-0 rounded bg-white/5 px-2 py-0.5 text-[10px] uppercase tracking-wider text-neutral-400">{ev.event_type}</span>
              <span className="min-w-0 flex-1 break-words text-neutral-200">{eventMessage(ev.payload) || '—'}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
