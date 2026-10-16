import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { asUuid } from '../lib/ids';
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Boxes,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  Download,
  FileCode2,
  FlaskConical,
  GitBranch,
  History,
  Link2,
  Loader2,
  Network,
  Package,
  Play,
  RefreshCw,
  RotateCcw,
  Settings as SettingsIcon,
  ShieldAlert,
  Sparkles,
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
import { IngestTab, UploadMode, UploadPhase } from './workspace/IngestTab';
import { DependenciesTab, MethodChip } from './workspace/DependenciesTab';
import { McpToolsTab } from './workspace/McpToolsTab';
import { VerifyTab } from './workspace/VerifyTab';
import { LiveTestModal } from './workspace/LiveTestModal';
import { McpResultTab } from './workspace/McpResultTab';
import { PipelineCanvas } from './workspace/PipelineCanvas';
import { TelemetryDock } from './workspace/TelemetryDock';
import { WeaverAgentDrawer, WeaverWorkspaceContext } from '../components/WeaverAgentDrawer';

type TabId = 'ingest' | 'dependencies' | 'tools' | 'verify' | 'result' | 'logs' | 'settings';

const errorMessage = (error: unknown) => (error instanceof Error ? error.message : 'Something went wrong.');

const sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));

// A test run that has stopped moving: polling ends and the panel reports its outcome.
const TERMINAL_TEST_STATUSES = ['completed', 'completed_with_failures', 'failed'];
// An export row still waiting on the pipeline; anything else has a real status.
const OPEN_EXPORT_STATUSES = ['queued', 'pending', 'running'];

