import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  Clipboard,
  Copy,
  Download,
  FileCode2,
  FileJson,
  FileText,
  FileType,
  History,
  Link2,
  Loader2,
  Maximize2,
  PlayCircle,
  RotateCcw,
  Settings as SettingsIcon,
  Terminal as TerminalIcon,
  Upload,
  GitBranch,
  Cpu,
} from 'lucide-react';
import Editor from '@monaco-editor/react';
import { apiFetch } from '../lib/api';
import { ApiSpec, HistoryItem, Page, ProjectSummary, SpecEndpoint, UploadResponse, WorkflowEvent } from '../lib/types';
import { NormalizedSpec, relativeTime, shortId, specFormat, validationState } from '../lib/format';
import {
  btnGhost,
  btnPrimary,
  cardCls,
  ErrorBanner,
  inputCls,
  Modal,
  OptionsMenu,
  StatusBadge,
} from '../components/ui';

type TabId = 'upload' | 'plan' | 'build' | 'test' | 'export' | 'logs' | 'settings';
type UploadMode = 'file' | 'paste' | 'url';
type UploadPhase = 'idle' | 'working' | 'success' | 'error';

const errorMessage = (error: unknown) => (error instanceof Error ? error.message : 'Something went wrong.');

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

/* Main page ------------------------------------------------------------------- */

