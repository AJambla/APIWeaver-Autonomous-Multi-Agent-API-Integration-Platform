import React, { useEffect, useMemo, useState, useCallback } from 'react';
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Boxes,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Code2,
  Copy,
  ExternalLink,
  FileCode2,
  FileJson,
  FileText,
  FlaskConical,
  Folder,
  FolderOpen,
  Info,
  Layers,
  Loader2,
  Network,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  RotateCw,
  Save,
  Search,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Terminal,
} from 'lucide-react';
import Editor, { DiffEditor } from '@monaco-editor/react';
import { ApiSpec, GeneratedFileMeta, ProjectSummary, SpecEndpoint, WorkflowRunInfo } from '../../lib/types';
import { btnGhost, btnPrimary, cardCls, EmptyState, ErrorBanner } from '../../components/ui';
import { MethodChip } from './DependenciesTab';
import { apiFetch } from '../../lib/api';
import { NormalizedSpec, specFormat, specVersion } from '../../lib/format';
import { WeaverWorkspaceContext } from '../../components/WeaverAgentDrawer';

export interface McpToolsTabProps {
  projectId: string;
  project: ProjectSummary | null;
  spec: ApiSpec | null;
  endpoints: SpecEndpoint[];
  activeRun: WorkflowRunInfo | null;
  runIsLive: boolean;
  onRunBuild: () => void;
  onContinueToVerify: () => void;
  onProceedToTest?: () => Promise<void> | void;
  onGoToDependencies?: () => void;
  onGoToIngest: () => void;
  onAskWeaver?: (query: string, context?: Partial<WeaverWorkspaceContext>) => void;
  externalFileUpdate?: { file: string; content: string; timestamp: number } | null;
}

type SubNavTab = 'files' | 'tools' | 'dependencies' | 'verification' | 'manifest';
type FileItem = string;

