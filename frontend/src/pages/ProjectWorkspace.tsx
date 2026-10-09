import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { asUuid } from '../lib/ids';
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  ArrowDown,
  Boxes,
  Check,
  CheckCircle2,
  Clipboard,
  Clock,
  Copy,
  Download,
  FileCode2,
  FileJson,
  FileText,
  FileType,
  FlaskConical,
  GitBranch,
  History,
  Link2,
  Loader2,
  Maximize2,
  Network,
  Play,
  RefreshCw,
  RotateCcw,
  Settings as SettingsIcon,
  ShieldAlert,
  Terminal as TerminalIcon,
  Upload,
  XCircle,
} from 'lucide-react';
import Editor from '@monaco-editor/react';
import { apiFetch, apiFetchBlob } from '../lib/api';
import { useWorkflowEvents, isWorkflowTerminal } from '../lib/use-workflow-events';
import {
  AgentEventLog,
  ApiSpec,
  DependencyGraph,
  DependencyNode,
  ExportRecord,
  ExportTriggerResponse,
  HistoryItem,
  MCPExportResponse,
  Page,
  ProjectSummary,
  SpecEndpoint,
  TestRunSummary,
  TestRunTriggerResponse,
  TriggerWorkflowResponse,
  UploadResponse,
  WorkflowRunInfo,
} from '../lib/types';
import { NormalizedSpec, relativeTime, shortId, specFormat, specVersion, validationState } from '../lib/format';
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
  SearchInput,
  StatCard,
  StatusBadge,
  tableCls,
  Td,
  Th,
} from '../components/ui';
import { LogsTab } from './workspace/LogsTab';
import { SettingsTab } from './workspace/SettingsTab';

type TabId = 'upload' | 'plan' | 'build' | 'test' | 'export' | 'logs' | 'settings';
type UploadMode = 'file' | 'paste' | 'url';
type UploadPhase = 'idle' | 'working' | 'success' | 'error';

const errorMessage = (error: unknown) => (error instanceof Error ? error.message : 'Something went wrong.');

const sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));

// A test run that has stopped moving: polling ends and the panel reports its outcome.
const TERMINAL_TEST_STATUSES = ['completed', 'completed_with_failures', 'failed'];
// An export row still waiting on the pipeline; anything else has a real status.
const OPEN_EXPORT_STATUSES = ['queued', 'pending', 'running'];

const CORE_STEPS: Array<{ id: TabId; n: number; label: string; desc: string }> = [
  { id: 'upload', n: 1, label: 'Upload Spec', desc: 'Import API documentation' },
  { id: 'plan', n: 2, label: 'Topological Plan', desc: 'Analyze API structure' },
  { id: 'build', n: 3, label: 'Build & Agents', desc: 'Configure and run agents' },
  { id: 'test', n: 4, label: 'Test Suite', desc: 'Validate integration' },
  { id: 'export', n: 5, label: 'Export Wizard', desc: 'Generate SDK/client' },
];

const SUPPORTING_STEPS: Array<{ id: TabId; label: string; icon: React.ElementType }> = [
  { id: 'logs', label: 'Event Logs', icon: TerminalIcon },
  { id: 'settings', label: 'Settings', icon: SettingsIcon },
];

const FORMAT_CHIPS = [
  { label: 'OpenAPI', ext: '.yaml / .json', icon: FileJson },
  { label: 'Swagger', ext: '.yaml / .json', icon: FileCode2 },
  { label: 'Postman', ext: '.json', icon: FileJson },
  { label: 'Markdown', ext: '.md', icon: FileText },
  { label: 'PDF', ext: '.pdf', icon: FileType },
];

const NEXT_STAGES = [
  { title: 'Parse & Validate', desc: 'Parse the specification and validate its format.' },
  { title: 'Analyze', desc: 'Extract endpoints, schemas, authentication and parameters.' },
  { title: 'Build Plan', desc: 'Generate API topology and integration plan.' },
  { title: 'Continue', desc: 'Move to the Topological Plan.' },
];

const DEFAULT_SPEC = 'openapi: 3.0.0\ninfo:\n  title: API Specification\n  version: 1.0.0\npaths: {}';

const METHOD_STYLES: Record<string, string> = {
  GET: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
  POST: 'bg-sky-500/10 text-sky-400 border-sky-500/30',
  PUT: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  PATCH: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  DELETE: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
};

const MethodChip: React.FC<{ method: string }> = ({ method }) => (
  <span
    className={`inline-flex shrink-0 items-center rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-bold ${
      METHOD_STYLES[method.toUpperCase()] || 'bg-white/5 text-neutral-400 border-white/15'
    }`}
  >
    {method.toUpperCase()}
  </span>
);

/* Stepper ------------------------------------------------------------------- */

const WorkflowStepper: React.FC<{
  active: TabId;
  onSelect: (id: TabId) => void;
  completed: Record<TabId, boolean>;
}> = ({ active, onSelect, completed }) => (
  <div className="flex items-start gap-1 overflow-x-auto pb-1">
    {CORE_STEPS.map((step, i) => {
      const isActive = active === step.id;
      const isDone = completed[step.id];
      return (
        <React.Fragment key={step.id}>
          <button
            onClick={() => onSelect(step.id)}
            className="group flex w-[128px] shrink-0 flex-col items-center gap-1.5 text-center"
          >
            <span
              className={`flex h-7 w-7 items-center justify-center rounded-full border text-xs font-medium transition-colors ${
                isActive
                  ? 'border-white bg-white text-black'
                  : isDone
                    ? 'border-emerald-500/50 bg-emerald-500/15 text-emerald-400'
                    : 'border-white/15 bg-white/[0.03] text-neutral-500 group-hover:border-white/40 group-hover:text-neutral-300'
              }`}
            >
              {isDone && !isActive ? <Check className="h-3.5 w-3.5" /> : step.n}
            </span>
            <span className={`text-xs leading-tight ${isActive ? 'font-medium text-white' : isDone ? 'text-neutral-300' : 'text-neutral-500'}`}>
              {step.label}
            </span>
            <span className="text-[10px] leading-tight text-neutral-600">{step.desc}</span>
          </button>
          {i < CORE_STEPS.length - 1 && (
            <span className={`mt-3.5 h-px w-6 shrink-0 sm:w-10 ${completed[CORE_STEPS[i].id] ? 'bg-emerald-500/40' : 'bg-white/10'}`} />
          )}
        </React.Fragment>
      );
    })}
    <span className="mx-3 mt-1.5 h-5 w-px shrink-0 bg-white/10" />
    {SUPPORTING_STEPS.map(step => {
      const Icon = step.icon;
      const isActive = active === step.id;
      return (
        <button
          key={step.id}
          onClick={() => onSelect(step.id)}
          className={`flex w-[92px] shrink-0 flex-col items-center gap-1.5 ${isActive ? 'text-white' : 'text-neutral-500 hover:text-neutral-300'}`}
        >
          <span className={`flex h-7 w-7 items-center justify-center rounded-full border ${isActive ? 'border-white/60 bg-white/10' : 'border-white/15'}`}>
            <Icon className="h-3.5 w-3.5" />
          </span>
          <span className="text-xs leading-tight">{step.label}</span>
        </button>
      );
    })}
  </div>
);

/* Upload dropzone ------------------------------------------------------------ */

