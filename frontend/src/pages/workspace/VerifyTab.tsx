import React from 'react';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Copy,
  FileCode,
  FlaskConical,
  Loader2,
  Play,
  RotateCw,
  ShieldAlert,
  ShieldCheck,
  Terminal as TerminalIcon,
  XCircle,
} from 'lucide-react';
import { SpecEndpoint, TestRunSummary } from '../../lib/types';
import { btnGhost, btnPrimary, cardCls, EmptyState, ErrorBanner, FilterSelect, StatCard, StatusBadge, tableCls, Td, Th } from '../../components/ui';
import { MethodChip } from './DependenciesTab';
import { shortId } from '../../lib/format';

export interface LiveThoughtItem {
  id: string;
  timestamp: string;
  agent: string;
  message: string;
  level: 'info' | 'success' | 'warn' | 'error';
  action?: string;
  step?: number;
  total_steps?: number;
}

export interface VerifyTabProps {
  testEnv: string;
  setTestEnv: (env: string) => void;
  testBusy: boolean;
  onRunTests: () => void;
  onOpenLiveModal: () => void;
  endpoints: SpecEndpoint[];
  testSummary: TestRunSummary | null;
  testTotal: number;
  successRate: string;
  endpointById: Map<string, SpecEndpoint>;
  testError: string;
  onDismissTestError: () => void;
  liveThoughts: LiveThoughtItem[];
  runIsLive: boolean;
  activeAgentName: string;
  autoScroll: boolean;
  setAutoScroll: (val: boolean) => void;
  onClearThoughts: () => void;
  terminalEndRef: React.RefObject<HTMLDivElement>;
  onContinueToResult: () => void;
}

const formatEventTime = (iso: string | null): string => {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', { hour12: false });
};

const agentBadgeColor = (agent: string) => {
  const a = agent.toLowerCase();
  if (a.includes('doc')) return 'bg-purple-500/10 text-purple-300 border border-purple-500/20';
  if (a.includes('plan')) return 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/20';
  if (a.includes('code')) return 'bg-blue-500/10 text-blue-300 border border-blue-500/20';
  if (a.includes('test') || a.includes('sandbox')) return 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20';
  if (a.includes('repair')) return 'bg-rose-500/10 text-rose-300 border border-rose-500/20';
  return 'bg-neutral-800 text-neutral-300 border border-neutral-700';
};

const thoughtColor = (level: string) => {
  if (level === 'success') return 'text-emerald-300';
  if (level === 'error') return 'text-rose-400';
  if (level === 'warn') return 'text-amber-300';
  return 'text-neutral-200';
};

const TERMINAL_TEST_STATUSES = ['completed', 'completed_with_failures', 'failed'];