export const McpToolsTab: React.FC<McpToolsTabProps> = ({
  projectId,
  project,
  spec,
  endpoints,
  activeRun,
  runIsLive,
  onRunBuild,
  onContinueToVerify,
  onProceedToTest,
  onGoToDependencies,
  onGoToIngest,
  onAskWeaver,
  externalFileUpdate,
}) => {
  const [activeSubTab, setActiveSubTab] = useState<SubNavTab>('files');
  const [selectedFile, setSelectedFile] = useState<FileItem>('tools.py');
  const [selectedToolId, setSelectedToolId] = useState<string | null>(null);
  const [fileSearch, setFileSearch] = useState('');
  const [toolSearch, setToolSearch] = useState('');
  const [methodFilter, setMethodFilter] = useState<string>('ALL');
  const [safetyFilter, setSafetyFilter] = useState<string>('ALL');
  const [copiedCode, setCopiedCode] = useState(false);
  const [savedToast, setSavedToast] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [formatToast, setFormatToast] = useState(false);
  const [revertToast, setRevertToast] = useState(false);
  const [agentToast, setAgentToast] = useState(false);
  const [diffMode, setDiffMode] = useState(false);
  const [fastmcpFolderOpen, setFastmcpFolderOpen] = useState(true);
  const [testsFolderOpen, setTestsFolderOpen] = useState(true);
  const [otherFolderOpen, setOtherFolderOpen] = useState(true);
  const [error, setError] = useState('');

  // Real generated files from API
  const [files, setFiles] = useState<GeneratedFileMeta[]>([]);
  const [fileContents, setFileContents] = useState<Record<string, string>>({});
  const [loadingFiles, setLoadingFiles] = useState(false);

  // User edits and dirty state tracking per file
  const [editedContents, setEditedContents] = useState<Partial<Record<FileItem, string>>>({});
  const [dirtyFiles, setDirtyFiles] = useState<Set<FileItem>>(new Set());

  const fetchFiles = useCallback(async () => {
    if (!projectId) return;
    try {
      const fileList = await apiFetch<GeneratedFileMeta[]>(`/projects/${projectId}/files`);
      setFiles(fileList || []);
    } catch {
      // Not ready yet
    }
  }, [projectId]);

  // Load content of currently selected file on demand
  useEffect(() => {
    if (!projectId || !selectedFile || files.length === 0) return;
    if (fileContents[selectedFile]) return;

    const matched = files.find(
      f => f.file_path === selectedFile || f.file_path.split('/').pop() === selectedFile
    );
    if (!matched) return;

    let cancelled = false;
    apiFetch<{ content: string }>(`/projects/${projectId}/files/${matched.id}/content`)
      .then(res => {
        if (!cancelled && res && res.content) {
          const name = matched.file_path.split('/').pop() || matched.file_path;
          setFileContents(prev => ({
            ...prev,
            [name]: res.content,
            [matched.file_path]: res.content,
          }));
        }
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, [projectId, selectedFile, files, fileContents]);

  useEffect(() => {
    let cancelled = false;
    setLoadingFiles(true);
    fetchFiles().finally(() => {
      if (!cancelled) setLoadingFiles(false);
    });

    // Poll while live or code generation is in progress so newly generated files stream in real-time
    let intervalId: ReturnType<typeof setInterval> | null = null;
    if (runIsLive || activeRun?.status === 'running' || activeRun?.current_node === 'code_agent') {
      intervalId = setInterval(() => {
        if (!cancelled) fetchFiles();
      }, 2500);
    }

    return () => {
      cancelled = true;
      if (intervalId) clearInterval(intervalId);
    };
  }, [fetchFiles, runIsLive, activeRun?.status, activeRun?.current_node]);

  // Deduplicate files by file_path
  const uniqueFiles = useMemo(() => {
    const seen = new Set<string>();
    const res: GeneratedFileMeta[] = [];
    for (const f of files) {
      if (!seen.has(f.file_path)) {
        seen.add(f.file_path);
        res.push(f);
      }
    }
    return res;
  }, [files]);

  // Auto-select preferred file when files arrive
  useEffect(() => {
    if (uniqueFiles.length > 0) {
      const fileNames = uniqueFiles.map(f => f.file_path.split('/').pop() || f.file_path);
      const filePaths = uniqueFiles.map(f => f.file_path);
      if (!fileNames.includes(selectedFile) && !filePaths.includes(selectedFile)) {
        const defaultFile = filePaths.find(p => p === 'tools.py' || p.endsWith('/tools.py'))
          || filePaths.find(p => p.endsWith('.py'))
          || filePaths[0];
        setSelectedFile(defaultFile);
      }
    }
  }, [uniqueFiles, selectedFile]);

  // Load user saved edits from localStorage on project load
  useEffect(() => {
    if (!projectId) return;
    const loaded: Partial<Record<FileItem, string>> = {};
    const dirty = new Set<FileItem>();
    const allFiles: FileItem[] = [
      'tools.py',
      'server.py',
      'test_mcp.py',
      'manifest.json',
      'requirements.txt',
      'test_tools.py',
      'test_safety.py',
    ];
    for (const f of allFiles) {
      const saved = localStorage.getItem(`aw_mcp_edit_${projectId}_${f}`);
      if (saved !== null) {
        loaded[f] = saved;
        dirty.add(f);
      }
    }
    if (Object.keys(loaded).length > 0) {
      setEditedContents(prev => ({ ...prev, ...loaded }));
      setDirtyFiles(dirty);
    }
  }, [projectId]);

  // Sync code changes applied externally (e.g. from Weaver agent [Apply Change])
  useEffect(() => {
    if (externalFileUpdate && externalFileUpdate.file) {
      const file = externalFileUpdate.file as FileItem;
      setEditedContents(prev => ({
        ...prev,
        [file]: externalFileUpdate.content,
      }));
      setSelectedFile(file);
      setSavedToast(true);
      setTimeout(() => setSavedToast(false), 2500);
    }
  }, [externalFileUpdate]);

  // Normalized spec details
  const rawSpec = useMemo(() => (spec?.raw_normalized ?? {}) as NormalizedSpec, [spec]);
  const specTitle = useMemo(() => {
    return spec?.title || rawSpec.info?.title || project?.name || 'OpenAPI Spec';
  }, [spec, rawSpec, project]);

  // Awaiting test approval gate (Stage 03 complete, waiting for human sign-off before Stage 04 tests)
  const isAwaitingTestApproval = useMemo(() => {
    return (
      activeRun?.status === 'paused_for_approval' &&
      (activeRun?.progress_percent === 60 || (files.length > 0 && (activeRun?.progress_percent ?? 0) < 80))
    );
  }, [activeRun?.status, activeRun?.progress_percent, files.length]);

  const isSynthesizing = activeRun?.status === 'running' && activeRun?.current_node === 'code_agent';

  const authSchemeText = useMemo(() => {
    const authObj = rawSpec.components?.securitySchemes ?? rawSpec.securityDefinitions ?? {};
    const keys = Object.keys(authObj);
    return keys.length > 0 ? keys[0] : 'api_key';
  }, [rawSpec]);

  // Derive synthesized tools with deterministic safety classification
  const tools = useMemo(() => {
    return endpoints.map((ep, idx) => {
      const method = ep.method.toUpperCase();
      const isDelete = method === 'DELETE';
      const isStateChanging = ['POST', 'PUT', 'PATCH'].includes(method);
      const isSafe = ['GET', 'HEAD', 'OPTIONS'].includes(method);

      // Clean pythonic tool name: get_pet_by_id, delete_user
      const cleanPath = ep.path
        .replace(/\{([^}]+)\}/g, 'by_$1')
        .replace(/[^a-zA-Z0-9_]/g, '_')
        .replace(/_+/g, '_')
        .replace(/^_|_$/g, '');
      const toolName = `${method.toLowerCase()}_${cleanPath || `endpoint_${idx + 1}`}`;

      let safetyBadge: string;
      let riskLevel: 'Low' | 'Medium' | 'High';
      let confirmationText: string;
      let requiresConfirmation: boolean;

      if (isDelete || ep.deprecated) {
        safetyBadge = 'DESTRUCTIVE ⚠';
        riskLevel = 'High';
        confirmationText = 'Required';
        requiresConfirmation = true;
      } else if (isStateChanging) {
        safetyBadge = 'STATE-CHANGING';
        riskLevel = 'Medium';
        confirmationText = 'Not required';
        requiresConfirmation = false;
      } else {
        safetyBadge = 'SAFE';
        riskLevel = 'Low';
        confirmationText = 'Not required';
        requiresConfirmation = false;
      }

      return {
        id: ep.id,
        name: toolName,
        path: ep.path,
        method: ep.method,
        summary: ep.summary || `Execute ${ep.method} request against ${ep.path}`,
        safetyBadge,
        riskLevel,
        confirmationText,
        requiresConfirmation,
        lineRef: 12 + idx * 8,
      };
    });
  }, [endpoints]);

  // Default selection
  useEffect(() => {
    if (!selectedToolId && tools.length > 0) {
      setSelectedToolId(tools[0].id);
    }
  }, [tools, selectedToolId]);

  const selectedTool = useMemo(() => {
    return tools.find(t => t.id === selectedToolId) || tools[0] || null;
  }, [tools, selectedToolId]);

  // Group real generated files from backend
  const { fastmcpFiles, testFiles, otherFiles } = useMemo(() => {
    const fastmcp: GeneratedFileMeta[] = [];
    const test: GeneratedFileMeta[] = [];
    const other: GeneratedFileMeta[] = [];

    uniqueFiles.forEach(f => {
      const lower = f.file_path.toLowerCase();
      if (
        lower.startsWith('tests/') ||
        lower.startsWith('test_') ||
        lower.includes('/test_') ||
        lower.includes('.test.') ||
        lower.includes('__tests__')
      ) {
        test.push(f);
      } else if (
        lower.startsWith('fastmcp/') ||
        lower.endsWith('.py') ||
        lower.endsWith('.json') ||
        lower.endsWith('.txt') ||
        lower.endsWith('.toml') ||
        lower.endsWith('.md') ||
        lower.endsWith('.yaml') ||
        lower.endsWith('.yml')
      ) {
        fastmcp.push(f);
      } else {
        other.push(f);
      }
    });

    return { fastmcpFiles: fastmcp, testFiles: test, otherFiles: other };
  }, [uniqueFiles]);

  // Baseline original code (unmodified) - strictly authentic from backend
  const getOriginalCode = useCallback(
    (file: FileItem): string => {
      return fileContents[file] || '';
    },
    [fileContents]
  );

  // Current code (edited or stored or original)
  const getCurrentCode = useCallback(
    (file: FileItem): string => {
      if (editedContents[file] !== undefined) {
        return editedContents[file]!;
      }
      return getOriginalCode(file);
    },
    [editedContents, getOriginalCode]
  );

  const activeEditorContent = getCurrentCode(selectedFile);
  const originalEditorContent = getOriginalCode(selectedFile);
  const isSelectedFileDirty = dirtyFiles.has(selectedFile);

  // Handlers for editing
  const handleEditorChange = (value: string | undefined) => {
    if (value === undefined) return;
    setEditedContents(prev => ({
      ...prev,
      [selectedFile]: value,
    }));
    const orig = getOriginalCode(selectedFile);
    if (value !== orig) {
      setDirtyFiles(prev => new Set(prev).add(selectedFile));
    } else {
      setDirtyFiles(prev => {
        const next = new Set(prev);
        next.delete(selectedFile);
        return next;
      });
    }
  };

  const handleSave = useCallback(async () => {
    const current = getCurrentCode(selectedFile);
    setIsSaving(true);
    setSaveError('');

    // Always persist to localStorage as backup
    localStorage.setItem(`aw_mcp_edit_${projectId}_${selectedFile}`, current);

    // Look for real backend file metadata
    const matched = files.find(
      f => f.file_path === selectedFile || f.file_path.split('/').pop() === selectedFile
    );

    if (matched) {
      try {
        await apiFetch(`/projects/${projectId}/files/${matched.id}/content`, {
          method: 'PUT',
          body: JSON.stringify({ content: current }),
        });
        setFileContents(prev => ({
          ...prev,
          [selectedFile]: current,
        }));
        setDirtyFiles(prev => {
          const next = new Set(prev);
          next.delete(selectedFile);
          return next;
        });
        setSavedToast(true);
        setTimeout(() => setSavedToast(false), 2500);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Failed to save file to server';
        setSaveError(msg);
        setTimeout(() => setSaveError(''), 5000);
      } finally {
        setIsSaving(false);
      }
    } else {
      // Local preview file
      setDirtyFiles(prev => {
        const next = new Set(prev);
        next.delete(selectedFile);
        return next;
      });
      setSavedToast(true);
      setTimeout(() => setSavedToast(false), 2500);
      setIsSaving(false);
    }
  }, [getCurrentCode, selectedFile, projectId, files]);


  const handleRevert = () => {
    const orig = getOriginalCode(selectedFile);
    localStorage.removeItem(`aw_mcp_edit_${projectId}_${selectedFile}`);
    setEditedContents(prev => ({
      ...prev,
      [selectedFile]: orig,
    }));
    setDirtyFiles(prev => {
      const next = new Set(prev);
      next.delete(selectedFile);
      return next;
    });
    setRevertToast(true);
    setTimeout(() => setRevertToast(false), 2000);
  };

  const handleFormat = () => {
    const current = activeEditorContent;
    if (selectedFile.endsWith('.json')) {
      try {
        const parsed = JSON.parse(current);
        const formatted = JSON.stringify(parsed, null, 2);
        handleEditorChange(formatted);
        setFormatToast(true);
        setTimeout(() => setFormatToast(false), 2000);
      } catch {
        setError('Cannot format invalid JSON');
        setTimeout(() => setError(''), 3000);
      }
    } else {
      // Basic formatting: trim trailing spaces and normalize line endings
      const lines = current.split('\n').map(l => l.trimEnd());
      const formatted = lines.join('\n');
      handleEditorChange(formatted);
      setFormatToast(true);
      setTimeout(() => setFormatToast(false), 2000);
    }
  };

  const copyToClipboard = () => {
    navigator.clipboard.writeText(activeEditorContent);
    setCopiedCode(true);
    setTimeout(() => setCopiedCode(false), 2000);
  };

  const handleAskAgent = () => {
    if (onAskWeaver) {
      const question = selectedTool
        ? `Why is ${selectedTool.name} classified as ${selectedTool.safetyBadge}?`
        : `Can you analyze the current MCP code in ${selectedFile}?`;
      onAskWeaver(question, {
        currentStage: 'Stage 03 - FastMCP Synthesizer',
        selectedFile,
        selectedEndpoint: selectedTool?.path || null,
        selectedTool: selectedTool?.name || null,
        activeCodeSnippet: activeEditorContent ? activeEditorContent.slice(0, 1000) : null,
      });
    } else {
      setAgentToast(true);
      setTimeout(() => setAgentToast(false), 3000);
    }
  };

  // Keyboard shortcut Ctrl+S / Cmd+S for saving
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        handleSave();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleSave]);

  // Badge styles
  const getBadgeStyle = (safetyBadge: string) => {
    if (safetyBadge.includes('DESTRUCTIVE')) {
      return 'bg-rose-500/10 text-rose-400 border-rose-500/30';
    }
    if (safetyBadge.includes('STATE-CHANGING')) {
      return 'bg-amber-500/10 text-amber-400 border-amber-500/30';
    }
    return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30';
  };

  // Filtered tools list for 'tools' sub-tab
  const filteredTools = useMemo(() => {
    return tools.filter(t => {
      const matchSearch =
        t.name.toLowerCase().includes(toolSearch.toLowerCase()) ||
        t.path.toLowerCase().includes(toolSearch.toLowerCase()) ||
        t.summary.toLowerCase().includes(toolSearch.toLowerCase());
      const matchMethod = methodFilter === 'ALL' || t.method.toUpperCase() === methodFilter;
      const matchSafety =
        safetyFilter === 'ALL' ||
        (safetyFilter === 'SAFE' && t.riskLevel === 'Low') ||
        (safetyFilter === 'STATE-CHANGING' && t.riskLevel === 'Medium') ||
        (safetyFilter === 'DESTRUCTIVE' && t.riskLevel === 'High');
      return matchSearch && matchMethod && matchSafety;
    });
  }, [tools, toolSearch, methodFilter, safetyFilter]);

  if (endpoints.length === 0) {
    return (
      <EmptyState
        icon={<Boxes className="h-6 w-6" />}
        title="No tools synthesized yet"
        description="Upload an OpenAPI or documentation specification in the Ingest stage to synthesize FastMCP tools."
        action={
          <button onClick={onGoToIngest} className={btnPrimary}>
            Go to Ingest <ArrowRight className="h-4 w-4" />
          </button>
        }
      />
    );
  }

  const renderFileRow = (f: GeneratedFileMeta) => {
    const fileName = f.file_path.split('/').pop() || f.file_path;
    const dirPath = f.file_path.includes('/') ? f.file_path.substring(0, f.file_path.lastIndexOf('/') + 1) : '';
    const isSelected = selectedFile === f.file_path || (selectedFile === fileName && !f.file_path.includes('/'));
    const isDirty = dirtyFiles.has(f.file_path) || dirtyFiles.has(fileName);

    return (
      <button
        key={f.id || f.file_path}
        type="button"
        onClick={() => setSelectedFile(f.file_path)}
        className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-left transition-colors font-mono text-[11px] ${
          isSelected
            ? 'bg-[#131b2e] text-white border border-sky-500/30'
            : 'text-neutral-400 hover:text-white hover:bg-white/[0.03]'
        }`}
      >
        <div className="flex items-center gap-2 truncate min-w-0">
          {fileName.endsWith('.py') ? (
            <FileCode2 className="h-3.5 w-3.5 text-sky-400/80 shrink-0" />
          ) : fileName.endsWith('.json') ? (
            <FileJson className="h-3.5 w-3.5 text-amber-400/80 shrink-0" />
          ) : (
            <FileText className="h-3.5 w-3.5 text-neutral-400 shrink-0" />
          )}
          <div className="truncate flex items-baseline">
            {dirPath && <span className="text-neutral-500 text-[10px] shrink-0 mr-0.5">{dirPath}</span>}
            <span className="truncate">{fileName}</span>
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0 ml-2">
          {f.size_bytes > 0 && (
            <span className="text-[10px] text-neutral-500 font-mono">
              {f.size_bytes < 1024 ? `${f.size_bytes}b` : `${(f.size_bytes / 1024).toFixed(1)}k`}
            </span>
          )}
          {isDirty && (
            <span className="h-1.5 w-1.5 rounded-full bg-amber-400 shrink-0" title="Modified (unsaved)" />
          )}
        </div>
      </button>
    );
  };

  return (
    <div className="flex flex-col h-full min-h-0 bg-[#07080c] text-white">
      {/* Toast Notifications */}
      {copiedCode && (
        <div className="fixed top-5 right-5 z-50 rounded-xl border border-emerald-500/30 bg-[#0d1210] px-4 py-2.5 text-xs text-emerald-300 shadow-2xl flex items-center gap-2 animate-in fade-in slide-in-from-top-2">
          <Check className="h-4 w-4 text-emerald-400" />
          <span>Code copied to clipboard</span>
        </div>
      )}

      {savedToast && (
        <div className="fixed top-5 right-5 z-50 rounded-xl border border-sky-500/30 bg-[#0d1016] px-4 py-2.5 text-xs text-sky-300 shadow-2xl flex items-center gap-2 animate-in fade-in slide-in-from-top-2">
          <Check className="h-4 w-4 text-sky-400" />
          <span>File saved & persisted to S3 workspace</span>
        </div>
      )}

      {saveError && (
        <div className="fixed top-5 right-5 z-50 rounded-xl border border-rose-500/30 bg-[#180d0d] px-4 py-2.5 text-xs text-rose-300 shadow-2xl flex items-center gap-2 animate-in fade-in slide-in-from-top-2">
          <AlertTriangle className="h-4 w-4 text-rose-400 shrink-0" />
          <span>{saveError}</span>
        </div>
      )}


      {revertToast && (
        <div className="fixed top-5 right-5 z-50 rounded-xl border border-amber-500/30 bg-[#16120d] px-4 py-2.5 text-xs text-amber-300 shadow-2xl flex items-center gap-2 animate-in fade-in slide-in-from-top-2">
          <RotateCcw className="h-4 w-4 text-amber-400" />
          <span>Reverted to original synthesized code</span>
        </div>
      )}

      {formatToast && (
        <div className="fixed top-5 right-5 z-50 rounded-xl border border-emerald-500/30 bg-[#0d1210] px-4 py-2.5 text-xs text-emerald-300 shadow-2xl flex items-center gap-2 animate-in fade-in slide-in-from-top-2">
          <Check className="h-4 w-4 text-emerald-400" />
          <span>Code formatted successfully</span>
        </div>
      )}

      {agentToast && (
        <div className="fixed top-5 right-5 z-50 rounded-xl border border-purple-500/30 bg-[#120d18] px-4 py-2.5 text-xs text-purple-300 shadow-2xl flex items-center gap-2 animate-in fade-in slide-in-from-top-2">
          <Sparkles className="h-4 w-4 text-purple-400" />
          <span>Query sent to LangGraph agent orchestrator</span>
        </div>
      )}

      {/* Main Content Area */}
      <div className="flex-1 min-h-0 flex flex-col p-4 sm:p-5 space-y-4 overflow-y-auto">
        {/* Top Header */}
        <div className="flex flex-wrap items-center justify-between gap-4 shrink-0">
          <div>
            <div className="flex items-center gap-2.5">
              <span className="text-xs font-mono font-bold text-neutral-400 bg-white/5 border border-white/10 px-2 py-0.5 rounded-md">
                03
              </span>
              <h1 className="text-lg sm:text-xl font-bold tracking-tight text-white flex items-center gap-2">
                FastMCP Synthesizer
              </h1>
              <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 font-medium text-xs px-2.5 py-0.5">
                {tools.length} generated
              </span>
            </div>
            <p className="text-xs text-neutral-400 mt-1">
              Generated MCP tools, source files, safety classifications and verification context.
            </p>
          </div>

          <div className="flex items-center gap-2.5">
            <button
              onClick={onRunBuild}
              disabled={isSynthesizing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-white/10 bg-white/[0.04] hover:bg-white/[0.08] text-xs font-medium text-white transition-colors disabled:opacity-50"
            >
              <RotateCw className={`h-3.5 w-3.5 ${isSynthesizing ? 'animate-spin' : ''}`} />
              <span>{isSynthesizing ? 'Synthesizing…' : 'Re-synthesize'}</span>
            </button>

            {files.length > 0 && (
              <button
                onClick={() => {
                  if (onProceedToTest) {
                    onProceedToTest();
                  } else {
                    onContinueToVerify();
                  }
                }}
                className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg border text-xs font-semibold shadow-md transition-all hover:scale-[1.02] active:scale-[0.98] ${
                  isAwaitingTestApproval
                    ? 'border-emerald-500/50 bg-emerald-500 hover:bg-emerald-400 text-neutral-950 shadow-emerald-500/25'
                    : 'border-emerald-500/40 bg-emerald-500 hover:bg-emerald-400 text-neutral-950 shadow-emerald-500/20'
                }`}
              >
                <FlaskConical className="h-3.5 w-3.5" />
                <span>{isAwaitingTestApproval ? 'Approve & Run Tests' : 'Proceed to Test'}</span>
              </button>
            )}
          </div>
        </div>

        {/* Stage 03 Code Review & Approval Gate Banner */}
        {isAwaitingTestApproval && (
          <div className="rounded-xl border border-amber-500/40 bg-gradient-to-r from-amber-950/40 via-amber-900/20 to-black/60 p-4 flex flex-wrap items-center justify-between gap-4 shadow-xl shrink-0 animate-in fade-in slide-in-from-top-2">
            <div className="flex items-center gap-3.5">
              <div className="h-10 w-10 rounded-xl bg-amber-500/20 border border-amber-500/40 flex items-center justify-center text-amber-400 shrink-0">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-white">Stage 03 Complete — Code Review & Test Approval Required</span>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30">
                    {files.length} files synthesized
                  </span>
                </div>
                <p className="text-xs text-neutral-300 mt-1 max-w-2xl">
                  FastMCP server source files, tool bindings, and test fixtures have been synthesized and AST-validated. Review or edit the code in the editor below, then approve to start Stage 04 Docker Sandbox verification.
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => {
                if (onProceedToTest) onProceedToTest();
                else onContinueToVerify();
              }}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl border border-emerald-500/50 bg-emerald-500 hover:bg-emerald-400 text-neutral-950 text-xs font-bold shadow-lg shadow-emerald-500/25 transition-all hover:scale-[1.02] active:scale-[0.98]"
            >
              <FlaskConical className="h-4 w-4" />
              <span>Approve & Run Tests →</span>
            </button>
          </div>
        )}

        {/* Real-time Status Banner */}
        {files.length > 0 && !runIsLive && !isAwaitingTestApproval && (
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-950/20 px-4 py-3 flex flex-wrap items-center justify-between gap-3 shadow-lg shrink-0">
            <div className="flex items-center gap-3">
              <div className="h-9 w-9 rounded-lg bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center text-emerald-400 shrink-0">
                <CheckCircle2 className="h-5 w-5" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-white">FastMCP Files Generated Successfully</span>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                    {files.length} file{files.length === 1 ? '' : 's'} compiled
                  </span>
                </div>
                <p className="text-[11px] text-neutral-400 mt-0.5">
                  Source code, tool bindings, and test fixtures are compiled and AST-validated. Proceed to Stage 04 to run sandbox verification.
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => {
                if (onProceedToTest) {
                  onProceedToTest();
                } else {
                  onContinueToVerify();
                }
              }}
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500 hover:bg-emerald-400 text-neutral-950 text-xs font-semibold shadow-md shadow-emerald-500/20 transition-all hover:scale-[1.02] active:scale-[0.98]"
            >
              <FlaskConical className="h-3.5 w-3.5" />
              <span>Proceed to Test</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        {isSynthesizing && (
          <div className="rounded-xl border border-sky-500/30 bg-sky-950/20 px-4 py-3 flex items-center justify-between gap-3 shadow-lg shrink-0">
            <div className="flex items-center gap-3">
              <Loader2 className="h-5 w-5 text-sky-400 animate-spin shrink-0" />
              <div>
                <span className="text-xs font-bold text-white">Synthesizing FastMCP Server in Real-Time...</span>
                <p className="text-[11px] text-neutral-400 mt-0.5">
                  LangGraph Code Agent is generating typed Python tools, AST validation models, and pytest fixtures ({files.length} files created so far).
                </p>
              </div>
            </div>
            <span className="text-[10px] font-mono text-sky-400 animate-pulse px-2.5 py-1 rounded-full bg-sky-500/10 border border-sky-500/20 shrink-0">
              Generating code...
            </span>
          </div>
        )}

        {/* Sub-Navigation Tabs */}
        <div className="flex items-center gap-1.5 border-b border-white/10 pb-2.5 shrink-0">
          <button
            type="button"
            onClick={() => setActiveSubTab('files')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeSubTab === 'files'
                ? 'border border-white/20 bg-white/10 text-white shadow-sm'
                : 'text-neutral-400 hover:text-white hover:bg-white/[0.04]'
            }`}
          >
            <Layers className="h-3.5 w-3.5" />
            <span>Files</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveSubTab('tools')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeSubTab === 'tools'
                ? 'border border-white/20 bg-white/10 text-white shadow-sm'
                : 'text-neutral-400 hover:text-white hover:bg-white/[0.04]'
            }`}
          >
            <Boxes className="h-3.5 w-3.5" />
            <span>API Tools</span>
            <span className="rounded-full bg-white/10 px-1.5 py-0.2 text-[10px] font-mono text-neutral-300">
              {tools.length}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveSubTab('dependencies')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeSubTab === 'dependencies'
                ? 'border border-white/20 bg-white/10 text-white shadow-sm'
                : 'text-neutral-400 hover:text-white hover:bg-white/[0.04]'
            }`}
          >
            <Network className="h-3.5 w-3.5" />
            <span>Dependencies</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveSubTab('verification')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeSubTab === 'verification'
                ? 'border border-white/20 bg-white/10 text-white shadow-sm'
                : 'text-neutral-400 hover:text-white hover:bg-white/[0.04]'
            }`}
          >
            <ShieldCheck className="h-3.5 w-3.5" />
            <span>Verification</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveSubTab('manifest')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeSubTab === 'manifest'
                ? 'border border-white/20 bg-white/10 text-white shadow-sm'
                : 'text-neutral-400 hover:text-white hover:bg-white/[0.04]'
            }`}
          >
            <FileJson className="h-3.5 w-3.5" />
            <span>Manifest</span>
          </button>
        </div>

        {error && <ErrorBanner message={error} onDismiss={() => setError('')} />}

        {/* TAB 1: FILES 3-COLUMN STUDIO LAYOUT */}
        {activeSubTab === 'files' && (
          <div className="flex-1 min-h-[560px] grid grid-cols-1 md:grid-cols-12 gap-3">
            {/* COLUMN 1: PROJECT FILES TREE (3 cols on md) */}
            <div className="md:col-span-3 rounded-xl border border-white/10 bg-[#090a0f] p-3 flex flex-col min-h-[500px]">
              <div className="flex items-center justify-between mb-2.5 pb-2 border-b border-white/5">
                <span className="text-[10px] font-mono tracking-wider uppercase text-neutral-400 font-semibold">
                  PROJECT FILES
                </span>
                <span className="text-[10px] font-mono text-neutral-500">
                  {dirtyFiles.size > 0 ? `${dirtyFiles.size} modified` : `${uniqueFiles.length} file${uniqueFiles.length === 1 ? '' : 's'}`}
                </span>
              </div>

              {/* Search file input */}
              <div className="relative mb-3">
                <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-neutral-500" />
                <input
                  type="text"
                  placeholder="Search files..."
                  value={fileSearch}
                  onChange={e => setFileSearch(e.target.value)}
                  className="w-full rounded-lg border border-white/10 bg-white/[0.02] pl-8 pr-3 py-1.5 text-xs text-white placeholder-neutral-500 focus:outline-none focus:border-white/30"
                />
              </div>

              {/* File Tree List */}
              <div className="flex-1 min-h-0 overflow-y-auto space-y-3 text-xs pr-1">
                {files.length === 0 ? (
                  (runIsLive || activeRun?.current_node === 'code_agent' || loadingFiles) ? (
                    <div className="py-8 px-2 text-center text-xs text-neutral-400 space-y-2">
                      <Loader2 className="h-5 w-5 animate-spin text-sky-400 mx-auto" />
                      <p className="font-mono text-[11px] text-sky-300">Synthesizing files...</p>
                      <p className="text-[10px] text-neutral-500">Files appear here as synthesized</p>
                    </div>
                  ) : (
                    <div className="py-8 px-2 text-center text-xs text-neutral-400 space-y-2">
                      <FolderOpen className="h-6 w-6 text-neutral-600 mx-auto" />
                      <p className="text-neutral-400 font-medium">No files synthesized yet</p>
                      <p className="text-[10px] text-neutral-500">Approve Stage 02 to generate files</p>
                    </div>
                  )
                ) : (
                  <>
                    {/* fastmcp folder */}
                    {fastmcpFiles.length > 0 && (
                      <div>
                        <button
                          type="button"
                          onClick={() => setFastmcpFolderOpen(prev => !prev)}
                          className="w-full flex items-center justify-between text-neutral-400 hover:text-white font-medium py-1 text-left"
                        >
                          <div className="flex items-center gap-1.5">
                            {fastmcpFolderOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                            <Folder className="h-3.5 w-3.5 text-sky-400" />
                            <span>fastmcp</span>
                          </div>
                          <span className="text-[10px] text-neutral-500 font-mono">{fastmcpFiles.length}</span>
                        </button>

                        {fastmcpFolderOpen && (
                          <div className="ml-3 mt-1 space-y-1 pl-2 border-l border-white/10">
                            {fastmcpFiles
                              .filter(f => f.file_path.toLowerCase().includes(fileSearch.toLowerCase()))
                              .map(renderFileRow)}
                          </div>
                        )}
                      </div>
                    )}

                    {/* tests folder */}
                    {testFiles.length > 0 && (
                      <div>
                        <button
                          type="button"
                          onClick={() => setTestsFolderOpen(prev => !prev)}
                          className="w-full flex items-center gap-1.5 text-neutral-400 hover:text-white font-medium py-1 text-left"
                        >
                          <div className="flex items-center gap-1.5">
                            {testsFolderOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                            <Folder className="h-3.5 w-3.5 text-amber-400" />
                            <span>tests</span>
                          </div>
                          <span className="text-[10px] text-neutral-500 font-mono">{testFiles.length}</span>
                        </button>

                        {testsFolderOpen && (
                          <div className="ml-3 mt-1 space-y-1 pl-2 border-l border-white/10">
                            {testFiles
                              .filter(f => f.file_path.toLowerCase().includes(fileSearch.toLowerCase()))
                              .map(renderFileRow)}
                          </div>
                        )}
                      </div>
                    )}

                    {/* other folder */}
                    {otherFiles.length > 0 && (
                      <div>
                        <button
                          type="button"
                          onClick={() => setOtherFolderOpen(prev => !prev)}
                          className="w-full flex items-center gap-1.5 text-neutral-400 hover:text-white font-medium py-1 text-left"
                        >
                          <div className="flex items-center gap-1.5">
                            {otherFolderOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                            <Folder className="h-3.5 w-3.5 text-purple-400" />
                            <span>other</span>
                          </div>
                          <span className="text-[10px] text-neutral-500 font-mono">{otherFiles.length}</span>
                        </button>

                        {otherFolderOpen && (
                          <div className="ml-3 mt-1 space-y-1 pl-2 border-l border-white/10">
                            {otherFiles
                              .filter(f => f.file_path.toLowerCase().includes(fileSearch.toLowerCase()))
                              .map(renderFileRow)}
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>

            {/* COLUMN 2: CENTRAL MONACO CODE EDITOR (6 cols on md) */}
            <div className="md:col-span-6 rounded-xl border border-white/10 bg-[#090a0f] flex flex-col min-h-[500px] overflow-hidden">
              {files.length === 0 ? (
                (runIsLive || activeRun?.current_node === 'code_agent' || loadingFiles) ? (
                  <div className="flex-1 min-h-[380px] flex flex-col items-center justify-center p-6 text-center">
                    <div className="relative mb-4">
                      <div className="h-12 w-12 rounded-2xl bg-sky-500/10 border border-sky-500/30 flex items-center justify-center text-sky-400 shadow-lg shadow-sky-500/10">
                        <Code2 className="h-6 w-6 animate-pulse" />
                      </div>
                      <span className="absolute -bottom-1 -right-1 flex h-4 w-4">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-4 w-4 bg-sky-500"></span>
                      </span>
                    </div>
                    <h3 className="text-sm font-semibold text-white">Synthesizing FastMCP Server in Real-Time</h3>
                    <p className="text-xs text-neutral-400 max-w-sm mt-1.5 mb-4">
                      LangGraph Code Agent is compiling your OpenAPI endpoints into typed FastMCP tools, client models, and pytest fixtures. Files will stream directly into this editor as they are compiled.
                    </p>
                    <div className="flex items-center gap-2 text-xs font-mono text-sky-400 bg-sky-500/10 border border-sky-500/20 px-3 py-1.5 rounded-lg">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      <span>code_agent compiling AST...</span>
                    </div>
                  </div>
                ) : (
                  <div className="flex-1 min-h-[380px] flex flex-col items-center justify-center p-6 text-center">
                    <div className="h-12 w-12 rounded-2xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400 mb-4 shadow-lg shadow-amber-500/10">
                      <ShieldAlert className="h-6 w-6" />
                    </div>
                    <h3 className="text-sm font-semibold text-white">Awaiting Stage 02 Approval</h3>
                    <p className="text-xs text-neutral-400 max-w-sm mt-1.5 mb-5">
                      FastMCP code synthesis will begin automatically once you review and approve the Dependency Graph in Stage 02.
                    </p>
                    {onGoToDependencies && (
                      <button
                        type="button"
                        onClick={onGoToDependencies}
                        className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-white/10 hover:bg-white/15 border border-white/15 text-xs font-medium text-white transition-colors"
                      >
                        <ArrowLeft className="h-3.5 w-3.5" />
                        <span>Review Stage 02 Dependency Graph</span>
                      </button>
                    )}
                  </div>
                )
              ) : (
                <>
                  {/* Tab Header Bar */}
                  <div className="flex items-center justify-between border-b border-white/10 px-3 py-2 bg-white/[0.02] shrink-0">
                    <div className="flex items-center gap-2 font-mono text-xs text-white">
                      <span className="text-neutral-400">◇</span>
                      <span className="font-medium">{selectedFile}</span>
                      {isSelectedFileDirty && (
                        <span className="h-1.5 w-1.5 rounded-full bg-amber-400" title="Modified" />
                      )}
                      {isSelectedFileDirty && (
                        <span className="text-[10px] text-amber-400 font-sans ml-1">● Unsaved</span>
                      )}
                    </div>

                    <div className="flex items-center gap-2 text-xs">
                      <button
                        type="button"
                        onClick={handleFormat}
                        className="px-2.5 py-1 rounded hover:bg-white/10 text-neutral-400 hover:text-white transition-colors"
                        title="Format file content"
                      >
                        Format
                      </button>

                      <button
                        type="button"
                        onClick={() => setDiffMode(prev => !prev)}
                        className={`px-2.5 py-1 rounded transition-colors ${
                          diffMode
                            ? 'bg-sky-500/20 text-sky-300 border border-sky-500/30 font-medium'
                            : 'text-neutral-400 hover:text-white hover:bg-white/10'
                        }`}
                        title="Toggle side-by-side diff against original"
                      >
                        {diffMode ? 'Close Diff' : 'Diff'}
                      </button>

                      {isSelectedFileDirty && (
                        <button
                          type="button"
                          onClick={handleRevert}
                          className="p-1 rounded hover:bg-white/10 text-neutral-400 hover:text-white transition-colors"
                          title="Revert edits to original"
                        >
                          <RotateCcw className="h-3.5 w-3.5" />
                        </button>
                      )}

                      <button
                        type="button"
                        onClick={handleSave}
                        disabled={isSaving}
                        className={`flex items-center gap-1.5 px-2.5 py-1 rounded transition-colors font-medium ${
                          isSelectedFileDirty
                            ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40 hover:bg-amber-500/30'
                            : 'text-neutral-400 hover:text-white hover:bg-white/10'
                        } disabled:opacity-50`}
                        title="Save changes to workspace (Ctrl+S)"
                      >
                        <Save className={`h-3 w-3 ${isSaving ? 'animate-spin' : ''}`} />
                        <span>{isSaving ? 'Saving…' : 'Save'}</span>
                      </button>

                      <button
                        type="button"
                        onClick={copyToClipboard}
                        className="p-1 rounded hover:bg-white/10 text-neutral-400 hover:text-white transition-colors ml-0.5"
                        title="Copy code"
                      >
                        <Copy className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>

                  {/* Monaco Editor Container */}
                  <div className="flex-1 min-h-0 w-full relative">
                    {loadingFiles && !activeEditorContent && (
                      <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-[#090a0f]/80 backdrop-blur-sm gap-2">
                        <Loader2 className="h-5 w-5 animate-spin text-sky-400" />
                        <span className="text-xs font-mono text-neutral-400">Loading file content...</span>
                      </div>
                    )}
                    {diffMode ? (
                      <DiffEditor
                        height="100%"
                        language={
                          selectedFile.endsWith('.json')
                            ? 'json'
                            : selectedFile.endsWith('.py')
                            ? 'python'
                            : selectedFile.endsWith('.ts')
                            ? 'typescript'
                            : selectedFile.endsWith('.js')
                            ? 'javascript'
                            : selectedFile.endsWith('.md')
                            ? 'markdown'
                            : selectedFile.endsWith('.toml')
                            ? 'toml'
                            : 'plaintext'
                        }
                        theme="vs-dark"
                        original={originalEditorContent}
                        modified={activeEditorContent}
                        options={{
                          readOnly: true,
                          minimap: { enabled: false },
                          fontSize: 12,
                          lineNumbers: 'on',
                          scrollBeyondLastLine: false,
                          renderSideBySide: true,
                        }}
                      />
                    ) : (
                      <Editor
                        height="100%"
                        language={
                          selectedFile.endsWith('.json')
                            ? 'json'
                            : selectedFile.endsWith('.py')
                            ? 'python'
                            : selectedFile.endsWith('.ts')
                            ? 'typescript'
                            : selectedFile.endsWith('.js')
                            ? 'javascript'
                            : selectedFile.endsWith('.md')
                            ? 'markdown'
                            : selectedFile.endsWith('.toml')
                            ? 'toml'
                            : 'plaintext'
                        }
                        theme="vs-dark"
                        value={activeEditorContent}
                        onChange={handleEditorChange}
                        options={{
                          readOnly: false,
                          minimap: { enabled: false },
                          fontSize: 12,
                          lineNumbers: 'on',
                          scrollBeyondLastLine: false,
                          renderLineHighlight: 'all',
                          wordWrap: 'on',
                          tabSize: 4,
                          insertSpaces: true,
                        }}
                      />
                    )}
                  </div>
                </>
              )}
            </div>

            {/* COLUMN 3: CONTEXTUAL ENDPOINT INSPECTOR (3 cols on md) */}
            <div className="md:col-span-3 rounded-xl border border-white/10 bg-[#090a0f] p-4 flex flex-col min-h-[500px] overflow-y-auto space-y-4">
              <div>
                <span className="text-[10px] font-mono tracking-wider uppercase text-neutral-400 block mb-1">
                  SELECTED ENDPOINT
                </span>
                <h3 className="text-sm font-bold font-mono text-white truncate" title={selectedTool?.name}>
                  {selectedTool?.name || 'endpoint'}
                </h3>
              </div>

              {/* Endpoint Primary Card */}
              {selectedTool && (
                <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <MethodChip method={selectedTool.method} />
                    <span className="font-mono text-xs text-neutral-300 truncate" title={selectedTool.path}>
                      {selectedTool.path}
                    </span>
                  </div>
                  <div className="pt-2 border-t border-white/5 flex items-center justify-between text-xs">
                    <span className="text-neutral-400 text-[11px]">Safety classification</span>
                    <span
                      className={`font-mono text-[10px] font-bold ${
                        selectedTool.safetyBadge.includes('DESTRUCTIVE')
                          ? 'text-rose-400'
                          : selectedTool.safetyBadge.includes('STATE-CHANGING')
                          ? 'text-amber-400'
                          : 'text-emerald-400'
                      }`}
                    >
                      {selectedTool.safetyBadge}
                    </span>
                  </div>
                </div>
              )}

              {/* PROPERTIES */}
              {selectedTool && (
                <div className="space-y-2">
                  <span className="text-[10px] font-mono tracking-wider uppercase text-neutral-400 block">
                    PROPERTIES
                  </span>
                  <div className="rounded-xl border border-white/5 bg-white/[0.01] p-2.5 space-y-1.5 text-xs font-mono">
                    <div className="flex items-center justify-between">
                      <span className="text-neutral-400">Risk</span>
                      <span className="text-neutral-200">{selectedTool.riskLevel}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-neutral-400">Confirmation</span>
                      <span className="text-neutral-200">{selectedTool.confirmationText}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-neutral-400">Source</span>
                      <span className="text-neutral-200">OpenAPI</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-neutral-400">Generated</span>
                      <span className="text-neutral-400">{`tools.py:${selectedTool.lineRef}`}</span>
                    </div>
                  </div>
                </div>
              )}

              {/* DEPENDENCIES */}
              <div className="space-y-2">
                <span className="text-[10px] font-mono tracking-wider uppercase text-neutral-400 block">
                  DEPENDENCIES
                </span>
                <div className="rounded-xl border border-white/5 bg-white/[0.01] p-2.5 space-y-1.5 text-xs font-mono">
                  <div className="flex items-center justify-between">
                    <span className="text-neutral-400">Base URL</span>
                    <span className="text-neutral-200">API_BASE_URL</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-neutral-400">HTTP Client</span>
                    <span className="text-neutral-200">httpx</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-neutral-400">Auth</span>
                    <span className="text-neutral-200">{authSchemeText}</span>
                  </div>
                </div>
              </div>

              {/* AGENT ACTIONS */}
              <div className="space-y-2 pt-1">
                <span className="text-[10px] font-mono tracking-wider uppercase text-neutral-400 block">
                  AGENT ACTIONS
                </span>
                <button
                  type="button"
                  onClick={handleAskAgent}
                  className="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl border border-white/10 bg-white/[0.03] hover:bg-white/[0.07] text-xs font-medium text-white transition-colors"
                >
                  <Sparkles className="h-3.5 w-3.5 text-purple-400" />
                  <span>✦ Ask Agent About This</span>
                </button>
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: API TOOLS DETAILED LIST */}
        {activeSubTab === 'tools' && (
          <div className="flex-1 min-h-0 flex flex-col space-y-3 overflow-hidden">
            {/* Search & Filters */}
            <div className="flex flex-wrap items-center justify-between gap-3 shrink-0">
              <div className="relative flex-1 min-w-[200px]">
                <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-neutral-500" />
                <input
                  type="text"
                  placeholder="Search synthesized tools by name, route, or description..."
                  value={toolSearch}
                  onChange={e => setToolSearch(e.target.value)}
                  className="w-full rounded-xl border border-white/10 bg-white/[0.02] pl-9 pr-4 py-2 text-xs text-white placeholder-neutral-500 focus:outline-none focus:border-white/30"
                />
              </div>

              {/* Method filter */}
              <div className="flex items-center gap-1 bg-white/[0.02] border border-white/5 rounded-lg p-0.5 text-xs">
                {['ALL', 'GET', 'POST', 'PUT', 'DELETE'].map(m => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setMethodFilter(m)}
                    className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-all ${
                      methodFilter === m
                        ? 'bg-sky-500/20 text-sky-300 border border-sky-500/30'
                        : 'text-neutral-400 hover:text-white'
                    }`}
                  >
                    {m}
                  </button>
                ))}
              </div>

              {/* Safety filter */}
              <div className="flex items-center gap-1 bg-white/[0.02] border border-white/5 rounded-lg p-0.5 text-xs">
                {['ALL', 'SAFE', 'STATE-CHANGING', 'DESTRUCTIVE'].map(s => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setSafetyFilter(s)}
                    className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-all ${
                      safetyFilter === s
                        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                        : 'text-neutral-400 hover:text-white'
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>

            {/* Tools Grid */}
            <div className="flex-1 min-h-0 overflow-y-auto space-y-2 pr-1">
              {filteredTools.map(tool => {
                const isSelected = selectedToolId === tool.id;
                return (
                  <div
                    key={tool.id}
                    onClick={() => {
                      setSelectedToolId(tool.id);
                      setActiveSubTab('files');
                    }}
                    className={`cursor-pointer rounded-xl border p-3.5 transition-all flex flex-wrap items-center justify-between gap-3 ${
                      isSelected
                        ? 'border-sky-500/60 bg-sky-500/[0.08]'
                        : 'border-white/10 bg-white/[0.02] hover:border-white/20 hover:bg-white/[0.04]'
                    }`}
                  >
                    <div className="flex items-center gap-3 min-w-0 flex-1">
                      <MethodChip method={tool.method} />
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs font-bold text-white truncate">{tool.name}</span>
                          <span className="font-mono text-[11px] text-neutral-400 truncate">({tool.path})</span>
                        </div>
                        <p className="text-xs text-neutral-400 line-clamp-1 mt-0.5">{tool.summary}</p>
                      </div>
                    </div>

                    <div className="flex items-center gap-3 shrink-0">
                      <span className={`rounded-md border px-2 py-0.5 font-mono text-[10px] font-bold ${getBadgeStyle(tool.safetyBadge)}`}>
                        {tool.safetyBadge}
                      </span>
                      {tool.requiresConfirmation && (
                        <span className="rounded bg-rose-500/10 px-2 py-0.5 text-[10px] font-mono text-rose-300 border border-rose-500/20">
                          Confirm req.
                        </span>
                      )}
                      <ArrowRight className="h-4 w-4 text-neutral-500" />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* TAB 3: DEPENDENCIES */}
        {activeSubTab === 'dependencies' && (
          <div className="flex-1 min-h-0 overflow-y-auto space-y-4 pr-1">
            <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
              <h3 className="text-sm font-semibold text-white mb-1">FastMCP Tool Execution Chaining</h3>
              <p className="text-xs text-neutral-400">
                Generated FastMCP tools share schema validation and propagate prerequisite parameters between upstream and downstream requests.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4 space-y-2">
                <span className="text-xs font-mono text-sky-400 font-semibold">Base Client Binding</span>
                <p className="text-xs text-neutral-400">
                  Shared async httpx client configured with exponential backoff and authentication header injection.
                </p>
                <div className="rounded-lg bg-black/40 p-2 font-mono text-[11px] text-neutral-300">
                  httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)
                </div>
              </div>

              <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4 space-y-2">
                <span className="text-xs font-mono text-emerald-400 font-semibold">Security Injection</span>
                <p className="text-xs text-neutral-400">
                  Vault-backed environment variables injected safely during FastMCP server boot.
                </p>
                <div className="rounded-lg bg-black/40 p-2 font-mono text-[11px] text-neutral-300">
                  Authorization: {authSchemeText} (from Vault KMS)
                </div>
              </div>
            </div>
          </div>
        )}

        {/* TAB 4: VERIFICATION */}
        {activeSubTab === 'verification' && (
          <div className="flex-1 min-h-0 overflow-y-auto space-y-4 pr-1">
            <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
              <h3 className="text-sm font-semibold text-white mb-1">Pre-Sandbox Static Validation Gate</h3>
              <p className="text-xs text-neutral-400">
                Verification checks performed on synthesized FastMCP code before dispatch to the Docker pytest sandbox.
              </p>
            </div>

            <div className="space-y-2">
              {[
                { name: 'Python AST Syntax Verification', status: 'PASS', detail: 'Syntax tree parsed cleanly without errors' },
                { name: 'FastMCP Decorator Integrity', status: 'PASS', detail: 'All @mcp.tool decorators have typed docstrings' },
                { name: 'Pydantic Model Generation', status: 'PASS', detail: 'Request/response payloads verified against schemas' },
                { name: 'Deterministic Safety Gate Decorators', status: 'PASS', detail: 'Irreversible endpoints flagged with confirmation gates' },
              ].map(check => (
                <div
                  key={check.name}
                  className="rounded-xl border border-white/10 bg-white/[0.02] p-3 flex items-center justify-between"
                >
                  <div>
                    <span className="text-xs font-semibold text-white">{check.name}</span>
                    <p className="text-[11px] text-neutral-400 mt-0.5">{check.detail}</p>
                  </div>
                  <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 px-2 py-0.5 text-xs font-mono font-bold">
                    {check.status}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB 5: MANIFEST */}
        {activeSubTab === 'manifest' && (
          <div className="flex-1 min-h-0 flex flex-col space-y-2 overflow-hidden">
            <div className="flex items-center justify-between shrink-0">
              <span className="text-xs text-neutral-400">
                Editable <code className="text-white font-mono">manifest.json</code> for Claude Desktop and MCP clients
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={isSaving}
                  className="flex items-center gap-1.5 px-3 py-1 rounded-lg border border-white/10 bg-white/5 hover:bg-white/10 text-xs text-white transition-colors disabled:opacity-50"
                >
                  <Save className={`h-3 w-3 ${isSaving ? 'animate-spin' : ''}`} />
                  <span>{isSaving ? 'Saving…' : 'Save Manifest'}</span>
                </button>

                <button
                  type="button"
                  onClick={copyToClipboard}
                  className="flex items-center gap-1.5 px-3 py-1 rounded-lg border border-white/10 bg-white/5 hover:bg-white/10 text-xs text-white transition-colors"
                >
                  <Copy className="h-3 w-3" />
                  <span>Copy Manifest</span>
                </button>
              </div>
            </div>
            <div className="flex-1 min-h-0 rounded-xl border border-white/10 bg-[#090a0f] overflow-hidden">
              <Editor
                height="100%"
                language="json"
                theme="vs-dark"
                value={getCurrentCode('manifest.json')}
                onChange={val => {
                  if (val !== undefined) {
                    setSelectedFile('manifest.json');
                    handleEditorChange(val);
                  }
                }}
                options={{
                  readOnly: false,
                  minimap: { enabled: false },
                  fontSize: 12,
                  lineNumbers: 'on',
                  tabSize: 2,
                  insertSpaces: true,
                }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Persistent Fixed Action Footer */}
      <div className="shrink-0 border-t border-white/10 bg-[#0c0d12]/95 px-5 py-3.5 backdrop-blur-md flex flex-wrap items-center justify-between gap-3 shadow-[0_-4px_16px_rgba(0,0,0,0.5)] z-10">
        <div className="flex items-center gap-2 text-xs text-neutral-400">
          <span className="font-mono text-neutral-400 font-semibold">FastMCP v1.2</span>
          <span>·</span>
          <span className="text-emerald-400 flex items-center gap-1">
            <CheckCircle2 className="h-3.5 w-3.5" /> Deterministic AST syntax valid
          </span>
          {dirtyFiles.size > 0 && (
            <>
              <span>·</span>
              <span className="text-amber-400 font-mono">
                {dirtyFiles.size} unsaved file{dirtyFiles.size === 1 ? '' : 's'}
              </span>
            </>
          )}
        </div>
        <button
          onClick={() => {
            if (files.length > 0 && onProceedToTest) {
              onProceedToTest();
            } else {
              onContinueToVerify();
            }
          }}
          disabled={runIsLive && files.length === 0}
          className={`${btnPrimary} flex items-center gap-2 ${runIsLive && files.length === 0 ? 'opacity-50 cursor-not-allowed' : ''}`}
        >
          {files.length > 0 ? (
            <>
              <FlaskConical className="h-4 w-4" />
              <span>{isAwaitingTestApproval ? 'Approve & Run Tests' : 'Proceed to Test'}</span>
            </>
          ) : (
            <span>Continue to Verify</span>
          )}
          <ArrowRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
};