export const ProjectWorkspace: React.FC = () => {
  const { id } = useParams<{ id: string }>();

  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [spec, setSpec] = useState<ApiSpec | null>(null);
  const [endpoints, setEndpoints] = useState<SpecEndpoint[]>([]);
  const [latestRun, setLatestRun] = useState<HistoryItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

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

  const [dagPlan, setDagPlan] = useState('1. Parse OpenAPI schema & extract models\n2. Generate FastAPI routers & Pydantic validation\n3. Initialize Celery background tasks & storage service\n4. Execute self-healing test suite');
  const [planApproved, setPlanApproved] = useState(false);
  const [events, setEvents] = useState<WorkflowEvent[]>([
    { id: '1', timestamp: new Date().toLocaleTimeString(), level: 'info', message: 'Initialized agent execution environment.', agent: 'System' },
  ]);
  const [building, setBuilding] = useState(false);
  const testResults = [
    { endpoint: '/api/v1/health', method: 'GET', status: 200, latency: '12ms', passed: true },
    { endpoint: '/api/v1/projects', method: 'POST', status: 201, latency: '45ms', passed: true },
  ];

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

      const [specRes, endpointsRes] = await Promise.all([
        apiFetch<ApiSpec>(`/projects/${id}/spec`).catch(() => null),
        apiFetch<SpecEndpoint[]>(`/projects/${id}/endpoints`).catch(() => [] as SpecEndpoint[]),
      ]);
      setSpec(specRes);
      setEndpoints(Array.isArray(endpointsRes) ? endpointsRes : []);
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
      setEvents(prev => [
        {
          id: String(Date.now()),
          timestamp: new Date().toLocaleTimeString(),
          level: 'success',
          message: `Specification ingested (${result.endpoints_discovered ?? 0} endpoints discovered).`,
          agent: 'IngestionAgent',
        },
        ...prev,
      ]);
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
            <div className="min-w-0">
              <h1 className="truncate text-xl font-semibold tracking-tight">{project.name}</h1>
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
        {activeTab === 'upload' && (
          <div className="space-y-6">
            {/* Mode selector */}
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

            {/* Two-column workspace */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
              {/* Left: input */}
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

                {/* Upload states */}
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

              {/* Right: preview */}
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

            {/* Analysis */}
            {showAnalysis && <AnalysisPanel spec={spec} endpoints={endpoints} />}

            {/* What happens next */}
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

            {/* Bottom actions */}
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

        {activeTab === 'plan' && (
          <div className={`${cardCls} p-6`}>
            <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-medium tracking-tight">Topological DAG Execution Plan</h2>
                <p className="text-xs text-neutral-500">Review generated dependency graph and approve execution schedule.</p>
              </div>
              <button
                onClick={() => setPlanApproved(true)}
                className={`flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-medium transition-colors ${
                  planApproved ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30' : btnPrimary
                }`}
              >
                {planApproved ? <><Check className="h-4 w-4" /> Plan Approved</> : 'Approve Execution Plan'}
              </button>
            </div>
            <div className="h-[350px] overflow-hidden rounded-xl border border-white/15">
              <Editor
                height="100%"
                defaultLanguage="markdown"
                theme="vs-dark"
                value={dagPlan}
                onChange={val => setDagPlan(val || '')}
                options={{ minimap: { enabled: false }, fontSize: 13 }}
              />
            </div>
          </div>
        )}

        {activeTab === 'build' && (
          <div className={`${cardCls} p-6`}>
            <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-medium tracking-tight">Agent Build & Execution</h2>
                <p className="text-xs text-neutral-500">Monitor autonomous code generation and model compilation.</p>
              </div>
              <button onClick={() => setBuilding(true)} disabled={building} className={btnPrimary}>
                <PlayCircle className="h-4 w-4" />
                {building ? 'Executing Agents…' : 'Run Build Pipeline'}
              </button>
            </div>
            <div className="space-y-3">
              {[
                { icon: Cpu, title: 'FastAPI Pydantic Generator Agent', desc: 'Generates type-safe routers, models, and validation schemas.', badge: 'Completed', badgeStatus: 'completed' },
                { icon: TerminalIcon, title: 'Celery Worker & Storage Service Agent', desc: 'Configures asynchronous task queues and SQLite/PostgreSQL storage.', badge: 'Ready', badgeStatus: 'queued' },
              ].map(agent => {
                const Icon = agent.icon;
                return (
                  <div key={agent.title} className={`${cardCls} flex items-center justify-between gap-4 p-4`}>
                    <div className="flex min-w-0 items-center gap-4">
                      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/5">
                        <Icon className="h-4 w-4" />
                      </span>
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium">{agent.title}</div>
                        <div className="truncate text-xs text-neutral-500">{agent.desc}</div>
                      </div>
                    </div>
                    <StatusBadge status={agent.badgeStatus} label={agent.badge} />
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {activeTab === 'test' && (
          <div className={`${cardCls} p-6`}>
            <h2 className="text-lg font-medium tracking-tight">Test Suite & Self-Healing Telemetry</h2>
            <p className="mb-5 text-xs text-neutral-500">Verify endpoint responses, status codes, and latency metrics.</p>
            <div className="space-y-3">
              {testResults.map(test => (
                <div key={`${test.method}${test.endpoint}`} className={`${cardCls} flex flex-wrap items-center justify-between gap-4 p-4`}>
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="rounded-lg bg-white/10 px-2 py-1 font-mono text-[11px] font-bold">{test.method}</span>
                    <span className="truncate font-mono text-sm text-neutral-200">{test.endpoint}</span>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="font-mono text-xs text-neutral-500">{test.latency}</span>
                    <StatusBadge status="completed" label={`${test.status} OK`} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeTab === 'export' && (
          <div className={`${cardCls} p-6`}>
            <h2 className="text-lg font-medium tracking-tight">Infrastructure Export Wizard</h2>
            <p className="mb-5 text-xs text-neutral-500">Export your generated workflows to production-ready targets.</p>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {[
                { title: 'Docker Compose Bundle', desc: 'Complete containerized deployment with FastAPI, Celery worker, Redis, and frontend Nginx.', cta: 'Download ZIP' },
                { title: 'FastAPI Python SDK', desc: 'Standalone Python client package with full Pydantic type hints and async support.', cta: 'Download SDK' },
              ].map(target => (
                <div key={target.title} className={`${cardCls} p-5 transition-colors hover:border-white/25`}>
                  <h3 className="mb-1 text-sm font-medium">{target.title}</h3>
                  <p className="mb-4 text-xs leading-relaxed text-neutral-500">{target.desc}</p>
                  <button className={btnGhost}>
                    <Download className="h-3.5 w-3.5" /> {target.cta}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeTab === 'logs' && (
          <div className={`${cardCls} p-6`}>
            <h2 className="text-lg font-medium tracking-tight">Real-Time Event Stream</h2>
            <p className="mb-5 text-xs text-neutral-500">Structured audit logs and agent telemetry events.</p>
            <div className="h-[400px] overflow-y-auto rounded-xl border border-white/15 bg-neutral-950 p-4 font-mono text-xs">
              {events.map(ev => (
                <div key={ev.id} className="flex items-start gap-4 border-b border-white/5 pb-3">
                  <span className="shrink-0 text-neutral-500">[{ev.timestamp}]</span>
                  <span className="shrink-0 rounded bg-white/10 px-2 py-0.5 text-[10px] uppercase text-neutral-300">{ev.agent || 'Agent'}</span>
                  <span className="text-neutral-200">{ev.message}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeTab === 'settings' && (
          <div className={`${cardCls} p-6`}>
            <h2 className="text-lg font-medium tracking-tight">Project Settings & Details</h2>
            <p className="mb-5 text-xs text-neutral-500">Project metadata and execution parameters.</p>
            <div className="divide-y divide-white/5">
              {[
                { label: 'Project name', value: project.name },
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
    </div>
  );
};