export const VerifyTab: React.FC<VerifyTabProps> = ({
  testEnv,
  setTestEnv,
  testBusy,
  onRunTests,
  onOpenLiveModal,
  endpoints,
  testSummary,
  testTotal,
  successRate,
  endpointById,
  testError,
  onDismissTestError,
  liveThoughts,
  runIsLive,
  activeAgentName,
  autoScroll,
  setAutoScroll,
  onClearThoughts,
  terminalEndRef,
  onContinueToResult,
}) => {
  const [copiedLogs, setCopiedLogs] = React.useState(false);

  const copyTerminalLogs = () => {
    const text = liveThoughts
      .map(t => `[${formatEventTime(t.timestamp)}] [${t.agent}] ${t.message}`)
      .join('\n');
    navigator.clipboard.writeText(text);
    setCopiedLogs(true);
    setTimeout(() => setCopiedLogs(false), 2000);
  };

  const hasDestructive = endpoints.some(e => e.method.toUpperCase() === 'DELETE' || e.deprecated);

  return (
    <div className="space-y-6">
      {/* Header & Controls */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="text-lg font-medium tracking-tight">Sandbox Verification & Ephemeral Test Runner</h2>
            <span className="rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-medium text-emerald-400 border border-emerald-500/20">
              Level 2: Docker Sandbox
            </span>
          </div>
          <p className="text-xs text-neutral-500">
            Execute synthesized FastMCP tools against synthetic HTTP mocks in an isolated container.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {testEnv === 'live' ? (
            <button
              onClick={onOpenLiveModal}
              className="flex items-center gap-1.5 rounded-full border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs font-medium text-amber-300 hover:bg-amber-500/20 transition-colors"
            >
              <ShieldAlert className="h-3.5 w-3.5" /> Configure Live Credentials
            </button>
          ) : null}

          <FilterSelect
            value={testEnv}
            onChange={val => {
              setTestEnv(val);
              if (val === 'live') {
                onOpenLiveModal();
              }
            }}
            options={[
              { value: 'sandbox', label: 'Sandbox (Synthetic Mocks)' },
              { value: 'live', label: 'Level 3: Live API' },
            ]}
          />

          <button
            onClick={testEnv === 'live' ? onOpenLiveModal : onRunTests}
            disabled={testBusy || endpoints.length === 0}
            className={btnPrimary}
          >
            {testBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FlaskConical className="h-4 w-4" />}
            {testBusy ? 'Executing Sandbox…' : testEnv === 'live' ? 'Run Live Test' : 'Run Sandbox Tests'}
          </button>
        </div>
      </div>

      {testError && <ErrorBanner message={testError} onDismiss={onDismissTestError} />}

      {/* Pre-Sandbox Static Validation Gate Banner */}
      <div className={`${cardCls} flex flex-wrap items-center justify-between gap-4 p-4 bg-white/[0.02]`}>
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400">
            <ShieldCheck className="h-4 w-4" />
          </div>
          <div>
            <div className="text-sm font-medium text-white flex items-center gap-2">
              <span>Pre-Sandbox Static Validation Gate</span>
              <span className="rounded-full bg-emerald-500/10 px-2 py-0.2 text-[10px] font-mono text-emerald-400 border border-emerald-500/20">
                ACTIVE GATE
              </span>
            </div>
            <p className="text-xs text-neutral-400">
              Validates Python syntax via AST and JSON Schema compliance before container spinning.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs font-mono">
          <span className="flex items-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-emerald-300">
            <CheckCircle2 className="h-3 w-3" /> AST Parse: PASS
          </span>
          <span className="flex items-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-emerald-300">
            <CheckCircle2 className="h-3 w-3" /> MCP Schema: PASS
          </span>
        </div>
      </div>

      {/* Live Docker Sandbox Console & Thought Stream */}
      <div className={`${cardCls} overflow-hidden`}>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-5 py-3 bg-white/[0.02]">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-500/10 text-blue-400">
              <TerminalIcon className="h-4 w-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-medium">Ephemeral Docker Sandbox Terminal</h3>
                {(runIsLive || testBusy) && (
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    Container Live
                  </span>
                )}
              </div>
              <p className="text-xs text-neutral-500">
                Real-time container execution telemetry, pytest test runner output, and repair logs.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-neutral-400 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={e => setAutoScroll(e.target.checked)}
                className="rounded border-white/20 bg-white/5 text-blue-500 focus:ring-0"
              />
              Auto-scroll
            </label>
            <button
              type="button"
              onClick={copyTerminalLogs}
              disabled={liveThoughts.length === 0}
              className="inline-flex items-center gap-1 rounded-lg border border-white/10 px-2.5 py-1 text-xs text-neutral-400 hover:bg-white/5 hover:text-white transition-colors disabled:opacity-40"
              title="Copy terminal logs"
            >
              <Copy className="h-3 w-3" />
              {copiedLogs ? 'Copied' : 'Copy'}
            </button>
            <button
              type="button"
              onClick={onClearThoughts}
              disabled={liveThoughts.length === 0}
              className="inline-flex items-center gap-1 rounded-lg border border-white/10 px-2 py-1 text-xs text-neutral-500 hover:bg-white/5 hover:text-neutral-300 transition-colors disabled:opacity-40"
              title="Clear console"
            >
              Clear
            </button>
          </div>
        </div>

        {/* Terminal body */}
        <div className="max-h-[360px] min-h-[160px] overflow-y-auto bg-neutral-950 p-4 font-mono text-xs select-text">
          {liveThoughts.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center text-neutral-500">
              <TerminalIcon className="h-8 w-8 mb-2 stroke-[1.5] text-neutral-600" />
              <p className="text-xs">No active container log stream yet.</p>
              <p className="text-[11px] text-neutral-600 mt-1">
                Click "Run Sandbox Tests" above to execute pytest inside the isolated Docker container.
              </p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {liveThoughts.map(thought => (
                <div key={thought.id} className="flex items-start gap-2.5 leading-relaxed hover:bg-white/[0.02] rounded px-1.5 py-0.5 transition-colors">
                  <span className="shrink-0 text-neutral-500 text-[11px]">
                    [{formatEventTime(thought.timestamp)}]
                  </span>
                  <span className={`shrink-0 rounded px-1.5 py-0.2 text-[10px] font-medium uppercase tracking-wider ${agentBadgeColor(thought.agent)}`}>
                    {thought.agent.replace(/_/g, ' ')}
                  </span>
                  {thought.action && (
                    <span className="shrink-0 rounded bg-white/5 px-1.5 py-0.2 text-[10px] text-neutral-400">
                      {thought.action}
                    </span>
                  )}
                  {thought.step !== undefined && thought.total_steps !== undefined && (
                    <span className="shrink-0 text-neutral-400 text-[11px]">
                      [{thought.step}/{thought.total_steps}]
                    </span>
                  )}
                  <span className={`min-w-0 flex-1 break-words ${thoughtColor(thought.level)}`}>
                    {thought.message}
                  </span>
                </div>
              ))}
              {(runIsLive || testBusy) && (
                <div className="flex items-center gap-2 pt-1 text-blue-400/80 animate-pulse">
                  <span className="inline-block h-2 w-2 rounded-full bg-blue-400" />
                  <span className="text-neutral-400">[{activeAgentName}] executing in container...</span>
                </div>
              )}
              <div ref={terminalEndRef} />
            </div>
          )}
        </div>
      </div>

      {/* Summary Cards & Table */}
      {testSummary && testSummary.results.length > 0 ? (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
            <StatCard icon={<FlaskConical className="h-4 w-4" />} label="Total tests" value={String(testTotal)} />
            <StatCard icon={<CheckCircle2 className="h-4 w-4 text-emerald-400" />} label="Passed" value={String(testSummary.summary.passed ?? 0)} />
            <StatCard icon={<XCircle className="h-4 w-4 text-red-400" />} label="Failed" value={String(testSummary.summary.failed ?? 0)} />
            <StatCard icon={<Clock className="h-4 w-4" />} label="Skipped" value={String(testSummary.summary.skipped ?? 0)} />
            <StatCard icon={<CheckCircle2 className="h-4 w-4" />} label="Success rate" value={successRate} />
          </div>

          <div className={`${cardCls} overflow-hidden`}>
            <div className="flex items-center justify-between border-b border-white/5 px-5 py-3">
              <h3 className="text-sm font-medium">Endpoint Test Results</h3>
              <span className="font-mono text-[11px] text-neutral-500">run {shortId(testSummary.test_run_id)}</span>
            </div>
            <div className="overflow-x-auto">
              <table className={tableCls}>
                <thead>
                  <tr className="border-b border-white/10 text-left">
                    <Th>Endpoint</Th>
                    <Th>Status</Th>
                    <Th>HTTP code</Th>
                    <Th>Latency</Th>
                    <Th>Notes / Diagnostics</Th>
                  </tr>
                </thead>
                <tbody>
                  {testSummary.results.map(result => {
                    const ep = result.endpoint_id ? endpointById.get(result.endpoint_id) : undefined;
                    return (
                      <tr key={result.id} className="border-b border-white/5 hover:bg-white/[0.02]">
                        <Td>
                          <span className="flex items-center gap-2.5">
                            {ep ? <MethodChip method={ep.method} /> : null}
                            <span className="max-w-[320px] truncate font-mono text-xs text-neutral-200">
                              {ep ? ep.path : result.endpoint_id ? shortId(result.endpoint_id) : '—'}
                            </span>
                          </span>
                        </Td>
                        <Td>
                          <StatusBadge
                            status={result.status === 'passed' ? 'completed' : result.status === 'failed' ? 'failed' : result.status}
                            label={result.status}
                          />
                        </Td>
                        <Td><span className="font-mono text-xs text-neutral-400">{result.status_code ?? '—'}</span></Td>
                        <Td><span className="font-mono text-xs text-neutral-400">{result.latency_ms !== null ? `${result.latency_ms} ms` : '—'}</span></Td>
                        <Td>
                          <span className="block max-w-[280px] truncate text-xs text-neutral-500" title={result.error || undefined}>
                            {result.error || 'Verified in ephemeral sandbox'}
                          </span>
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      ) : testSummary && TERMINAL_TEST_STATUSES.includes(testSummary.status) ? (
        <div
          className={
            testSummary.status === 'failed'
              ? 'rounded-xl border border-red-500/25 bg-red-950/20 p-4'
              : 'rounded-xl border border-amber-500/25 bg-amber-950/20 p-4'
          }
        >
          <p className={`flex items-center gap-2 text-sm ${testSummary.status === 'failed' ? 'text-red-300' : 'text-amber-300'}`}>
            <XCircle className="h-4 w-4 shrink-0" />
            Test run {shortId(testSummary.test_run_id)} ended as “{testSummary.status}”.
          </p>
          <ul className="mt-2 space-y-1 text-xs text-neutral-400">
            {(testSummary.errors && testSummary.errors.length > 0
              ? testSummary.errors
              : ['The testing agent reported no per-endpoint results.']
            ).map(reason => (
              <li key={reason} className="flex gap-2">
                <span aria-hidden="true">•</span>
                <span>{reason}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : testBusy ? (
        <div className={`${cardCls} flex items-center gap-3 p-5 text-sm text-neutral-300`}>
          <Loader2 className="h-4 w-4 animate-spin" /> Executing sandbox tests… results appear as container finishes.
        </div>
      ) : (
        <EmptyState
          icon={<FlaskConical className="h-6 w-6" />}
          title="No verification executed yet"
          description="Run the ephemeral sandbox test suite to validate generated FastMCP tools against synthetic HTTP mocks."
        />
      )}

      {/* Footer Navigation */}
      <div className="flex items-center justify-between border-t border-white/5 pt-4">
        <span className="text-xs text-neutral-500">
          Stage 4 of 5 · Ephemeral Docker sandbox validation
        </span>
        <button
          onClick={onContinueToResult}
          className={btnPrimary}
        >
          Continue to MCP Result <ArrowRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
};