const DEFAULT_SPEC = 'openapi: 3.0.0\ninfo:\n  title: API Specification\n  version: 1.0.0\npaths: {}';

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

  /* --- workspace stage navigation --- */
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get('tab');

  const normalizedInitialTab: TabId = useMemo(() => {
    if (rawTab === 'upload' || rawTab === 'ingest') return 'ingest';
    if (rawTab === 'plan' || rawTab === 'dependencies') return 'dependencies';
    if (rawTab === 'build' || rawTab === 'tools') return 'tools';
    if (rawTab === 'test' || rawTab === 'verify') return 'verify';
    if (rawTab === 'export' || rawTab === 'result') return 'result';
    if (rawTab === 'logs') return 'logs';
    if (rawTab === 'settings') return 'settings';
    return 'ingest';
  }, [rawTab]);

  const [activeTab, setActiveTabState] = useState<TabId>(normalizedInitialTab);

  const setActiveTab = useCallback((tab: TabId) => {
    setActiveTabState(tab);
    setSearchParams(prev => {
      const next = new URLSearchParams(prev);
      next.set('tab', tab);
      return next;
    }, { replace: true });
  }, [setSearchParams]);
  const [autoFollow, setAutoFollow] = useState(true);

  /* --- Resizable Drawer Width --- */
  const [drawerWidth, setDrawerWidth] = useState<number>(() => {
    const saved = localStorage.getItem('aw_drawer_width');
    return saved ? Math.max(380, Math.min(1000, parseInt(saved, 10))) : 560;
  });
  const [isResizing, setIsResizing] = useState(false);

  const startResizing = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
  }, []);

  useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      const newWidth = window.innerWidth - e.clientX;
      const minW = 380;
      const maxW = Math.max(minW, Math.min(window.innerWidth * 0.75, 1050));
      const clamped = Math.max(minW, Math.min(maxW, newWidth));
      setDrawerWidth(clamped);
    };

    const handleMouseUp = () => {
      setIsResizing(false);
      localStorage.setItem('aw_drawer_width', String(drawerWidth));
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing, drawerWidth]);

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
  const [liveModalOpen, setLiveModalOpen] = useState(false);

  /* --- export tab --- */
  const [exportBusy, setExportBusy] = useState<string | null>(null);
  const [exportNote, setExportNote] = useState('');
  const [exportError, setExportError] = useState('');

  /* --- logs tab --- */
  const [logQuery, setLogQuery] = useState('');
  const [logAgent, setLogAgent] = useState('all');
  const [logType, setLogType] = useState('all');

  /* --- Weaver AI Agent State --- */
  const [weaverOpen, setWeaverOpen] = useState(false);
  const [weaverQuery, setWeaverQuery] = useState<string | null>(null);
  const [weaverContextOverride, setWeaverContextOverride] = useState<Partial<WeaverWorkspaceContext>>({});
  const [externalFileUpdate, setExternalFileUpdate] = useState<{ file: string; content: string; timestamp: number } | null>(null);

  // Global keyboard shortcut: Ctrl+K / Cmd+K to toggle Weaver Agent Drawer
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setWeaverQuery(null);
        setWeaverOpen(prev => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const currentWeaverContext = useMemo<WeaverWorkspaceContext>(() => {
    const stageNameMap: Record<TabId, string> = {
      ingest: 'Stage 01 - API Ingestion & Spec Normalization',
      dependencies: 'Stage 02 - Topological Dependency Graph',
      tools: 'Stage 03 - FastMCP Synthesizer',
      verify: 'Stage 04 - Sandbox & Live Verification',
      result: 'Stage 05 - Artifact Bundles & MCP Manifest',
      logs: 'Audit & Event Logs',
      settings: 'Project Settings',
    };

    return {
      currentStage: stageNameMap[activeTab] || 'Workspace',
      selectedFile: activeTab === 'tools' ? 'tools.py' : activeTab === 'ingest' ? 'spec.yaml' : null,
      selectedEndpoint: endpoints.length > 0 ? endpoints[0].path : null,
      errorMessage: error || uploadError || planError || buildError || testError || exportError || null,
      ...weaverContextOverride,
    };
  }, [activeTab, endpoints, error, uploadError, planError, buildError, testError, exportError, weaverContextOverride]);

  const handleAskWeaver = useCallback((query: string, ctx?: Partial<WeaverWorkspaceContext>) => {
    if (ctx) {
      setWeaverContextOverride(ctx);
    }
    setWeaverQuery(query);
    setWeaverOpen(true);
  }, []);

  const handleApplyWeaverCode = useCallback((filePath: string, newContent: string) => {
    const fileName = filePath.split('/').pop() || filePath;
    if (id) {
      localStorage.setItem(`aw_mcp_edit_${id}_${fileName}`, newContent);
    }
    if (fileName.includes('spec')) {
      setSpecContent(newContent);
    }
    setExternalFileUpdate({ file: fileName, content: newContent, timestamp: Date.now() });
  }, [id]);

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

    if (autoFollow) {
      if (isPaused) {
        setActiveTab('dependencies');
      } else if (payload.current_node) {
        const node = String(payload.current_node);
        if (node === 'doc_agent') setActiveTab('ingest');
        else if (node === 'planner_agent' || node === 'approval_gate') setActiveTab('dependencies');
        else if (node === 'code_agent') setActiveTab('tools');
        else if (node === 'test_agent' || node === 'repair_agent') setActiveTab('verify');
        else if (node === 'export_agent') setActiveTab('result');
      }
    }

    if (isPaused) {
      loadProjectData();
    }
  }, [runEvents, activeRunId, loadProjectData, autoFollow, setActiveTab]);

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

  /* Resume watching a run that is still in flight when the tools tab opens. */
  useEffect(() => {
    if (activeTab !== 'tools' || activeRunId || !latestRun) return;
    if (['queued', 'running', 'paused_for_approval'].includes(latestRun.status)) {
      setActiveRunId(latestRun.workflow_run_id);
    }
  }, [activeTab, activeRunId, latestRun]);

  /* Load the dependency graph when the Dependencies tab opens, once per project. */
  useEffect(() => {
    if (activeTab === 'dependencies' && id && graphFetchedFor.current !== id) {
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

  /* Refresh test summary when Verify tab opens if missing */
  useEffect(() => {
    if (activeTab === 'verify' && id && !testSummary) {
      apiFetch<TestRunSummary>(`/projects/${id}/test-runs/latest`)
        .then(ts => { if (ts) setTestSummary(ts); })
        .catch(err => {
          console.warn('Could not fetch latest test summary', err);
        });
    }
  }, [activeTab, id, testSummary]);

  const stepCompleted = useMemo<Record<TabId, boolean>>(() => {
    const ingestDone = spec !== null;
    const depsDone = ingestDone && Boolean(graph && graph.nodes.length > 0);
    const toolsDone = Boolean(activeRun?.status === 'completed' || project?.last_run_status === 'completed');
    const verifyDone = Boolean(testSummary && (testSummary.summary.total ?? 0) > 0);
    const resultDone = Boolean(exports.some(e => e.status === 'completed'));
    return {
      ingest: ingestDone,
      dependencies: depsDone,
      tools: toolsDone,
      verify: verifyDone,
      result: resultDone,
      logs: false,
      settings: false,
    };
  }, [spec, graph, activeRun, project, testSummary, exports]);

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

  const hasDestructiveEndpoints = useMemo(() => {
    return endpoints.some(ep => {
      const m = ep.method.toUpperCase();
      return m === 'DELETE' || m === 'POST' || m === 'PUT' || m === 'PATCH';
    });
  }, [endpoints]);

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

  const handleLiveTestSubmit = async (params: { baseUrl: string; authType: string; headerName: string; secretValue: string }) => {
    if (!id) return;
    setLiveModalOpen(false);
    setTestBusy(true);
    setTestError('');
    setTestSummary(null);
    try {
      if (params.authType !== 'none' && params.secretValue) {
        let scheme = 'none';
        const credentials: Record<string, string> = {};
        const configJson: Record<string, string> = { base_url: params.baseUrl };
        if (params.authType === 'bearer') {
          scheme = 'bearer';
          credentials.token = params.secretValue;
        } else if (params.authType === 'apikey') {
          scheme = 'api_key';
          configJson.header_name = params.headerName || 'X-API-Key';
          credentials.api_key = params.secretValue;
        } else if (params.authType === 'basic') {
          scheme = 'basic';
          credentials.username = 'api';
          credentials.password = params.secretValue;
        }
        await apiFetch(`/projects/${id}/auth`, {
          method: 'PUT',
          body: JSON.stringify({ scheme, config_json: configJson, credentials }),
        }).catch(() => {
          // If auth saving fails (e.g. Vault not running in local dev), proceed with testing
        });
      }

      const trigger = await apiFetch<TestRunTriggerResponse>(`/projects/${id}/test`, {
        method: 'POST',
        body: JSON.stringify({ environment: 'live' }),
      });
      let summary: TestRunSummary | null = null;
      for (let attempt = 0; attempt < 25; attempt += 1) {
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
        if (!cancelled) {
          try {
            const parsed = JSON.parse(text);
            setFilePreview(JSON.stringify(parsed, null, 2));
          } catch {
            setFilePreview(text);
          }
        }
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
    <div className="h-screen bg-[#070709] text-white flex flex-col selection:bg-white selection:text-black overflow-hidden">
      {/* Top Command Header */}
      <header className="h-14 border-b border-white/10 bg-[#0a0a0f] px-4 flex items-center justify-between shrink-0 z-30">
        <div className="flex items-center gap-3">
          <Link
            to="/dashboard"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/10 text-neutral-400 hover:bg-white/5 hover:text-white transition-colors"
            title="Back to projects"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg border border-emerald-500/30 bg-emerald-500/15 font-mono text-xs font-bold text-emerald-400">
              AW
            </div>
            <div className="flex items-center gap-2 text-sm">
              <Link to="/dashboard" className="text-neutral-500 hover:text-white transition-colors">
                Projects
              </Link>
              <span className="text-neutral-600">/</span>
              <span className="font-medium text-white">{project.name}</span>
            </div>
          </div>
          <span className="px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-[11px] font-mono text-neutral-400">
            {project.endpoint_count} endpoint{project.endpoint_count === 1 ? '' : 's'}
          </span>
          {/* Dynamic Global Pipeline Status Pill */}
          {activeRun && ['queued', 'running', 'paused_for_approval'].includes(activeRun.status) ? (
            <span className="px-2.5 py-0.5 rounded-full bg-amber-500/10 text-[11px] font-medium text-amber-400 border border-amber-500/30 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
              <span>
                {activeRun.status === 'paused_for_approval'
                  ? 'Paused for Approval'
                  : `Running: ${activeAgentName} (${activeRun.progress_percent || 0}%)`}
              </span>
            </span>
          ) : stepCompleted.result && testSummary && testSummary.summary.failed === 0 ? (
            <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-[11px] font-medium text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              <span>All 5 Stages Verified</span>
            </span>
          ) : spec ? (
            <span className="px-2.5 py-0.5 rounded-full bg-blue-500/10 text-[11px] font-medium text-blue-400 border border-blue-500/30 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
              <span>Spec Ready</span>
            </span>
          ) : (
            <span className="px-2.5 py-0.5 rounded-full bg-neutral-800 text-[11px] font-medium text-neutral-400 border border-white/10 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-neutral-500" />
              <span>Standby (Needs Ingest)</span>
            </span>
          )}
        </div>

        {/* Right Controls */}
        <div className="flex items-center gap-3">
          {/* Auto-Follow Stream Toggle */}
          <label className="flex items-center gap-2 text-xs text-neutral-400 cursor-pointer hover:text-neutral-200 transition-colors">
            <input
              type="checkbox"
              checked={autoFollow}
              onChange={e => setAutoFollow(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-white/20 bg-white/5 text-emerald-500 focus:ring-0"
            />
            <span>Auto-Follow Stream</span>
          </label>

          {/* Weaver AI Engineering Agent Button */}
          <button
            type="button"
            onClick={() => {
              setWeaverQuery(null);
              setWeaverOpen(prev => !prev);
            }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border font-medium transition-all ${
              weaverOpen
                ? 'bg-purple-600/30 text-purple-200 border-purple-500/50 shadow-[0_0_12px_rgba(168,85,247,0.35)]'
                : 'bg-purple-500/10 hover:bg-purple-500/20 text-purple-300 border-purple-500/30'
            }`}
            title="Open Weaver AI Engineering Agent (Ctrl+K)"
          >
            <Sparkles className="h-3.5 w-3.5 text-purple-400" />
            <span>✦ Weaver</span>
            <kbd className="hidden sm:inline-block px-1 py-0.2 rounded bg-black/40 border border-purple-500/30 text-[10px] text-purple-300 font-mono">
              ⌘K
            </kbd>
          </button>

          {/* Trigger Live Weave button */}
          <button
            onClick={runBuild}
            disabled={cancelBusy || runIsLive}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-black font-semibold text-xs transition-colors shadow-sm disabled:opacity-50"
            title="Trigger full multi-agent weave pipeline"
          >
            <Play className="h-3.5 w-3.5 fill-current" />
            <span>{runIsLive ? 'Weaving...' : 'Trigger Live Weave'}</span>
          </button>

          {/* Get Claude Config button */}
          <button
            onClick={() => setActiveTab('result')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border transition-colors ${
              activeTab === 'result'
                ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300'
                : 'bg-white/5 hover:bg-white/10 text-neutral-300 border-white/10'
            }`}
          >
            <Package className="h-3.5 w-3.5" />
            <span>Get Claude Config</span>
          </button>

          {/* Settings button */}
          <button
            onClick={() => setActiveTab('settings')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border transition-colors ${
              activeTab === 'settings'
                ? 'bg-white/15 border-white/30 text-white'
                : 'bg-white/5 hover:bg-white/10 text-neutral-400 hover:text-neutral-200 border-white/10'
            }`}
            title="Project Settings"
          >
            <SettingsIcon className="h-3.5 w-3.5" />
            <span>Settings</span>
          </button>

          {/* Options Menu & Cancel */}
          {activeRun && ['queued', 'running', 'paused_for_approval'].includes(activeRun.status) && (
            <button
              type="button"
              onClick={cancelWorkflow}
              disabled={cancelBusy}
              className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 bg-red-500/10 px-2.5 py-1 text-xs font-medium text-red-400 hover:bg-red-500/20 disabled:opacity-50 transition-colors"
              title="Cancel active workflow immediately"
            >
              <XCircle className="h-3.5 w-3.5" />
              <span>{cancelBusy ? 'Cancelling...' : 'Cancel'}</span>
            </button>
          )}

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
      </header>

      {error && (
        <div className="mx-auto w-full px-4 pt-2">
          <ErrorBanner message={error} onDismiss={() => setError('')} />
        </div>
      )}

      {/* Main Workspace: Left Dot-Grid Canvas + Right Contextual Inspector Studio */}
      <main className={`flex-1 flex overflow-hidden relative ${isResizing ? 'select-none' : ''}`}>
        {/* Left Pane: Interactive Dot-Grid Pipeline Canvas */}
        <PipelineCanvas
          activeTab={activeTab}
          onSelectTab={setActiveTab}
          spec={spec}
          endpoints={endpoints}
          graph={graph}
          testSummary={testSummary}
          exports={exports}
          activeRun={activeRun}
          project={project}
          stepCompleted={stepCompleted}
        />

        {/* Vertical Draggable Resize Handle / Divider */}
        <div
          onMouseDown={startResizing}
          className={`group relative z-30 flex w-2.5 cursor-col-resize shrink-0 items-center justify-center select-none transition-colors ${
            isResizing ? 'bg-emerald-500/25' : 'bg-transparent hover:bg-emerald-500/15'
          }`}
          title="Drag to resize inspector studio"
        >
          {/* Vertical divider border line */}
          <div
            className={`h-full w-px transition-colors ${
              isResizing ? 'bg-emerald-400' : 'bg-white/10 group-hover:bg-emerald-400/80'
            }`}
          />
          {/* Draggable grip indicator dots */}
          <div
            className={`absolute flex h-8 w-1 flex-col items-center justify-center gap-1 rounded-full transition-opacity ${
              isResizing ? 'bg-emerald-400 opacity-100' : 'bg-neutral-500 opacity-0 group-hover:opacity-100'
            }`}
          >
            <span className="h-0.5 w-0.5 rounded-full bg-white" />
            <span className="h-0.5 w-0.5 rounded-full bg-white" />
          </div>
        </div>

        {/* Right Pane: Contextual Inspector Workbench + Persistent Telemetry Dock */}
        <aside
          style={{ width: `${drawerWidth}px` }}
          className="border-l border-white/10 bg-[#0c0d12] flex flex-col shrink-0 z-20 transition-[width] duration-75"
        >
          {/* Top Workbench Area */}
          <div className={`flex-1 min-h-0 flex flex-col ${['ingest', 'dependencies', 'tools'].includes(activeTab) ? 'overflow-hidden' : 'overflow-y-auto p-5'}`}>
            {activeTab === 'ingest' && (
              <IngestTab
                file={file}
                setFile={setFile}
                setFilePreview={setFilePreview}
                mode={mode}
                setMode={setMode}
                specContent={specContent}
                setSpecContent={setSpecContent}
                urlValue={urlValue}
                setUrlValue={setUrlValue}
                urlNote={urlNote}
                phase={phase}
                setPhase={setPhase}
                uploadError={uploadError}
                uploadedMeta={uploadedMeta}
                uploadResult={uploadResult}
                spec={spec}
                endpoints={endpoints}
                showAnalysis={showAnalysis}
                editorValue={editorValue}
                language={language}
                hasValidInput={hasValidInput}
                onUrlImport={handleUrlImport}
                onUpload={handleUpload}
                onReset={resetUpload}
                onContinue={() => setActiveTab('dependencies')}
                onPreviewExpand={() => setPreviewExpanded(true)}
              />
            )}

            {activeTab === 'dependencies' && (
              <DependenciesTab
                graph={graph}
                resourceGroups={resourceGroups}
                spec={spec}
                endpoints={endpoints}
                planBusy={planBusy}
                planApproved={planApproved}
                planError={planError}
                pausedRunId={pausedRunId}
                onApprovePlan={approvePlan}
                onViewPlanDoc={() => setPlanDocOpen(true)}
                onGoToIngest={() => setActiveTab('ingest')}
                onContinueToTools={() => setActiveTab('tools')}
                onDismissError={() => setPlanError('')}
              />
            )}

            {activeTab === 'tools' && (
              <McpToolsTab
                projectId={id || ''}
                project={project}
                spec={spec}
                endpoints={endpoints}
                activeRun={activeRun}
                runIsLive={runIsLive}
                onRunBuild={runBuild}
                onContinueToVerify={() => setActiveTab('verify')}
                onGoToIngest={() => setActiveTab('ingest')}
                onAskWeaver={handleAskWeaver}
                externalFileUpdate={externalFileUpdate}
              />
            )}

            {activeTab === 'verify' && (
              <VerifyTab
                testEnv={testEnv}
                setTestEnv={setTestEnv}
                testBusy={testBusy}
                onRunTests={runTests}
                onOpenLiveModal={() => setLiveModalOpen(true)}
                endpoints={endpoints}
                testSummary={testSummary}
                testTotal={testTotal}
                successRate={successRate}
                endpointById={endpointById}
                testError={testError}
                onDismissTestError={() => setTestError('')}
                liveThoughts={liveThoughts}
                runIsLive={runIsLive}
                activeAgentName={activeAgentName}
                autoScroll={autoScroll}
                setAutoScroll={setAutoScroll}
                onClearThoughts={() => setLiveThoughts([])}
                terminalEndRef={terminalEndRef}
                onContinueToResult={() => setActiveTab('result')}
              />
            )}

            {activeTab === 'result' && (
              <McpResultTab
                projectId={id || ''}
                project={project}
                spec={spec}
                endpoints={endpoints}
                testSummary={testSummary}
                exports={exports}
                exportBusy={exportBusy}
                exportError={exportError}
                exportNote={exportNote}
                onDismissExportError={() => setExportError('')}
                onTriggerExport={triggerExport}
                onDownloadExport={handleDownloadExport}
                onGoToVerify={() => setActiveTab('verify')}
              />
            )}

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

            {activeTab === 'settings' && (
              <SettingsTab
                project={project}
                spec={spec}
                rawSpec={rawSpec}
              />
            )}
          </div>

          {/* Bottom Persistent Telemetry Dock */}
          <TelemetryDock
            liveThoughts={liveThoughts}
            autoScroll={autoScroll}
            setAutoScroll={setAutoScroll}
            onClear={() => setLiveThoughts([])}
            terminalEndRef={terminalEndRef}
            isLive={runIsLive}
          />
        </aside>
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

      {/* Live test credentials modal */}
      <LiveTestModal
        isOpen={liveModalOpen}
        onClose={() => setLiveModalOpen(false)}
        onSubmit={handleLiveTestSubmit}
        hasDestructiveEndpoints={hasDestructiveEndpoints}
        busy={testBusy}
      />

      {/* Weaver AI Engineering Agent Drawer */}
      <WeaverAgentDrawer
        isOpen={weaverOpen}
        onClose={() => setWeaverOpen(false)}
        projectId={id || ''}
        projectName={project.name}
        context={currentWeaverContext}
        initialQuery={weaverQuery}
        onApplyCode={handleApplyWeaverCode}
      />
    </div>
  );
};
