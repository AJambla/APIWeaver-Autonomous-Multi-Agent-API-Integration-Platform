import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
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
import { apiFetch } from '../lib/api';
import {
  AgentEventLog,
  ApiSpec,
  DependencyGraph,
  DependencyNode,
  ExportRecord,
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

type TabId = 'upload' | 'plan' | 'build' | 'test' | 'export' | 'logs' | 'settings';
type UploadMode = 'file' | 'paste' | 'url';
type UploadPhase = 'idle' | 'working' | 'success' | 'error';

const errorMessage = (error: unknown) => (error instanceof Error ? error.message : 'Something went wrong.');

const sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));

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

const DEFAULT_SPEC = 'openapi: 3.0.0\ninfo:\n  title: Sample API\n  version: 1.0.0\npaths: {}';

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
  const raw = (spec.raw_normalized ?? {}) as NormalizedSpec & { security?: unknown[] };
  const schemaCount = Object.keys(raw.components?.schemas ?? {}).length;
  const authSchemes = Object.keys((raw.components as { securitySchemes?: Record<string, unknown> } | undefined)?.securitySchemes ?? {});
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

/* Main page ------------------------------------------------------------------- */

export const ProjectWorkspace: React.FC = () => {
  const { id } = useParams<{ id: string }>();

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
  const [dagPlan, setDagPlan] = useState('1. Parse OpenAPI schema & extract models\n2. Generate FastAPI routers & Pydantic validation\n3. Initialize Celery background tasks & storage service\n4. Execute self-healing test suite');
  const [planDocOpen, setPlanDocOpen] = useState(false);
  const [planApproved, setPlanApproved] = useState(false);
  const [planBusy, setPlanBusy] = useState(false);
  const [planError, setPlanError] = useState('');

  /* --- build tab --- */
  const [activeRun, setActiveRun] = useState<WorkflowRunInfo | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [buildError, setBuildError] = useState('');

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
        apiFetch<Page<HistoryItem>>(`/projects/${id}/history?limit=1`).catch(() => null),
      ]);
      setProject(summary);
      if (history?.data?.length) setLatestRun(history.data[0]);

      const [specRes, endpointsRes, graphRes, logsRes, exportsRes] = await Promise.all([
        apiFetch<ApiSpec>(`/projects/${id}/spec`).catch(() => null),
        apiFetch<SpecEndpoint[]>(`/projects/${id}/endpoints`).catch(() => [] as SpecEndpoint[]),
        apiFetch<DependencyGraph>(`/projects/${id}/dependency-graph`).catch(() => null),
        apiFetch<Page<AgentEventLog>>(`/projects/${id}/logs?limit=100`).catch(() => null),
        apiFetch<ExportRecord[]>(`/projects/${id}/exports`).catch(() => [] as ExportRecord[]),
      ]);
      setSpec(specRes);
      setEndpoints(Array.isArray(endpointsRes) ? endpointsRes : []);
      if (graphRes) setGraph(graphRes);
      setLogs(logsRes?.data ?? []);
      setExports(Array.isArray(exportsRes) ? exportsRes : []);
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

  /* Follow an in-flight workflow run: poll status + refresh logs while running. */
  useEffect(() => {
    if (!activeRunId || !id) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const [info, logsRes] = await Promise.all([
          apiFetch<WorkflowRunInfo>(`/workflows/${activeRunId}`),
          apiFetch<Page<AgentEventLog>>(`/projects/${id}/logs?limit=100`).catch(() => null),
        ]);
        if (cancelled) return;
        setActiveRun(info);
        if (logsRes) setLogs(logsRes.data ?? []);
        if (['completed', 'failed', 'cancelled'].includes(info.status)) {
          setActiveRunId(null);
          loadProjectData();
        }
      } catch {
        /* transient poll failure — retry on next tick */
      }
    };
    tick();
    const timer = setInterval(tick, 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [activeRunId, id, loadProjectData]);

  /* Resume watching a run that is still in flight when the build tab opens. */
  useEffect(() => {
    if (activeTab !== 'build' || activeRunId || !latestRun) return;
    if (['queued', 'running', 'paused_for_approval'].includes(latestRun.status)) {
      setActiveRunId(latestRun.workflow_run_id);
    }
  }, [activeTab, activeRunId, latestRun]);

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

  const hasValidInput = mode === 'file' ? file !== null : mode === 'paste' ? specContent.trim().length > 0 : urlValue.trim().length > 0;

  const handleUpload = async () => {
    if (!id || !hasValidInput || phase === 'working') return;
    setPhase('working');
    setUploadError('');
    setUploadResult(null);
    try {
      const payloadFile =
        file ?? new File([specContent], 'openapi.yaml', { type: 'application/yaml' });
      const formData = new FormData();
      formData.append('file', payloadFile);
      formData.append('format_hint', 'openapi');

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
      const res = await fetch(urlValue.trim());
      if (!res.ok) throw new Error(`Unable to fetch the URL (${res.status} ${res.statusText}).`);
      const text = await res.text();
      setSpecContent(text);
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

  const approvePlan = async () => {
    setPlanBusy(true);
    setPlanError('');
    try {
      if (latestRun) {
        await apiFetch(`/workflows/${latestRun.workflow_run_id}/approve`, {
          method: 'POST',
          body: JSON.stringify({ approved: true }),
        });
      }
      setPlanApproved(true);
    } catch (err) {
      setPlanError(errorMessage(err));
    } finally {
      setPlanBusy(false);
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
          target_languages: ['python', 'node'],
          execution_mode: 'sync',
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
        summary = await apiFetch<TestRunSummary>(`/projects/${id}/test-runs/${trigger.test_run_id}`).catch(() => summary);
        if (summary && summary.results.length > 0) break;
      }
      setTestSummary(summary);
    } catch (err) {
      setTestError(errorMessage(err));
    } finally {
      setTestBusy(false);
    }
  };

  /* --- export actions --- */

  const triggerExport = async (exportType: string) => {
    if (!id) return;
    setExportBusy(exportType);
    setExportError('');
    setExportNote('');
    try {
      if (exportType === 'mcp') {
        const res = await apiFetch<MCPExportResponse>(`/projects/${id}/export/mcp`, { method: 'POST' });
        setExportNote(`MCP export complete — ${res.tools_generated} tool${res.tools_generated === 1 ? '' : 's'} generated, ${res.flagged_destructive} flagged destructive.`);
      } else {
        await apiFetch(`/projects/${id}/export`, {
          method: 'POST',
          body: JSON.stringify({ export_types: [exportType] }),
        });
        setExportNote(`${exportType} export queued.`);
      }
      const rows = await apiFetch<ExportRecord[]>(`/projects/${id}/exports`).catch(() => [] as ExportRecord[]);
      setExports(Array.isArray(rows) ? rows : []);
    } catch (err) {
      setExportError(errorMessage(err));
    } finally {
      setExportBusy(null);
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
                  ? [{ label: 'Open latest run', onSelect: () => window.location.assign(`/dashboard/runs/${latestRun.workflow_run_id}?project=${project.id}`) }]
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
            {project.last_run_status && (
              <div className="flex items-center gap-2 text-xs text-neutral-500">
                <History className="h-3.5 w-3.5" /> last run: <StatusBadge status={project.last_run_status} />
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
                    <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium">Specification uploaded successfully</div>
                      <div className="truncate text-xs text-neutral-500">
                        {uploadedMeta.name}
                        {file ? ` · ${(file.size / 1024).toFixed(1)} KB` : ''} · {uploadedMeta.format}
                      </div>
                    </div>
                    <StatusBadge status={validationState(spec?.confidence_score).status} label={validationState(spec?.confidence_score).label} />
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
                    ? `${graph.nodes.length} endpoint${graph.nodes.length === 1 ? '' : 's'} · ${graph.edges.length} dependency${graph.edges.length === 1 ? '' : 'ies'} extracted from the specification`
                    : 'Generated from the uploaded specification'}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => setPlanDocOpen(true)} className={btnGhost}>
                  <FileText className="h-4 w-4" /> View Full Document
                </button>
                <button
                  onClick={approvePlan}
                  disabled={planBusy || planApproved}
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
            {planApproved && !latestRun && (
              <p className="text-xs text-neutral-500">
                Approval recorded locally — no workflow run exists yet, so it will apply when a build is triggered.
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

            <div className={`${cardCls} p-5`}>
              <h3 className="mb-2 text-sm font-medium">Execution schedule</h3>
              <p className="mb-3 text-xs text-neutral-500">
                Review or edit the generated plan document before approving. Agents execute it in the Build step.
              </p>
              <button onClick={() => setPlanDocOpen(true)} className={btnGhost}>
                <FileCode2 className="h-4 w-4" /> Open plan document
              </button>
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
              <button onClick={runBuild} disabled={runIsLive || !project} className={btnPrimary}>
                {runIsLive ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                {runIsLive ? 'Pipeline Running…' : 'Run Build Pipeline'}
              </button>
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
                    className={`${btnGhost} h-9 px-4 text-xs`}
                  >
                    {exportBusy === target.type ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Boxes className="h-3.5 w-3.5" />}
                    Generate
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
                    </tr>
                  </thead>
                  <tbody>
                    {exports.map(row => (
                      <tr key={row.id} className="border-b border-white/5 hover:bg-white/[0.02]">
                        <Td><span className="font-mono text-xs capitalize">{row.export_type}</span></Td>
                        <Td><StatusBadge status={row.status} /></Td>
                        <Td><span className="text-xs text-neutral-500">{relativeTime(row.created_at)}</span></Td>
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
                    <span className="shrink-0 rounded bg-white/10 px-2 py-0.5 text-[10px] text-neutral-300">{ev.agent_name || 'System'}</span>
                    <span className="shrink-0 rounded bg-white/5 px-2 py-0.5 text-[10px] uppercase tracking-wider text-neutral-400">{ev.event_type}</span>
                    <span className="min-w-0 flex-1 break-words text-neutral-200">{eventMessage(ev.payload) || '—'}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* ============================= SETTINGS ============================= */}
        {activeTab === 'settings' && (
          <div className={`${cardCls} p-6`}>
            <h2 className="text-lg font-medium tracking-tight">Project Settings & Details</h2>
            <p className="mb-5 text-xs text-neutral-500">Project metadata and execution parameters.</p>
            <div className="divide-y divide-white/5">
              {[
                { label: 'Project name', value: project.name },
                { label: 'Specification', value: spec ? spec.title || specFormat(rawSpec) : 'None uploaded' },
                { label: 'Status', value: project.status },
                { label: 'Project ID', value: project.id, mono: true },
                { label: 'Organization ID', value: project.organization_id, mono: true },
                { label: 'Endpoints discovered', value: String(project.endpoint_count) },
                { label: 'Created', value: new Date(project.created_at).toLocaleString() },
                { label: 'Updated', value: new Date(project.updated_at).toLocaleString() },
              ].map(row => (
                <div key={row.label} className="flex flex-wrap items-center justify-between gap-2 py-3">
                  <span className="text-sm text-neutral-500">{row.label}</span>
                  <span className={`text-sm capitalize ${row.mono ? 'font-mono text-xs text-neutral-300' : ''}`}>
                    {row.value}
                    {row.mono && (
                      <button
                        onClick={() => navigator.clipboard.writeText(row.value)}
                        className="ml-2 inline-flex rounded p-1 text-neutral-500 hover:bg-white/5 hover:text-white"
                        title="Copy"
                      >
                        <Copy className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </span>
                </div>
              ))}
            </div>
            <div className="mt-6 flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.02] p-4">
              <GitBranch className="h-4 w-4 shrink-0 text-neutral-500" />
              <p className="text-xs text-neutral-500">
                Retry policy, target languages, and workflow triggers are configured when a run is triggered from the
                Build step. Short ID <span className="font-mono">{shortId(project.id)}</span>.
              </p>
            </div>
          </div>
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