const UploadDropzone: React.FC<{
  file: File | null;
  onFile: (f: File | null) => void;
  disabled: boolean;
}> = ({ file, onFile, disabled }) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  return (
    <div
      onDragOver={e => {
        e.preventDefault();
        if (!disabled) setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={e => {
        e.preventDefault();
        setDragOver(false);
        const dropped = e.dataTransfer.files?.[0];
        if (dropped && !disabled) onFile(dropped);
      }}
      onClick={() => !disabled && inputRef.current?.click()}
      className={`flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border border-dashed px-6 py-10 text-center transition-colors ${
        dragOver ? 'border-white/70 bg-white/[0.06]' : 'border-white/15 bg-white/[0.02] hover:border-white/35'
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".yaml,.yml,.json,.md,.pdf"
        className="hidden"
        onChange={e => onFile(e.target.files?.[0] ?? null)}
      />
      <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/5">
        <Upload className="h-5 w-5 text-neutral-300" />
      </span>
      {file ? (
        <div>
          <div className="text-sm font-medium">{file.name}</div>
          <div className="text-xs text-neutral-500">
            {(file.size / 1024).toFixed(1)} KB · click to choose a different file
          </div>
        </div>
      ) : (
        <div>
          <div className="text-sm font-medium">Drop your API specification here</div>
          <div className="text-xs text-neutral-500">or click to browse files</div>
        </div>
      )}
      <span className={`${btnGhost} pointer-events-none`}>
        <Clipboard className="h-4 w-4" /> Browse Files
      </span>
      <div className="mt-2 flex flex-wrap items-center justify-center gap-1.5">
        {FORMAT_CHIPS.map(f => {
          const Icon = f.icon;
          return (
            <span key={f.label} className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1 text-[10px] text-neutral-400">
              <Icon className="h-3 w-3" />
              <span className="font-medium text-neutral-300">{f.label}</span>
              {f.ext}
            </span>
          );
        })}
      </div>
    </div>
  );
};

/* Analysis panel ------------------------------------------------------------- */

const AnalysisPanel: React.FC<{ spec: ApiSpec; endpoints: SpecEndpoint[] }> = ({ spec, endpoints }) => {
  const raw = (spec.raw_normalized ?? {}) as NormalizedSpec;
  const schemasObj = raw.components?.schemas ?? raw.definitions ?? {};
  const schemaCount = Object.keys(schemasObj).length;
  const authSchemesObj = raw.components?.securitySchemes ?? raw.securityDefinitions ?? {};
  const authSchemes = Object.keys(authSchemesObj);
  const deprecated = endpoints.filter(e => e.deprecated).length;
  const missingSummary = endpoints.filter(e => !e.summary).length;
  const lowConfidence = endpoints.filter(e => e.confidence_score !== null && e.confidence_score < 0.6).length;
  const validation = validationState(spec.confidence_score);

  const findings = [
    { text: `${specFormat(raw)} detected`, ok: true },
    { text: `${endpoints.length} endpoint${endpoints.length === 1 ? '' : 's'} discovered`, ok: true },
    { text: `${schemaCount} schema${schemaCount === 1 ? '' : 's'} discovered`, ok: true },
    { text: authSchemes.length > 0 ? `Authentication detected (${authSchemes.join(', ')})` : 'No authentication schemes declared', ok: authSchemes.length > 0 },
  ];
  const warnings = [
    deprecated > 0 ? `${deprecated} deprecated endpoint${deprecated === 1 ? '' : 's'}` : null,
    missingSummary > 0 ? `${missingSummary} endpoint${missingSummary === 1 ? '' : 's'} without summary` : null,
    lowConfidence > 0 ? `${lowConfidence} low-confidence extraction${lowConfidence === 1 ? '' : 's'}` : null,
  ].filter((w): w is string => w !== null);

  return (
    <div className={`${cardCls} p-5`}>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium">Specification Analysis</h3>
        <StatusBadge status={validation.status} label={validation.label} />
      </div>
      <ul className="space-y-2">
        {findings.map(f => (
          <li key={f.text} className="flex items-center gap-2.5 text-sm">
            {f.ok ? (
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
            ) : (
              <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
            )}
            <span className="text-neutral-300">{f.text}</span>
          </li>
        ))}
      </ul>
      {warnings.length > 0 && (
        <div className="mt-4 border-t border-white/5 pt-3">
          <div className="mb-2 text-[11px] font-medium uppercase tracking-wider text-neutral-500">Warnings</div>
          <ul className="space-y-1.5">
            {warnings.map(w => (
              <li key={w} className="flex items-center gap-2.5 text-sm text-neutral-400">
                <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

/* Event log helpers ----------------------------------------------------------- */

const eventMessage = (payload: Record<string, unknown> | null): string => {
  if (!payload) return '';
  for (const key of ['message', 'detail', 'summary', 'description', 'error', 'reason']) {
    const v = payload[key];
    if (typeof v === 'string' && v) return v;
  }
  const s = JSON.stringify(payload);
  return s.length > 180 ? `${s.slice(0, 177)}…` : s;
};

const formatEventTime = (iso: string | null): string => {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', { hour12: false });
};

interface LiveThought {
  id: string;
  timestamp: string;
  agent: string;
  message: string;
  level: 'info' | 'success' | 'warn' | 'error';
  action?: string;
  step?: number;
  total_steps?: number;
}

const agentBadgeColor = (agent: string) => {
  const a = agent.toLowerCase();
  if (a.includes('doc')) return 'bg-purple-500/10 text-purple-300 border border-purple-500/20';
  if (a.includes('plan')) return 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/20';
  if (a.includes('gate') || a.includes('approval')) return 'bg-amber-500/10 text-amber-300 border border-amber-500/20';
  if (a.includes('code')) return 'bg-blue-500/10 text-blue-300 border border-blue-500/20';
  if (a.includes('test')) return 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20';
  if (a.includes('repair')) return 'bg-rose-500/10 text-rose-300 border border-rose-500/20';
  if (a.includes('export')) return 'bg-indigo-500/10 text-indigo-300 border border-indigo-500/20';
  return 'bg-neutral-800 text-neutral-300 border border-neutral-700';
};

const thoughtColor = (level: string) => {
  if (level === 'success') return 'text-emerald-300';
  if (level === 'error') return 'text-rose-400';
  if (level === 'warn') return 'text-amber-300';
  return 'text-neutral-200';
};

const formatExportType = (type: string) => {
  const map: Record<string, string> = {
    sdk: 'SDK',
    mcp: 'MCP',
    cicd: 'CI/CD',
    client: 'Client',
    docker: 'Docker',
    docs: 'Docs',
    fastapi: 'FastAPI',
    github: 'GitHub',
  };
  return map[type.toLowerCase()] || type.toUpperCase();
};

/* Main page ------------------------------------------------------------------- */

export const ProjectWorkspace: React.FC = () => {
  // Only a UUID ever reaches an API path (see lib/ids.ts); anything else is "not found".
  const id = asUuid(useParams<{ id: string }>().id);
  const navigate = useNavigate();

  /* --- shared data --- */
  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [spec, setSpec] = useState<ApiSpec | null>(null);
  const [endpoints, setEndpoints] = useState<SpecEndpoint[]>([]);
  const [latestRun, setLatestRun] = useState<HistoryItem | null>(null);
  const [graph, setGraph] = useState<DependencyGraph | null>(null);
  const [logs, setLogs] = useState<AgentEventLog[]>([]);
  const [exports, setExports] = useState<ExportRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  /* --- upload tab --- */
  const [activeTab, setActiveTab] = useState<TabId>('upload');
  const [mode, setMode] = useState<UploadMode>('file');
  const [file, setFile] = useState<File | null>(null);
  const [specContent, setSpecContent] = useState(DEFAULT_SPEC);
  const [urlValue, setUrlValue] = useState('');
  const [urlNote, setUrlNote] = useState('');
  const [phase, setPhase] = useState<UploadPhase>('idle');
  const [uploadError, setUploadError] = useState('');
  const [uploadResult, setUploadResult] = useState<UploadResponse | null>(null);
  const [previewExpanded, setPreviewExpanded] = useState(false);
  const [menuCopied, setMenuCopied] = useState(false);

  /* --- plan tab --- */
  const [dagPlan, setDagPlan] = useState('');
  const [planDocOpen, setPlanDocOpen] = useState(false);
  const [approvedRunId, setApprovedRunId] = useState<string | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const [planError, setPlanError] = useState('');

  /* --- build tab --- */
  const [activeRun, setActiveRun] = useState<WorkflowRunInfo | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [buildError, setBuildError] = useState('');
  const [targetLanguages, setTargetLanguages] = useState<string[]>(['python', 'node']);
  const [liveThoughts, setLiveThoughts] = useState<LiveThought[]>([]);
  const [autoScroll, setAutoScroll] = useState(true);
  const terminalEndRef = useRef<HTMLDivElement>(null);
  /* Polling loops (tests, exports) stop when the page unmounts. */
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);
  /* The project whose dependency graph has been fetched; see the Plan tab effect. */
  const graphFetchedFor = useRef<string | null>(null);

  /* --- test tab --- */
  const [testEnv, setTestEnv] = useState('sandbox');
  const [testBusy, setTestBusy] = useState(false);
  const [testSummary, setTestSummary] = useState<TestRunSummary | null>(null);
  const [testError, setTestError] = useState('');

  /* --- export tab --- */
  const [exportBusy, setExportBusy] = useState<string | null>(null);
  const [exportNote, setExportNote] = useState('');
  const [exportError, setExportError] = useState('');

  /* --- logs tab --- */
  const [logQuery, setLogQuery] = useState('');
  const [logAgent, setLogAgent] = useState('all');
  const [logType, setLogType] = useState('all');

  const loadProjectData = useCallback(async () => {
    if (!id) return;
    setError('');
    try {
      const [summary, history] = await Promise.all([
        apiFetch<ProjectSummary>(`/projects/${id}`),
        apiFetch<Page<HistoryItem>>(`/projects/${id}/history?limit=10`).catch(() => null),
      ]);
      setProject(summary);
      if (history?.data?.length) {
        const inFlightRun = history.data.find(r => ['queued', 'running'].includes(r.status));
        const pausedRun = history.data.find(r => r.status === 'paused_for_approval');
        const latestWorkflowRun = history.data.find(r => r.run_type !== 'export' || r.stages?.includes('plan'));
        const chosenRun = inFlightRun || pausedRun || latestWorkflowRun || history.data[0];
        setLatestRun(chosenRun);
      }

      const [specRes, endpointsRes, graphRes, logsRes, exportsRes, testRes] = await Promise.all([
        apiFetch<ApiSpec>(`/projects/${id}/spec`).catch(() => null),
        apiFetch<SpecEndpoint[]>(`/projects/${id}/endpoints`).catch(() => [] as SpecEndpoint[]),
        apiFetch<DependencyGraph>(`/projects/${id}/dependency-graph`).catch(() => null),
        apiFetch<Page<AgentEventLog>>(`/projects/${id}/logs?limit=100`).catch(() => null),
        apiFetch<ExportRecord[]>(`/projects/${id}/exports`).catch(() => [] as ExportRecord[]),
        apiFetch<TestRunSummary>(`/projects/${id}/test-runs/latest`).catch(() => null),
      ]);
      setSpec(specRes);
      setEndpoints(Array.isArray(endpointsRes) ? endpointsRes : []);
      graphFetchedFor.current = id;
      if (graphRes) {
        setGraph(graphRes);
        if (graphRes.nodes && graphRes.nodes.length > 0) {
          const lines = graphRes.nodes.map((n, i) => `${i + 1}. [${n.method}] ${n.path}${n.label ? ` - ${n.label}` : ''}`);
          setDagPlan(lines.join('\n'));
        }
      }
      setLogs(logsRes?.data ?? []);
      setExports(Array.isArray(exportsRes) ? exportsRes : []);
      if (testRes) setTestSummary(testRes);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    if (!id) {
      setError('A project ID is required.');
      setLoading(false);
      return;
    }
    loadProjectData();
  }, [id, loadProjectData]);

  /* Follow an in-flight workflow run: SSE is the transport; REST only for the
     initial snapshot, the logs list, and the final reconciliation. */
  const { events: runEvents } = useWorkflowEvents(activeRunId);

  useEffect(() => {
    if (!activeRunId) return;
    let cancelled = false;
    apiFetch<WorkflowRunInfo>(`/workflows/${activeRunId}`)
      .then(info => { if (!cancelled) setActiveRun(info); })
      .catch(err => {
        console.warn('Could not fetch active run status; live events will continue driving the panel', err);
      });
    return () => { cancelled = true; };
  }, [activeRunId]);

  /* Stream events repaint the run panel while it is in flight. */
  useEffect(() => {
    const latest = runEvents[runEvents.length - 1];
    if (!latest || !activeRunId) return;
    const payload = (latest.payload ?? {}) as Record<string, unknown>;
    const isPaused =
      (latest.event_type === 'workflow.completed' && payload.status === 'paused_for_approval') ||
      latest.event_type === 'workflow.paused';

    setActiveRun(prev => {
      if (!prev) return prev;
      if (latest.event_type === 'workflow.started') {
        return {
          ...prev,
          status: 'running',
          progress_percent: typeof payload.progress_percent === 'number' ? payload.progress_percent : prev.progress_percent,
        };
      }
      if (latest.event_type === 'workflow.progress') {
        return {
          ...prev,
          current_node: typeof payload.current_node === 'string' ? payload.current_node : prev.current_node,
          progress_percent: typeof payload.progress_percent === 'number' ? payload.progress_percent : prev.progress_percent,
        };
      }
      if (isPaused) {
        return {
          ...prev,
          status: 'paused_for_approval',
          progress_percent: typeof payload.progress_percent === 'number' ? payload.progress_percent : prev.progress_percent,
        };
      }
      return prev;
    });

    if (isPaused) {
      loadProjectData();
    }
  }, [runEvents, activeRunId, loadProjectData]);

  /* A terminal stream event ends the watch: reconcile from REST, then detach. */
  useEffect(() => {
    if (!activeRunId || !id) return;
    const terminal = [...runEvents].reverse().find(
      ev => isWorkflowTerminal(ev.event_type, ev.payload),
    );
    if (!terminal) return;
    let cancelled = false;
    (async () => {
      try {
        const info = await apiFetch<WorkflowRunInfo>(`/workflows/${activeRunId}`);
        if (!cancelled) setActiveRun(info);
      } catch {
        /* the event payload already carries the final status */
      }
      await loadProjectData();
      if (!cancelled) setActiveRunId(null);
    })();
    return () => { cancelled = true; };
  }, [runEvents, activeRunId, id, loadProjectData]);

  /* Pull fresh logs shortly after events land; the trailing debounce collapses bursts. */
  useEffect(() => {
    if (!activeRunId || !id || runEvents.length === 0) return;
    const timer = setTimeout(() => {
      apiFetch<Page<AgentEventLog>>(`/projects/${id}/logs?limit=100`)
        .then(res => setLogs(res.data ?? []))
        .catch(err => {
          console.warn('Could not refresh logs for run', err);
        });
    }, 500);
    return () => clearTimeout(timer);
  }, [runEvents, activeRunId, id]);

  /* Accumulate live thoughts from SSE events */
  useEffect(() => {
    if (runEvents.length === 0) return;
    const newThoughts: LiveThought[] = [];
    for (const ev of runEvents) {
      if (ev.event_type === 'agent.thought' && ev.payload && typeof ev.payload === 'object') {
        const p = ev.payload as Record<string, unknown>;
        newThoughts.push({
          id: ev.id,
          timestamp: (p.timestamp as string) || new Date().toISOString(),
          agent: (p.agent_name as string) || 'orchestrator',
          message: (p.message as string) || '',
          level: (p.level as 'info' | 'success' | 'warn' | 'error') || 'info',
          action: p.action as string | undefined,
          step: typeof p.step === 'number' ? p.step : undefined,
          total_steps: typeof p.total_steps === 'number' ? p.total_steps : undefined,
        });
      } else if (ev.event_type === 'workflow.started') {
        newThoughts.push({
          id: ev.id,
          timestamp: new Date().toISOString(),
          agent: 'orchestrator',
          message: 'Workflow execution initiated. LangGraph state machine active.',
          level: 'info',
          action: 'workflow_started',
        });
      } else if (ev.event_type === 'workflow.progress' && ev.payload && typeof ev.payload === 'object') {
        const p = ev.payload as Record<string, unknown>;
        if (p.current_node) {
          newThoughts.push({
            id: ev.id,
            timestamp: new Date().toISOString(),
            agent: String(p.current_node),
            message: `Entering pipeline stage [${p.current_node}] (${p.progress_percent || 0}%)`,
            level: 'info',
            action: 'stage_transition',
          });
        }
      }
    }
    if (newThoughts.length > 0) {
      setLiveThoughts(prev => {
        const seen = new Set(prev.map(t => t.id));
        const append = newThoughts.filter(t => !seen.has(t.id));
        if (append.length === 0) return prev;
        return [...prev, ...append];
      });
    }
  }, [runEvents]);

  /* Hydrate historical thoughts from project logs if terminal or returning */
  useEffect(() => {
    if (logs.length === 0) return;
    setLiveThoughts(prev => {
      if (prev.length > 0) return prev;
      const fromLogs: LiveThought[] = [];
      const sorted = [...logs].reverse();
      for (const log of sorted) {
        const p = log.payload || {};
        const msg = (p.message as string) || eventMessage(p) || log.event_type;
        const lvl: 'info' | 'success' | 'warn' | 'error' =
          log.event_type.includes('fail') || log.event_type.includes('error')
            ? 'error'
            : log.event_type.includes('complete') || log.event_type.includes('pass')
            ? 'success'
            : log.event_type.includes('pause') || log.event_type.includes('warn')
            ? 'warn'
            : ((p.level as 'info' | 'success' | 'warn' | 'error') || 'info');
        fromLogs.push({
          id: log.id,
          timestamp: log.created_at || new Date().toISOString(),
          agent: log.agent_name || 'orchestrator',
          message: msg,
          level: lvl,
          action: (p.action as string) || log.event_type,
          step: typeof p.step === 'number' ? p.step : undefined,
          total_steps: typeof p.total_steps === 'number' ? p.total_steps : undefined,
        });
      }
      return fromLogs;
    });
  }, [logs]);

  /* Auto-scroll terminal when new thoughts arrive */
  useEffect(() => {
    if (autoScroll && terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [liveThoughts, autoScroll]);

  /* Resume watching a run that is still in flight when the build tab opens. */
  useEffect(() => {
    if (activeTab !== 'build' || activeRunId || !latestRun) return;
    if (['queued', 'running', 'paused_for_approval'].includes(latestRun.status)) {
      setActiveRunId(latestRun.workflow_run_id);
    }
  }, [activeTab, activeRunId, latestRun]);

  /* Load the dependency graph when the Plan tab opens, once per project.
     Keyed on a ref, not on `graph`: a project with no dependencies legitimately has
     zero edges, and re-fetching "until there are edges" looped until rate limited. */
  useEffect(() => {
    if (activeTab === 'plan' && id && graphFetchedFor.current !== id) {
      graphFetchedFor.current = id;
      apiFetch<DependencyGraph>(`/projects/${id}/dependency-graph`)
        .then(g => {
          if (g) {
            setGraph(g);
            if (g.nodes && g.nodes.length > 0) {
              const lines = g.nodes.map((n, i) => `${i + 1}. [${n.method}] ${n.path}${n.label ? ` - ${n.label}` : ''}`);
              setDagPlan(lines.join('\n'));
            }
          }
        })
        .catch(() => {
          graphFetchedFor.current = null;
        });
    }
  }, [activeTab, id]);

  /* Refresh test summary when Test tab opens if missing */
  useEffect(() => {
    if (activeTab === 'test' && id && !testSummary) {
      apiFetch<TestRunSummary>(`/projects/${id}/test-runs/latest`)
        .then(ts => { if (ts) setTestSummary(ts); })
        .catch(err => {
          console.warn('Could not fetch latest test summary', err);
        });
    }
  }, [activeTab, id, testSummary]);

  const stepCompleted = useMemo<Record<TabId, boolean>>(() => {
    const uploadDone = spec !== null;
    const runDone = project?.last_run_status === 'completed';
    return {
      upload: uploadDone,
      plan: uploadDone && runDone,
      build: uploadDone && runDone,
      test: uploadDone && runDone,
      export: uploadDone && runDone,
      logs: false,
      settings: false,
    };
  }, [spec, project]);

  // URL mode uploads nothing directly: Import fetches the document into the editor
  // (switching to paste mode) so it can be reviewed first.
  const hasValidInput = mode === 'file' ? file !== null : mode === 'paste' ? specContent.trim().length > 0 : false;

  const handleUpload = async () => {
    if (!id || !hasValidInput || phase === 'working') return;
    setPhase('working');
    setUploadError('');
    setUploadResult(null);
    try {
      const isJson = specContent.trim().startsWith('{');
      const payloadFile =
        mode === 'file' && file
          ? file
          : new File(
          [specContent],
          isJson ? 'spec.json' : 'spec.yaml',
          { type: isJson ? 'application/json' : 'application/yaml' },
        );
      const formData = new FormData();
      formData.append('file', payloadFile);

      // Content-sniffing: inspect snippet from uploaded file or pasted content to pass accurate hint
      try {
        let snippet = '';
        if (mode === 'paste') {
          snippet = specContent.slice(0, 2000);
        } else if (file) {
          snippet = await file.slice(0, 2048).text();
        }
        if (snippet.includes('"swagger"') || snippet.includes('swagger:')) {
          formData.append('format_hint', 'swagger');
        } else if (snippet.includes('"info"') && snippet.includes('"item"')) {
          formData.append('format_hint', 'postman');
        } else if (snippet.includes('"openapi"') || snippet.includes('openapi:')) {
          formData.append('format_hint', 'openapi');
        }
      } catch {
        // Fall back to backend content-sniffing
      }

      const result = await apiFetch<UploadResponse>(`/projects/${id}/upload`, {
        method: 'POST',
        body: formData,
      });
      setUploadResult(result);
      setPhase('success');
      if (result.workflow_run_id) setActiveRunId(result.workflow_run_id);
      await loadProjectData();
    } catch (err) {
      setPhase('error');
      setUploadError(errorMessage(err));
    }
  };

  const handleUrlImport = async () => {
    if (!urlValue.trim()) return;
    setPhase('working');
    setUploadError('');
    setUrlNote('');
    try {
      // Fetched server-side: the page's CSP only allows its own origin, and the server
      // applies SSRF and size limits to the target.
      const fetched = await apiFetch<{ content: string }>(`/projects/${id}/fetch-spec`, {
        method: 'POST',
        body: JSON.stringify({ url: urlValue.trim() }),
      });
      setSpecContent(fetched.content);
      setMode('paste');
      setUrlNote('Specification fetched — review it below, then upload & analyze.');
      setPhase('idle');
    } catch (err) {
      setPhase('error');
      setUploadError(errorMessage(err));
    }
  };

  const resetUpload = () => {
    setFile(null);
    setUrlValue('');
    setUrlNote('');
    setPhase('idle');
    setUploadError('');
    setUploadResult(null);
    setSpecContent(DEFAULT_SPEC);
  };

  /* --- plan actions --- */

  /* The run waiting at the approval gate, if any: approving anything else is a 422. */
  const pausedRunId =
    (activeRun?.status === 'paused_for_approval' ? activeRun.id : null) ||
    (latestRun?.status === 'paused_for_approval' ? latestRun.workflow_run_id : null);

  /* An approval belongs to one run; a different run pausing starts unapproved. Approving
     moves the run out of the gate (pausedRunId becomes null), which used to reset this flag
     and flip the button straight back to a disabled "Approve Plan". */
  const planApproved = approvedRunId !== null && (pausedRunId === null || pausedRunId === approvedRunId);

  const approvePlan = async () => {
    if (!pausedRunId) return;
    setPlanBusy(true);
    setPlanError('');
    try {
      await apiFetch(`/workflows/${pausedRunId}/approve`, {
        method: 'POST',
        body: JSON.stringify({
          approved: true,
          target_languages: targetLanguages.length > 0 ? targetLanguages : ['python', 'node'],
        }),
      });
      setActiveRunId(pausedRunId);
      setActiveRun(prev => (prev ? { ...prev, status: 'running' } : null));
      setApprovedRunId(pausedRunId);
      await loadProjectData();
    } catch (err) {
      setPlanError(errorMessage(err));
    } finally {
      setPlanBusy(false);
    }
  };

  const cancelWorkflow = async () => {
    const runId = activeRunId || latestRun?.workflow_run_id;
    if (!runId) return;
    setCancelBusy(true);
    try {
      await apiFetch(`/workflows/${runId}/cancel`, { method: 'POST' });
      setActiveRun(prev => (prev ? { ...prev, status: 'cancelled' } : null));
      await loadProjectData();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setCancelBusy(false);
    }
  };

  /* --- build actions --- */

  const runBuild = async () => {
    if (!id) return;
    setBuildError('');
    try {
      const res = await apiFetch<TriggerWorkflowResponse>(`/projects/${id}/workflows`, {
        method: 'POST',
        body: JSON.stringify({
          stages: ['plan', 'generate', 'test', 'export'],
          target_languages: targetLanguages.length > 0 ? targetLanguages : ['python', 'node'],
          // Runs execute on the agent worker; the API falls back in-process only in
          // development when no worker is reachable.
          execution_mode: 'async',
        }),
      });
      setActiveRunId(res.workflow_run_id);
    } catch (err) {
      setBuildError(errorMessage(err));
    }
  };

  /* --- test actions --- */

  const runTests = async () => {
    if (!id) return;
    setTestBusy(true);
    setTestError('');
    setTestSummary(null);
    try {
      const trigger = await apiFetch<TestRunTriggerResponse>(`/projects/${id}/test`, {
        method: 'POST',
        body: JSON.stringify({ environment: testEnv }),
      });
      let summary: TestRunSummary | null = null;
      for (let attempt = 0; attempt < 20; attempt += 1) {
        await sleep(attempt === 0 ? 1500 : 3000);
        if (!mountedRef.current) return;
        summary = await apiFetch<TestRunSummary>(`/projects/${id}/test-runs/${trigger.test_run_id}`).catch(() => summary);
        if (summary && (summary.results.length > 0 || TERMINAL_TEST_STATUSES.includes(summary.status))) break;
      }
      if (mountedRef.current) setTestSummary(summary);
    } catch (err) {
      if (mountedRef.current) setTestError(errorMessage(err));
    } finally {
      if (mountedRef.current) setTestBusy(false);
    }
  };

  /* --- export actions --- */

  const triggerExport = async (exportType: string) => {
    if (!id || exportBusy !== null) return;
    setExportBusy(exportType);
    setExportError('');
    setExportNote('');
    try {
      if (exportType === 'mcp') {
        const res = await apiFetch<MCPExportResponse>(`/projects/${id}/export/mcp`, { method: 'POST' });
        setExportNote(`MCP export complete — ${res.tools_generated} tool${res.tools_generated === 1 ? '' : 's'} generated, ${res.flagged_destructive} flagged destructive.`);
      } else {
        const triggered = await apiFetch<ExportTriggerResponse>(`/projects/${id}/export`, {
          method: 'POST',
          body: JSON.stringify({ export_types: [exportType] }),
        });
        const watched = new Set(triggered.artifacts.map(a => a.export_id));
        let rows: ExportRecord[] = [];
        for (let attempt = 0; attempt < 20; attempt += 1) {
          await sleep(attempt === 0 ? 1500 : 3000);
          if (!mountedRef.current) return;
          const next = await apiFetch<ExportRecord[]>(`/projects/${id}/exports`).catch(() => null);
          if (Array.isArray(next)) rows = next;
          const mine = rows.filter(row => watched.has(row.id));
          if (mine.length > 0 && mine.every(row => !OPEN_EXPORT_STATUSES.includes(row.status))) break;
        }
        setExports(rows);
        const mine = rows.filter(row => watched.has(row.id));
        if (mine.length === 0) {
          setExportError('The export could not be tracked — no export row was recorded.');
        } else if (mine.some(row => row.status === 'failed')) {
          setExportError(`${exportType} export failed. See Recent exports for the recorded status.`);
        } else if (mine.every(row => row.status === 'completed')) {
          setExportNote(`${exportType} export completed.`);
        } else {
          setExportNote(`${exportType} export is still running — refresh Recent exports for its result.`);
        }
        return;
      }
      const rows = await apiFetch<ExportRecord[]>(`/projects/${id}/exports`).catch(() => [] as ExportRecord[]);
      setExports(Array.isArray(rows) ? rows : []);
    } catch (err) {
      setExportError(errorMessage(err));
    } finally {
      setExportBusy(null);
    }
  };

  const handleDownloadExport = async (row: ExportRecord) => {
    if (!row.download_url) return;
    setExportError('');
    try {
      const { blob, filename: served } = await apiFetchBlob(row.download_url);
      const filename = served || `export-${row.export_type}.zip`;
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } catch (err) {
      setExportError(`Download failed: ${errorMessage(err)}`);
    }
  };

  /* --- derived view data --- */

  const [filePreview, setFilePreview] = useState('');
  useEffect(() => {
    if (mode === 'file' && file && !file.name.toLowerCase().endsWith('.pdf')) {
      let cancelled = false;
      file.text().then(text => {
        if (!cancelled) setFilePreview(text);
      });
      return () => {
        cancelled = true;
      };
    }
    setFilePreview('');
    return undefined;
  }, [mode, file]);

  const editorValue = phase === 'success' && spec && !file
    ? JSON.stringify(spec.raw_normalized, null, 2)
    : mode === 'file' && file
      ? filePreview
      : specContent;

  const editorLanguage = (name: string) =>
    name.toLowerCase().endsWith('.json') ? 'json' : name.toLowerCase().endsWith('.md') ? 'markdown' : 'yaml';
  const language = phase === 'success' && spec ? 'json' : editorLanguage(file?.name ?? 'spec.yaml');

  const rawSpec = useMemo(() => (spec?.raw_normalized ?? {}) as NormalizedSpec, [spec]);
  const projectDescription = useMemo(() => {
    const info = rawSpec.info?.description?.trim();
    if (info) return info.length > 160 ? `${info.slice(0, 157)}…` : info;
    if (spec) {
      const parts = [specFormat(rawSpec), specVersion(rawSpec) !== '—' ? `v${specVersion(rawSpec)}` : null, spec.base_url];
      return parts.filter(Boolean).join(' · ');
    }
    return 'No specification uploaded yet.';
  }, [spec, rawSpec]);

  /* Topology: group graph nodes by resource (first meaningful path segment). */
  const resourceGroups = useMemo(() => {
    if (!graph || graph.nodes.length === 0) return [];
    const skip = new Set(['api', 'v1', 'v2', 'v3']);
    const nodeById = new Map(graph.nodes.map(n => [n.id, n]));
    const groups = new Map<string, DependencyNode[]>();
    for (const node of graph.nodes) {
      const segs = node.path.split('/').filter(s => s && !s.startsWith('{'));
      const key = segs.find(s => !skip.has(s.toLowerCase())) || 'general';
      const list = groups.get(key) || [];
      list.push(node);
      groups.set(key, list);
    }
    const edgeCounts = new Map<string, { out: number; targets: string[] }>();
    for (const edge of graph.edges) {
      const from = nodeById.get(edge.from_id);
      const to = nodeById.get(edge.to_id);
      if (!from) continue;
      const entry = edgeCounts.get(from.id) || { out: 0, targets: [] };
      entry.out += 1;
      if (to && entry.targets.length < 2) entry.targets.push(to.label || `${to.method} ${to.path}`);
      edgeCounts.set(from.id, entry);
    }
    return Array.from(groups.entries())
      .sort((a, b) => b[1].length - a[1].length)
      .map(([resource, nodes]) => ({ resource, nodes, edgeCounts }));
  }, [graph]);

  /* Agent execution streams: group logs by agent name. */
  const agentStreams = useMemo(() => {
    const byAgent = new Map<string, AgentEventLog[]>();
    for (const log of logs) {
      const name = log.agent_name || 'System';
      const list = byAgent.get(name) || [];
      list.push(log);
      byAgent.set(name, list);
    }
    return Array.from(byAgent.entries()).map(([agent, events]) => ({
      agent,
      events: events.length,
      latest: events[0], // logs arrive newest-first
    }));
  }, [logs]);

  const activeAgentName = useMemo(() => {
    if (activeRun?.current_node) {
      const map: Record<string, string> = {
        doc_agent: 'Specification Normalizer',
        planner_agent: 'Topological DAG Planner',
        approval_gate: 'Approval Gate (Human Review)',
        code_agent: 'SDK Code Generator',
        test_agent: 'Docker Sandbox Test Runner',
        repair_agent: 'Self-Healing Repair Agent',
        export_agent: 'Packaging & Distribution Agent',
        completed: 'Pipeline Completed',
      };
      return map[activeRun.current_node] || activeRun.current_node;
    }
    return 'Agent Orchestrator';
  }, [activeRun?.current_node]);

  const agentNames = useMemo(
    () => Array.from(new Set(logs.map(l => l.agent_name || 'System'))).sort(),
    [logs],
  );
  const eventTypes = useMemo(
    () => Array.from(new Set(logs.map(l => l.event_type))).sort(),
    [logs],
  );
  const visibleLogs = useMemo(
    () =>
      logs.filter(l => {
        if (logAgent !== 'all' && (l.agent_name || 'System') !== logAgent) return false;
        if (logType !== 'all' && l.event_type !== logType) return false;
        if (logQuery) {
          const q = logQuery.toLowerCase();
          const hay = `${l.event_type} ${l.agent_name ?? ''} ${eventMessage(l.payload)}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      }),
    [logs, logAgent, logType, logQuery],
  );

  const endpointById = useMemo(() => new Map(endpoints.map(e => [e.id, e])), [endpoints]);

  const runIsLive = activeRun !== null && ['queued', 'running', 'paused_for_approval'].includes(activeRun.status);

  if (loading) {
    return (
      <div className="min-h-screen bg-black text-white flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-white" />
      </div>
    );
  }

  if (!project) {
    return (
      <div className="min-h-screen bg-black text-white flex flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-sm text-red-300">{error || 'Unable to load the project.'}</p>
        <Link to="/dashboard" className="rounded-xl border border-white/15 px-4 py-2 text-sm text-white hover:bg-white/10">
          Return to projects
        </Link>
      </div>
    );
  }

  const showAnalysis = spec !== null;
  const uploadedMeta = uploadResult
    ? { name: file?.name ?? 'pasted-spec.yaml', format: spec ? specFormat((spec.raw_normalized ?? {}) as NormalizedSpec) : '—' }
    : null;

  const testTotal = testSummary?.summary.total ?? 0;
  const testPassed = testSummary?.summary.passed ?? 0;
  const successRate = testTotal > 0 ? `${((testPassed / testTotal) * 100).toFixed(1)}%` : '—';

  return (
    <div className="min-h-screen bg-black text-white flex flex-col selection:bg-white selection:text-black">
      {/* Project header */}
      <header className="border-b border-white/10 bg-black/60 backdrop-blur-xl sticky top-0 z-40">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 pt-4">
          <div className="flex items-center gap-3">
            <Link
              to="/dashboard"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/10 text-neutral-400 hover:bg-white/5 hover:text-white transition-colors"
              title="Back to projects"
            >
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <nav className="min-w-0 flex-1 truncate text-xs text-neutral-500">
              <Link to="/dashboard" className="hover:text-white transition-colors">Projects</Link>
              <span className="mx-1.5">/</span>
              <span className="text-neutral-300">{project.name}</span>
            </nav>
            <StatusBadge status={project.status} />
            <OptionsMenu
              items={[
                {
                  label: menuCopied ? 'Copied!' : 'Copy project ID',
                  onSelect: () => {
                    navigator.clipboard.writeText(project.id);
                    setMenuCopied(true);
                    setTimeout(() => setMenuCopied(false), 1500);
                  },
                },
                ...(latestRun
                  ? [{ label: 'Open latest run', onSelect: () => navigate(`/dashboard/runs/${latestRun.workflow_run_id}?project=${project.id}`) }]
                  : []),
              ]}
            />
          </div>
          <div className="mt-2 flex flex-wrap items-end justify-between gap-x-6 gap-y-1 pb-4">
            <div className="min-w-0 max-w-3xl">
              <h1 className="truncate text-xl font-semibold tracking-tight">{project.name}</h1>
              <p className="truncate text-sm text-neutral-400" title={projectDescription}>{projectDescription}</p>
              <p className="text-xs text-neutral-500">
                {project.endpoint_count} endpoint{project.endpoint_count === 1 ? '' : 's'} · created {relativeTime(project.created_at)} · updated {relativeTime(project.updated_at)}
              </p>
            </div>
            {(activeRun?.status || latestRun?.status || project.last_run_status) && (
              <div className="flex items-center gap-2 text-xs text-neutral-500">
                <History className="h-3.5 w-3.5" />
                {activeRun && ['queued', 'running', 'paused_for_approval'].includes(activeRun.status)
                  ? 'current run:'
                  : 'last run:'}{' '}
                <StatusBadge
                  status={
                    activeRun && ['queued', 'running', 'paused_for_approval'].includes(activeRun.status)
                      ? activeRun.status
                      : (latestRun?.status || project.last_run_status!)
                  }
                />
                {activeRun && ['queued', 'running', 'paused_for_approval'].includes(activeRun.status) && (
                  <button
                    type="button"
                    onClick={cancelWorkflow}
                    disabled={cancelBusy}
                    className="ml-2 inline-flex items-center gap-1 rounded-md border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-xs font-medium text-red-400 hover:bg-red-500/20 disabled:opacity-50 transition-colors"
                    title="Cancel active workflow immediately"
                  >
                    <XCircle className="h-3.5 w-3.5" />
                    {cancelBusy ? 'Cancelling...' : 'Cancel Run'}
                  </button>
                )}
              </div>
            )}
          </div>
          {/* Workflow stepper */}
          <div className="border-t border-white/5 py-4">
            <WorkflowStepper active={activeTab} onSelect={setActiveTab} completed={stepCompleted} />
          </div>
        </div>
      </header>

      {error && (
        <div className="mx-auto mt-6 w-full max-w-7xl px-4 sm:px-6">
          <ErrorBanner message={error} onDismiss={() => setError('')} />
        </div>
      )}

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6">
        {/* ============================== UPLOAD ============================== */}
        {activeTab === 'upload' && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-1 rounded-xl border border-white/10 bg-white/[0.02] p-1">
              {([
                { id: 'file', label: 'Upload File', icon: Upload },
                { id: 'paste', label: 'Paste Specification', icon: Clipboard },
                { id: 'url', label: 'Import from URL', icon: Link2 },
              ] as const).map(m => {
                const Icon = m.icon;
                return (
                  <button
                    key={m.id}
                    onClick={() => setMode(m.id)}
                    className={`flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm transition-colors ${
                      mode === m.id ? 'bg-white text-black font-medium' : 'text-neutral-400 hover:bg-white/5 hover:text-white'
                    }`}
                  >
                    <Icon className="h-4 w-4" /> {m.label}
                  </button>
                );
              })}
            </div>

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
              <div className="space-y-4 lg:col-span-3">
                {mode === 'file' && <UploadDropzone file={file} onFile={f => { setFile(f); setPhase('idle'); }} disabled={phase === 'working'} />}

                {mode === 'paste' && (
                  <div className={`${cardCls} overflow-hidden`}>
                    <div className="flex items-center justify-between border-b border-white/5 px-4 py-2.5">
                      <span className="text-xs uppercase tracking-wider text-neutral-500">Specification source</span>
                    </div>
                    <div className="h-[320px]">
                      <Editor
                        height="100%"
                        defaultLanguage="yaml"
                        theme="vs-dark"
                        value={specContent}
                        onChange={val => setSpecContent(val || '')}
                        options={{ minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false }}
                      />
                    </div>
                  </div>
                )}

                {mode === 'url' && (
                  <div className={`${cardCls} p-5`}>
                    <label htmlFor="spec-url" className="mb-1.5 block text-xs uppercase tracking-wider text-neutral-500">
                      API Specification URL
                    </label>
                    <div className="flex flex-col gap-2 sm:flex-row">
                      <input
                        id="spec-url"
                        type="url"
                        value={urlValue}
                        onChange={e => setUrlValue(e.target.value)}
                        placeholder="https://petstore3.swagger.io/api/v3/openapi.json"
                        className={`${inputCls} flex-1`}
                        disabled={phase === 'working'}
                      />
                      <button
                        onClick={handleUrlImport}
                        disabled={!urlValue.trim() || phase === 'working'}
                        className={btnPrimary}
                      >
                        {phase === 'working' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />} Import
                      </button>
                    </div>
                    <p className="mt-2 text-[11px] text-neutral-500">
                      Fetches the document in your browser and loads it into the editor for review before ingestion.
                    </p>
                    {urlNote && <p className="mt-2 text-xs text-emerald-300">{urlNote}</p>}
                  </div>
                )}

                {phase === 'working' && (
                  <div className={`${cardCls} flex items-center gap-3 p-4 text-sm text-neutral-300`}>
                    <Loader2 className="h-4 w-4 animate-spin text-white" />
                    Uploading & parsing specification…
                  </div>
                )}
                {phase === 'error' && <ErrorBanner message={uploadError || 'Unable to process specification.'} onDismiss={() => setPhase('idle')} />}
                {phase === 'success' && uploadedMeta && (
                  <div className={`${cardCls} flex flex-wrap items-center gap-x-6 gap-y-2 p-4`}>
                    {uploadResult && uploadResult.endpoints_discovered === 0 && !spec ? (
                      <>
                        <AlertTriangle className="h-5 w-5 text-amber-400" />
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium text-amber-300">Document uploaded · Background AI extraction queued</div>
                          <div className="truncate text-xs text-neutral-400">
                            {uploadedMeta.name} · 0 endpoints discovered deterministically. The AI doc agent is processing freeform content.
                          </div>
                        </div>
                      </>
                    ) : (
                      <>
                        <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium">Specification uploaded successfully</div>
                          <div className="truncate text-xs text-neutral-500">
                            {uploadedMeta.name}
                            {file ? ` · ${(file.size / 1024).toFixed(1)} KB` : ''} · {uploadedMeta.format}
                            {uploadResult ? ` · ${uploadResult.endpoints_discovered} endpoint${uploadResult.endpoints_discovered === 1 ? '' : 's'}` : ''}
                          </div>
                        </div>
                        <StatusBadge status={validationState(spec?.confidence_score).status} label={validationState(spec?.confidence_score).label} />
                      </>
                    )}
                  </div>
                )}
              </div>

              <div className={`${cardCls} flex min-w-0 flex-col lg:col-span-2`}>
                <div className="flex items-center justify-between border-b border-white/5 px-4 py-2.5">
                  <span className="text-sm font-medium">Specification Preview</span>
                  <div className="flex items-center gap-2">
                    <span className="rounded-md border border-white/10 px-1.5 py-0.5 text-[10px] uppercase text-neutral-500">
                      {language}
                    </span>
                    <button
                      onClick={() => setPreviewExpanded(true)}
                      className="rounded-lg p-1.5 text-neutral-400 hover:bg-white/5 hover:text-white transition-colors"
                      title="Expand preview"
                    >
                      <Maximize2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
                <div className="h-[360px] min-h-0">
                  <Editor
                    height="100%"
                    language={language}
                    theme="vs-dark"
                    value={editorValue || '# Nothing to preview yet'}
                    options={{
                      readOnly: true,
                      minimap: { enabled: false },
                      fontSize: 12,
                      lineNumbers: 'on',
                      scrollBeyondLastLine: false,
                      renderLineHighlight: 'none',
                    }}
                  />
                </div>
                {file?.name.toLowerCase().endsWith('.pdf') && (
                  <div className="border-t border-white/5 px-4 py-2 text-[11px] text-neutral-500">
                    PDF documents are parsed server-side; no text preview available.
                  </div>
                )}
              </div>
            </div>

            {showAnalysis && <AnalysisPanel spec={spec} endpoints={endpoints} />}

            <div>
              <h3 className="mb-3 text-sm font-medium uppercase tracking-wider text-neutral-400">What happens next?</h3>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {NEXT_STAGES.map((stage, i) => (
                  <div key={stage.title} className={`${cardCls} relative p-4`}>
                    <div className="mb-1.5 flex items-center gap-2">
                      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-white/5 text-[10px] font-medium text-neutral-400">
                        {i + 1}
                      </span>
                      <span className="text-sm font-medium">{stage.title}</span>
                    </div>
                    <p className="text-xs leading-relaxed text-neutral-500">{stage.desc}</p>
                    {i < NEXT_STAGES.length - 1 && (
                      <ArrowRight className="absolute -right-3 top-1/2 hidden h-4 w-4 -translate-y-1/2 text-neutral-700 xl:block" />
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/5 pt-5">
              <button onClick={resetUpload} className={btnGhost} disabled={phase === 'working'}>
                <RotateCcw className="h-4 w-4" /> Reset
              </button>
              {phase === 'success' ? (
                <button onClick={() => setActiveTab('plan')} className={btnPrimary}>
                  Continue to Topological Plan <ArrowRight className="h-4 w-4" />
                </button>
              ) : (
                <button
                  onClick={handleUpload}
                  disabled={!hasValidInput || phase === 'working'}
                  className={btnPrimary}
                >
                  {phase === 'working' ? (
                    <><Loader2 className="h-4 w-4 animate-spin" /> Analyzing…</>
                  ) : (
                    <>Upload & Analyze <ArrowRight className="h-4 w-4" /></>
                  )}
                </button>
              )}
            </div>
          </div>
        )}

        {/* =============================== PLAN =============================== */}
        {activeTab === 'plan' && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-medium tracking-tight">API Topology & Integration Plan</h2>
                <p className="text-xs text-neutral-500">
                  {graph && graph.nodes.length > 0
                    ? `${graph.nodes.length} endpoint${graph.nodes.length === 1 ? '' : 's'} · ${graph.edges.length} ${graph.edges.length === 1 ? 'dependency' : 'dependencies'} extracted from the specification`
                    : 'Generated from the uploaded specification'}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => setPlanDocOpen(true)} className={btnGhost}>
                  <FileText className="h-4 w-4" /> View Full Document
                </button>
                <button
                  onClick={approvePlan}
                  disabled={planBusy || planApproved || !pausedRunId}
                  className={`flex items-center gap-2 rounded-full px-5 h-10 text-sm font-medium transition-colors ${
                    planApproved
                      ? 'border border-emerald-500/30 bg-emerald-500/15 text-emerald-300'
                      : btnPrimary
                  }`}
                >
                  {planBusy ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : planApproved ? (
                    <Check className="h-4 w-4" />
                  ) : (
                    <CheckCircle2 className="h-4 w-4" />
                  )}
                  {planApproved ? 'Plan Approved' : 'Approve Plan'}
                </button>
              </div>
            </div>

            {planError && <ErrorBanner message={planError} onDismiss={() => setPlanError('')} />}
            {!pausedRunId && !planApproved && (
              <p className="text-xs text-neutral-500">
                Nothing is waiting for approval. Start a build — it pauses here so you can review the plan first.
              </p>
            )}

            {resourceGroups.length === 0 ? (
              <EmptyState
                icon={<Network className="h-6 w-6" />}
                title="No topology available yet"
                description={spec
                  ? 'This specification did not yield any endpoints, so there is nothing to plan. Upload a richer specification to build the graph.'
                  : 'Upload an API specification to generate the endpoint topology and integration plan.'}
                action={
                  <button onClick={() => setActiveTab('upload')} className={btnPrimary}>
                    Go to Upload <ArrowRight className="h-4 w-4" />
                  </button>
                }
              />
            ) : (
              <div className="flex items-stretch gap-3 overflow-x-auto pb-2">
                {resourceGroups.map(group => (
                  <div key={group.resource} className={`${cardCls} w-64 shrink-0 p-4 hover:bg-white/[0.04]`}>
                    <div className="mb-3 flex items-center justify-between">
                      <span className="truncate text-sm font-medium capitalize">{group.resource}</span>
                      <span className="ml-2 shrink-0 rounded-full bg-white/5 px-2 py-0.5 text-[10px] text-neutral-400">
                        {group.nodes.length}
                      </span>
                    </div>
                    <div className="space-y-2">
                      {group.nodes.map(node => {
                        const deps = group.edgeCounts.get(node.id);
                        return (
                          <div key={node.id} className="rounded-xl border border-white/10 bg-white/[0.02] p-2.5">
                            <div className="flex items-center gap-2">
                              <MethodChip method={node.method} />
                              <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-neutral-300" title={node.path}>
                                {node.path}
                              </span>
                              {node.is_destructive && (
                                <ShieldAlert className="h-3.5 w-3.5 shrink-0 text-rose-400" aria-label="Destructive operation" />
                              )}
                            </div>
                            {node.label && node.label !== `${node.method} ${node.path}` && (
                              <div className="mt-1 truncate text-[11px] text-neutral-500" title={node.label}>{node.label}</div>
                            )}
                            {deps && deps.out > 0 && (
                              <div className="mt-1.5 flex items-start gap-1.5 text-[10px] text-neutral-500">
                                <ArrowDown className="mt-0.5 h-3 w-3 shrink-0" />
                                <span className="min-w-0">
                                  depends on {deps.out} endpoint{deps.out === 1 ? '' : 's'}
                                  {deps.targets.length > 0 && ` (${deps.targets.join(', ')}${deps.out > deps.targets.length ? ', …' : ''})`}
                                </span>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className={`${cardCls} p-5 flex flex-wrap items-center justify-between gap-3`}>
              <div>
                <h3 className="mb-1 text-sm font-medium">Execution schedule</h3>
                <p className="text-xs text-neutral-500">
                  Review or edit the generated plan document. Agents execute it in the Build step.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => setPlanDocOpen(true)} className={btnGhost}>
                  <FileCode2 className="h-4 w-4" /> Open plan document
                </button>
                <button onClick={() => setActiveTab('build')} className={btnPrimary}>
                  Continue to Build & Agents <ArrowRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
        )}

        {/* =============================== BUILD ============================== */}
        {activeTab === 'build' && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-medium tracking-tight">Agent Build & Execution</h2>
                <p className="text-xs text-neutral-500">Trigger the multi-agent pipeline and monitor each agent's event stream.</p>
              </div>
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 p-1 text-xs">
                  <span className="px-2 text-neutral-400 font-mono text-[11px]">Targets:</span>
                  {(['python', 'node'] as const).map(lang => {
                    const isSelected = targetLanguages.includes(lang);
                    return (
                      <button
                        key={lang}
                        type="button"
                        onClick={() => {
                          setTargetLanguages(prev => {
                            if (isSelected) {
                              if (prev.length <= 1) return prev; // Keep at least one
                              return prev.filter(l => l !== lang);
                            } else {
                              return [...prev, lang];
                            }
                          });
                        }}
                        className={`rounded px-2.5 py-1 font-mono uppercase transition-colors ${
                          isSelected
                            ? 'bg-blue-600/40 text-blue-200 border border-blue-500/30'
                            : 'text-neutral-500 hover:text-neutral-300'
                        }`}
                      >
                        {lang}
                      </button>
                    );
                  })}
                </div>
                <button
                  onClick={activeRun?.status === 'paused_for_approval' ? () => setActiveTab('plan') : runBuild}
                  disabled={(runIsLive && activeRun?.status !== 'paused_for_approval') || !project}
                  className={btnPrimary}
                >
                  {activeRun?.status === 'paused_for_approval' ? (
                    <CheckCircle2 className="h-4 w-4 text-amber-400" />
                  ) : runIsLive ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="h-4 w-4" />
                  )}
                  {activeRun?.status === 'paused_for_approval'
                    ? 'Review Plan (Approval Required)'
                    : runIsLive
                    ? 'Pipeline Running…'
                    : 'Run Build Pipeline'}
                </button>
              </div>
            </div>

            {buildError && <ErrorBanner message={buildError} onDismiss={() => setBuildError('')} />}

            {activeRun && (
              <div className={`${cardCls} p-5`}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <StatusBadge status={activeRun.status} />
                    {activeRun.current_node && (
                      <span className="font-mono text-xs text-neutral-400">node: {activeRun.current_node}</span>
                    )}
                  </div>
                  <div className="flex items-center gap-4 text-xs text-neutral-500">
                    <span className="flex items-center gap-1.5"><Clock className="h-3.5 w-3.5" /> started {relativeTime(activeRun.started_at)}</span>
                    <span>{activeRun.total_tokens_used.toLocaleString()} tokens</span>
                  </div>
                </div>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ${
                      activeRun.status === 'failed' ? 'bg-red-500/60' : activeRun.status === 'completed' ? 'bg-emerald-500' : 'bg-blue-500'
                    }`}
                    style={{ width: `${Math.max(4, activeRun.progress_percent)}%` }}
                  />
                </div>
                <div className="mt-1.5 text-right text-[11px] text-neutral-500">{activeRun.progress_percent}%</div>
              </div>
            )}

            {/* Live Agent Activity & Terminal Console */}
            <div className={`${cardCls} overflow-hidden`}>
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-5 py-3 bg-white/[0.02]">
                <div className="flex items-center gap-2.5">
                  <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-500/10 text-blue-400">
                    <TerminalIcon className="h-4 w-4" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-medium">Live Agent Activity & Thought Stream</h3>
                      {runIsLive && (
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                          Live Stream
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-neutral-500">
                      Real-time LangGraph agent thoughts, DAG transitions, and execution telemetry.
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {runIsLive && (
                    <span className="rounded-lg border border-blue-500/20 bg-blue-500/10 px-2.5 py-1 text-xs text-blue-300 font-mono">
                      Active: {activeAgentName}
                    </span>
                  )}
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
                    onClick={() => {
                      const text = liveThoughts.map(t => `[${formatEventTime(t.timestamp)}] [${t.agent}] ${t.message}`).join('\n');
                      navigator.clipboard.writeText(text);
                    }}
                    disabled={liveThoughts.length === 0}
                    className="inline-flex items-center gap-1 rounded-lg border border-white/10 px-2.5 py-1 text-xs text-neutral-400 hover:bg-white/5 hover:text-white transition-colors disabled:opacity-40"
                    title="Copy terminal logs"
                  >
                    <Copy className="h-3 w-3" />
                    Copy
                  </button>
                  <button
                    type="button"
                    onClick={() => setLiveThoughts([])}
                    disabled={liveThoughts.length === 0}
                    className="inline-flex items-center gap-1 rounded-lg border border-white/10 px-2 py-1 text-xs text-neutral-500 hover:bg-white/5 hover:text-neutral-300 transition-colors disabled:opacity-40"
                    title="Clear console"
                  >
                    Clear
                  </button>
                </div>
              </div>

              {/* Terminal body */}
              <div className="max-h-[380px] min-h-[160px] overflow-y-auto bg-neutral-950 p-4 font-mono text-xs select-text">
                {liveThoughts.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-12 text-center text-neutral-500">
                    <TerminalIcon className="h-8 w-8 mb-2 stroke-[1.5] text-neutral-600" />
                    <p className="text-xs">No active thought stream recorded yet.</p>
                    <p className="text-[11px] text-neutral-600 mt-1">
                      Trigger "Run Build Pipeline" above to stream live agent decisions and sandbox telemetry.
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
                    {runIsLive && (
                      <div className="flex items-center gap-2 pt-1 text-blue-400/80 animate-pulse">
                        <span className="inline-block h-2 w-2 rounded-full bg-blue-400" />
                        <span className="text-neutral-400">[{activeAgentName}] executing stage...</span>
                      </div>
                    )}
                    <div ref={terminalEndRef} />
                  </div>
                )}
              </div>
            </div>

            {agentStreams.length === 0 ? (
              <EmptyState
                icon={<Boxes className="h-6 w-6" />}
                title="No agent activity yet"
                description="Run the build pipeline to see per-agent execution streams here. Each agent's events will appear as they are emitted."
              />
            ) : (
              <div className={`${cardCls} overflow-hidden`}>
                <div className="border-b border-white/5 px-5 py-3">
                  <h3 className="text-sm font-medium">Agent Execution Streams</h3>
                </div>
                <table className={tableCls}>
                  <thead>
                    <tr className="border-b border-white/10 text-left">
                      <Th>Agent</Th>
                      <Th>Latest event</Th>
                      <Th>Status</Th>
                      <Th>Activity</Th>
                      <Th>Updated</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {agentStreams.map(stream => (
                      <tr key={stream.agent} className="border-b border-white/5 hover:bg-white/[0.02]">
                        <Td>
                          <span className="flex items-center gap-2.5">
                            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/5">
                              <Boxes className="h-3.5 w-3.5 text-neutral-400" />
                            </span>
                            <span className="text-sm font-medium">{stream.agent}</span>
                          </span>
                        </Td>
                        <Td>
                          <span className="block max-w-[320px] truncate font-mono text-xs text-neutral-400" title={eventMessage(stream.latest?.payload ?? null)}>
                            {stream.latest?.event_type?.replace(/_/g, ' ') || '—'}
                            {eventMessage(stream.latest?.payload ?? null) ? ` — ${eventMessage(stream.latest?.payload ?? null)}` : ''}
                          </span>
                        </Td>
                        <Td><StatusBadge status={stream.latest?.event_type} /></Td>
                        <Td>
                          <span className="rounded-full bg-white/5 px-2 py-0.5 text-[11px] text-neutral-400">
                            {stream.events} event{stream.events === 1 ? '' : 's'}
                          </span>
                        </Td>
                        <Td>
                          <span className="text-xs text-neutral-500">{relativeTime(stream.latest?.created_at)}</span>
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* =============================== TEST =============================== */}
        {activeTab === 'test' && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-medium tracking-tight">Test Suite & Self-Healing Telemetry</h2>
                <p className="text-xs text-neutral-500">Execute generated tests against {testEnv === 'live' ? 'the live API' : 'a sandbox'} and inspect per-endpoint results.</p>
              </div>
              <div className="flex items-center gap-2">
                <FilterSelect
                  value={testEnv}
                  onChange={setTestEnv}
                  options={[
                    { value: 'sandbox', label: 'Sandbox' },
                    { value: 'live', label: 'Live' },
                  ]}
                />
                <button onClick={runTests} disabled={testBusy || endpoints.length === 0} className={btnPrimary}>
                  {testBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FlaskConical className="h-4 w-4" />}
                  {testBusy ? 'Running…' : 'Run Test Suite'}
                </button>
              </div>
            </div>

            {testError && <ErrorBanner message={testError} onDismiss={() => setTestError('')} />}

            {endpoints.length === 0 && (
              <p className="text-xs text-amber-300">
                No endpoints discovered for this project — upload a specification with paths before running tests.
              </p>
            )}

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
                    <h3 className="text-sm font-medium">Test results</h3>
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
                          <Th>Notes</Th>
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
                              <Td><StatusBadge status={result.status === 'passed' ? 'completed' : result.status === 'failed' ? 'failed' : result.status} label={result.status} /></Td>
                              <Td><span className="font-mono text-xs text-neutral-400">{result.status_code ?? '—'}</span></Td>
                              <Td><span className="font-mono text-xs text-neutral-400">{result.latency_ms !== null ? `${result.latency_ms} ms` : '—'}</span></Td>
                              <Td>
                                <span className="block max-w-[280px] truncate text-xs text-neutral-500" title={result.error || undefined}>
                                  {result.error || ''}
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
                  Test run {shortId(testSummary.test_run_id)} ended as “{testSummary.status}” without running any tests.
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
                <Loader2 className="h-4 w-4 animate-spin" /> Executing tests… results appear as each endpoint completes.
              </div>
            ) : (
              <EmptyState
                icon={<FlaskConical className="h-6 w-6" />}
                title="No test run yet"
                description="Run the test suite to validate generated integration code. Pass/fail counts, status codes and latency will appear here."
              />
            )}
          </div>
        )}

        {/* ============================== EXPORT ============================== */}
        {activeTab === 'export' && (
          <div className="space-y-6">
            <div>
              <h2 className="text-lg font-medium tracking-tight">Export Integration</h2>
              <p className="text-xs text-neutral-500">Generate artifacts from the built integration. Export status is tracked below.</p>
            </div>

            {exportError && <ErrorBanner message={exportError} onDismiss={() => setExportError('')} />}
            {exportNote && (
              <div className={`${cardCls} flex items-center gap-3 p-4 text-sm text-emerald-300`}>
                <CheckCircle2 className="h-4 w-4 shrink-0" /> {exportNote}
              </div>
            )}

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {[
                { type: 'sdk', title: 'Python SDK', desc: 'Generated client package with typed models and async support.' },
                { type: 'client', title: 'TypeScript Client', desc: 'Typed client library generated from the normalized specification.' },
                { type: 'docker', title: 'Dockerfile & Compose', desc: 'Containerized deployment bundle for the generated service.' },
                { type: 'mcp', title: 'MCP Tools', desc: 'Export the integration as Model Context Protocol tools.' },
                { type: 'docs', title: 'API Documentation', desc: 'Rendered documentation for the integrated API.' },
                { type: 'cicd', title: 'CI/CD Pipelines', desc: 'Pipeline definitions for building and testing the integration.' },
              ].map(target => (
                <div key={target.type} className={`${cardCls} flex flex-col p-5 transition-colors hover:border-white/25`}>
                  <h3 className="mb-1 text-sm font-medium">{target.title}</h3>
                  <p className="mb-4 flex-1 text-xs leading-relaxed text-neutral-500">{target.desc}</p>
                  <button
                    onClick={() => triggerExport(target.type)}
                    disabled={exportBusy !== null}
                    className={`${btnGhost} h-9 px-4 text-xs disabled:opacity-40 disabled:cursor-not-allowed`}
                  >
                    {exportBusy === target.type ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Boxes className="h-3.5 w-3.5" />}
                    {exportBusy === target.type ? 'Generating...' : 'Generate'}
                  </button>
                </div>
              ))}
            </div>

            <div className={`${cardCls} overflow-hidden`}>
              <div className="flex items-center justify-between border-b border-white/5 px-5 py-3">
                <h3 className="text-sm font-medium">Recent exports</h3>
                <button
                  onClick={async () => {
                    if (!id) return;
                    const rows = await apiFetch<ExportRecord[]>(`/projects/${id}/exports`).catch(() => [] as ExportRecord[]);
                    setExports(Array.isArray(rows) ? rows : []);
                  }}
                  className="rounded-lg p-1.5 text-neutral-400 hover:bg-white/5 hover:text-white"
                  title="Refresh"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                </button>
              </div>
              {exports.length === 0 ? (
                <p className="px-5 py-8 text-center text-sm text-neutral-500">No exports generated yet.</p>
              ) : (
                <table className={tableCls}>
                  <thead>
                    <tr className="border-b border-white/10 text-left">
                      <Th>Type</Th>
                      <Th>Status</Th>
                      <Th>Created</Th>
                      <Th>Artifact</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {exports.map(row => (
                      <tr key={row.id} className="border-b border-white/5 hover:bg-white/[0.02]">
                        <Td><span className="font-mono text-xs">{formatExportType(row.export_type)}</span></Td>
                        <Td><StatusBadge status={row.status} /></Td>
                        <Td><span className="text-xs text-neutral-500">{relativeTime(row.created_at)}</span></Td>
                        <Td>
                          {row.download_url ? (
                            <button
                              type="button"
                              onClick={() => handleDownloadExport(row)}
                              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-xs font-medium text-white hover:bg-white/10 transition-colors"
                              title="Download artifact archive"
                            >
                              <Download className="h-3 w-3 text-neutral-400" />
                              Download
                            </button>
                          ) : (
                            <span className="text-xs text-neutral-500">—</span>
                          )}
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}

        {/* =============================== LOGS =============================== */}
        {activeTab === 'logs' && (
          <LogsTab
            logs={logs}
            visibleLogs={visibleLogs}
            logQuery={logQuery}
            setLogQuery={setLogQuery}
            logAgent={logAgent}
            setLogAgent={setLogAgent}
            logType={logType}
            setLogType={setLogType}
            agentNames={agentNames}
            eventTypes={eventTypes}
            loadProjectData={loadProjectData}
            formatEventTime={formatEventTime}
            eventMessage={eventMessage}
          />
        )}

        {/* ============================= SETTINGS ============================= */}
        {activeTab === 'settings' && (
          <SettingsTab
            project={project}
            spec={spec}
            rawSpec={rawSpec}
          />
        )}
      </main>

      {/* Fullscreen preview modal */}
      {previewExpanded && (
        <Modal onClose={() => setPreviewExpanded(false)} title="Specification Preview">
          <div className="h-[60vh] overflow-hidden rounded-xl border border-white/15">
            <Editor
              height="100%"
              language={language}
              theme="vs-dark"
              value={editorValue || '# Nothing to preview yet'}
              options={{ readOnly: true, minimap: { enabled: false }, fontSize: 13, lineNumbers: 'on', scrollBeyondLastLine: false }}
            />
          </div>
        </Modal>
      )}

      {/* Plan document modal */}
      {planDocOpen && (
        <Modal onClose={() => setPlanDocOpen(false)} title="Topological Plan Document">
          <div className="h-[60vh] overflow-hidden rounded-xl border border-white/15">
            <Editor
              height="100%"
              defaultLanguage="markdown"
              theme="vs-dark"
              value={dagPlan}
              onChange={val => setDagPlan(val || '')}
              options={{ minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false }}
            />
          </div>
        </Modal>
      )}
    </div>
  );
};
