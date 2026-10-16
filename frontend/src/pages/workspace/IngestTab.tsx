import React, { useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  FileCode2,
  FileJson,
  FileText,
  FileType,
  History,
  Link2,
  Loader2,
  Maximize2,
  Plus,
  RotateCcw,
  Sparkles,
  Upload,
} from 'lucide-react';
import Editor from '@monaco-editor/react';
import { ApiSpec, SpecEndpoint, UploadResponse } from '../../lib/types';
import { btnGhost, btnPrimary, cardCls, ErrorBanner, inputCls, StatusBadge } from '../../components/ui';
import { NormalizedSpec, specFormat, validationState } from '../../lib/format';

export type UploadMode = 'file' | 'paste' | 'url';
export type UploadPhase = 'idle' | 'working' | 'success' | 'error';

const NEXT_STAGES = [
  { title: 'Deterministic Parsing', desc: 'Parse OpenAPI/Swagger specs or extract endpoints via RAG docs.' },
  { title: 'Dependency Graph', desc: 'Extract endpoint topology, parameters, and auth schemes.' },
  { title: 'FastMCP Synthesis', desc: 'Generate typed tools with deterministic safety classification.' },
  { title: 'Sandbox Verification', desc: 'Ephemeral Docker test runner with synthetic HTTP mocks.' },
];

export interface IngestTabProps {
  file: File | null;
  setFile: (f: File | null) => void;
  setFilePreview?: (val: string) => void;
  mode: UploadMode;
  setMode: (m: UploadMode) => void;
  specContent: string;
  setSpecContent: (s: string) => void;
  urlValue: string;
  setUrlValue: (s: string) => void;
  urlNote: string;
  phase: UploadPhase;
  setPhase: (p: UploadPhase) => void;
  uploadError: string;
  uploadedMeta: { name: string; format: string } | null;
  uploadResult: UploadResponse | null;
  spec: ApiSpec | null;
  endpoints: SpecEndpoint[];
  showAnalysis: boolean;
  editorValue: string;
  language: string;
  hasValidInput: boolean;
  onUrlImport: () => void;
  onUpload: () => void;
  onReset: () => void;
  onContinue: () => void;
  onPreviewExpand: () => void;
}

export const IngestTab: React.FC<IngestTabProps> = ({
  file,
  setFile,
  setFilePreview,
  mode,
  setMode,
  specContent,
  setSpecContent,
  urlValue,
  setUrlValue,
  urlNote,
  phase,
  setPhase,
  uploadError,
  uploadedMeta,
  uploadResult,
  spec,
  endpoints,
  showAnalysis,
  editorValue,
  language,
  hasValidInput,
  onUrlImport,
  onUpload,
  onReset,
  onContinue,
  onPreviewExpand,
}) => {
  const [subTab, setSubTab] = useState<'spec' | 'analysis' | 'history'>('spec');
  const [formatStatus, setFormatStatus] = useState('');
  const [formattedOverride, setFormattedOverride] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const editorRef = useRef<any>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Clear formattedOverride whenever the source file, content, or mode changes
  React.useEffect(() => {
    setFormattedOverride(null);
  }, [file, specContent, mode, editorValue]);

  // Automatically activate Specification Analysis view once upload succeeds or analysis is available
  React.useEffect(() => {
    if (uploadResult || (showAnalysis && phase === 'success')) {
      setSubTab('analysis');
    }
  }, [uploadResult, showAnalysis, phase]);

  const activeCode = formattedOverride ?? editorValue;

  /* Spec Analysis Metrics */
  const raw = (spec?.raw_normalized ?? {}) as NormalizedSpec;
  const schemasObj = raw.components?.schemas ?? raw.definitions ?? {};
  const schemaCount = Object.keys(schemasObj).length;
  const authSchemesObj = raw.components?.securitySchemes ?? raw.securityDefinitions ?? {};
  const authSchemes = Object.keys(authSchemesObj);
  const endpointCount = endpoints.length || (uploadResult?.endpoints_discovered ?? 0);
  const validation = validationState(spec?.confidence_score);
  const deprecated = endpoints.filter(e => e.deprecated).length;
  const missingSummary = endpoints.filter(e => !e.summary).length;
  const lowConfidence = endpoints.filter(e => e.confidence_score !== null && e.confidence_score < 0.6).length;

  const detectedFormat = spec
    ? specFormat(raw)
    : file
      ? (file.name.toLowerCase().endsWith('.json') ? 'JSON' : 'YAML')
      : 'OpenAPI 3.1';

  /* Handlers */
  const handleFormat = () => {
    const currentText = activeCode;
    let formatted = currentText;

    // 1. Try parsing and pretty-printing JSON with 2-space indentation
    try {
      const parsed = JSON.parse(currentText);
      formatted = JSON.stringify(parsed, null, 2);
    } catch {
      // 2. If YAML or plain text, normalize line endings and trim trailing whitespace per line
      formatted = currentText
        .split(/\r?\n/)
        .map(line => line.trimEnd())
        .join('\n');
    }

    setFormattedOverride(formatted);
    if (mode === 'paste') {
      setSpecContent(formatted);
    }
    if (setFilePreview) {
      setFilePreview(formatted);
    }

    // 3. Update Monaco editor instance directly
    if (editorRef.current) {
      try {
        const model = editorRef.current.getModel();
        if (model) {
          editorRef.current.updateOptions({ readOnly: false });
          editorRef.current.setValue(formatted);
          editorRef.current.getAction('editor.action.formatDocument')?.run();
          if (mode !== 'paste') {
            setTimeout(() => {
              editorRef.current?.updateOptions({ readOnly: true });
            }, 100);
          }
        }
      } catch {
        // no-op
      }
    }

    setFormatStatus('Formatted!');
    setTimeout(() => setFormatStatus(''), 2000);
  };

  const handleFileDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (phase === 'working') return;
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) {
      setFile(dropped);
      setPhase('idle');
    }
  };

  return (
    <div className="flex flex-col h-full min-h-0 bg-[#0c0d12]">
      {/* Top Section: Sub-Tabs & Editor Action Buttons */}
      <div className="shrink-0 flex items-center justify-between border-b border-white/10 px-5 py-3">
        {/* Navigation Sub-Tabs */}
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setSubTab('spec')}
            className={`flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-medium transition-all ${
              subTab === 'spec'
                ? 'bg-white/10 text-white border border-white/15 shadow-sm'
                : 'text-neutral-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <span>Specification</span>
            <span className="rounded bg-white/10 px-1 py-0.2 text-[10px] text-neutral-400 font-mono">⌘</span>
          </button>
          <button
            type="button"
            onClick={() => setSubTab('analysis')}
            className={`flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-medium transition-all ${
              subTab === 'analysis'
                ? 'bg-white/10 text-white border border-white/15 shadow-sm'
                : 'text-neutral-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <span>Analysis</span>
            <span className="rounded-full bg-emerald-500/15 border border-emerald-500/30 px-1.5 py-0.2 text-[10px] text-emerald-400 font-mono">
              {endpointCount || 4}
            </span>
          </button>
          <button
            type="button"
            onClick={() => setSubTab('history')}
            className={`flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-medium transition-all ${
              subTab === 'history'
                ? 'bg-white/10 text-white border border-white/15 shadow-sm'
                : 'text-neutral-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <span>History</span>
            <span className="rounded-full bg-white/10 px-1.5 py-0.2 text-[10px] text-neutral-400 font-mono">
              {spec ? 1 : 0}
            </span>
          </button>
        </div>

        {/* Global Toolbar Action Buttons */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleFormat}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-neutral-200 hover:bg-white/10 hover:text-white transition-colors"
            title="Format & Prettify specification code"
          >
            <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
            <span>{formatStatus || 'Format'}</span>
          </button>
          <button
            type="button"
            onClick={onPreviewExpand}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-neutral-200 hover:bg-white/10 hover:text-white transition-colors"
            title="Expand editor to fullscreen"
          >
            <Maximize2 className="h-3.5 w-3.5" />
            <span>Expand</span>
          </button>
        </div>
      </div>

      {/* Main Scrollable Area */}
      <div className="flex-1 overflow-y-auto p-5 space-y-5">
        {uploadError && (
          <ErrorBanner message={uploadError} onDismiss={() => setPhase('idle')} />
        )}

        {/* --- SubTab 1: Specification (Reference Hero Layout) --- */}
        {subTab === 'spec' && (
          <>
            {/* Mode Selector & Active Spec Status Strip */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-1 rounded-xl border border-white/10 bg-white/[0.03] p-1 text-xs">
                <button
                  type="button"
                  onClick={() => setMode('file')}
                  className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 transition-all ${
                    mode === 'file' ? 'bg-white text-black font-semibold shadow-sm' : 'text-neutral-400 hover:text-white'
                  }`}
                >
                  <Upload className="h-3.5 w-3.5" />
                  <span>Upload</span>
                </button>
                <button
                  type="button"
                  onClick={() => setMode('paste')}
                  className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 transition-all ${
                    mode === 'paste' ? 'bg-white text-black font-semibold shadow-sm' : 'text-neutral-400 hover:text-white'
                  }`}
                >
                  <FileCode2 className="h-3.5 w-3.5" />
                  <span>Paste</span>
                </button>
                <button
                  type="button"
                  onClick={() => setMode('url')}
                  className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 transition-all ${
                    mode === 'url' ? 'bg-white text-black font-semibold shadow-sm' : 'text-neutral-400 hover:text-white'
                  }`}
                >
                  <Link2 className="h-3.5 w-3.5" />
                  <span>Import URL</span>
                </button>
              </div>

              {/* Active Spec Pill */}
              <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.02] px-3 py-1.5 text-xs text-neutral-400 font-mono">
                <span className={`h-2 w-2 rounded-full ${spec || file ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]' : 'bg-amber-400'}`} />
                <span className="truncate max-w-[220px] text-neutral-200">
                  {file?.name || uploadedMeta?.name || (spec ? 'api-spec.json' : 'specification.yaml')}
                </span>
                {file && <span className="text-neutral-500">· {(file.size / 1024).toFixed(1)} KB</span>}
                {spec && !file && <span className="text-neutral-500">· {endpoints.length} endpoints</span>}
              </div>
            </div>

            {/* 2. Change specification / Source Card (ABOVE THE EDITOR) */}
            <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm font-semibold text-white">Change specification</span>
                {mode === 'file' && (
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="text-xs text-neutral-400 hover:text-white transition-colors"
                  >
                    Replace source
                  </button>
                )}
              </div>

              {mode === 'file' && (
                <div
                  onClick={() => fileInputRef.current?.click()}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragOver(true);
                  }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={handleFileDrop}
                  className={`border border-dashed rounded-xl p-4 flex flex-col items-center justify-center text-center cursor-pointer transition-all ${
                    dragOver
                      ? 'border-emerald-400 bg-emerald-500/10'
                      : 'border-white/15 hover:border-white/30 bg-white/[0.01]'
                  }`}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".yaml,.yml,.json,.md,.pdf"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) {
                        setFile(f);
                        setPhase('idle');
                      }
                    }}
                  />
                  <div className="flex items-center gap-2 text-sm font-semibold text-white mb-1">
                    <Plus className="h-4 w-4 text-emerald-400" />
                    <span>Browse files</span>
                  </div>
                  <p className="text-[11px] text-neutral-500">
                    .json · .yaml · .yml · .md · .pdf
                  </p>
                  {file && (
                    <p className="mt-2 text-xs text-emerald-300 font-mono truncate max-w-full">
                      {file.name} ({(file.size / 1024).toFixed(1)} KB)
                    </p>
                  )}
                </div>
              )}

              {mode === 'url' && (
                <div className="space-y-2.5">
                  <input
                    type="url"
                    value={urlValue}
                    onChange={(e) => setUrlValue(e.target.value)}
                    placeholder="https://petstore.swagger.io/v2/swagger.json"
                    className={`${inputCls} text-xs`}
                    disabled={phase === 'working'}
                  />
                  <button
                    type="button"
                    onClick={onUrlImport}
                    disabled={!urlValue.trim() || phase === 'working'}
                    className="w-full flex items-center justify-center gap-1.5 rounded-xl bg-white text-black text-xs font-semibold py-2 hover:bg-neutral-200 transition-colors disabled:opacity-50"
                  >
                    {phase === 'working' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Link2 className="h-3.5 w-3.5" />}
                    <span>Import URL</span>
                  </button>
                  {urlNote && <p className="text-xs text-emerald-300">{urlNote}</p>}
                </div>
              )}

              {mode === 'paste' && (
                <div className="rounded-xl border border-white/5 bg-white/[0.01] p-3 text-xs text-neutral-400 space-y-2">
                  <p>Editing directly in the central editor below. Paste any OpenAPI or Swagger document.</p>
                  <div className="flex items-center gap-2 pt-1 border-t border-white/5">
                    <button
                      type="button"
                      onClick={handleFormat}
                      className="flex items-center gap-1 text-emerald-400 hover:text-emerald-300"
                    >
                      <Sparkles className="h-3 w-3" /> Format code
                    </button>
                    <span>·</span>
                    <button
                      type="button"
                      onClick={() => setSpecContent('')}
                      className="text-neutral-500 hover:text-neutral-300"
                    >
                      Clear
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* 3. Central Big Editor Card (Full-width & Spacious) */}
            <div className="rounded-2xl border border-white/10 bg-[#090a0f] overflow-hidden shadow-lg">
              {/* Editor Header Bar */}
              <div className="flex items-center justify-between border-b border-white/5 bg-white/[0.02] px-4 py-2 text-xs">
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${spec ? 'bg-emerald-400' : 'bg-amber-400'}`} />
                  <span className="font-mono text-neutral-200 font-medium">
                    {file?.name || uploadedMeta?.name || (spec ? 'petstore-openapi.json' : 'specification.yaml')}
                  </span>
                  <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] uppercase font-mono text-neutral-400">
                    {language}
                  </span>
                </div>
              </div>

              {/* Monaco Editor Canvas */}
              <div className="h-[360px] min-h-0">
                <Editor
                  height="100%"
                  language={language}
                  theme="vs-dark"
                  value={activeCode || '# Specification Preview\n# Select a file, paste YAML/JSON, or import from URL.'}
                  onMount={(editor) => {
                    editorRef.current = editor;
                  }}
                  onChange={(val) => {
                    if (mode === 'paste') setSpecContent(val || '');
                  }}
                  options={{
                    readOnly: mode !== 'paste',
                    minimap: { enabled: false },
                    fontSize: 12,
                    lineNumbers: 'on',
                    scrollBeyondLastLine: false,
                    renderLineHighlight: 'none',
                    wordWrap: 'on',
                    automaticLayout: true,
                  }}
                />
              </div>

              {file?.name.toLowerCase().endsWith('.pdf') && (
                <div className="border-t border-white/5 px-4 py-2 text-[11px] text-neutral-500">
                  PDF documents are parsed server-side; preview reflects extracted representation.
                </div>
              )}
            </div>

            {/* 4. Specification Analysis Card (Below Editor) */}
            <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm font-semibold text-white">Specification Analysis</span>
                <StatusBadge
                  status={spec ? validation.status : (file ? 'ready' : 'draft')}
                  label={spec ? validation.label : (file ? 'READY' : 'STANDBY')}
                />
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                {/* Metric 1: Format */}
                <div className="rounded-xl border border-white/5 bg-white/[0.02] p-2.5">
                  <div className="flex items-center gap-1.5 text-emerald-400 text-xs font-semibold">
                    <Check className="h-3.5 w-3.5 shrink-0" />
                    <span className="truncate">{detectedFormat}</span>
                  </div>
                  <p className="mt-1 text-[11px] text-neutral-500 truncate">Detected automatically</p>
                </div>

                {/* Metric 2: Endpoints */}
                <div className="rounded-xl border border-white/5 bg-white/[0.02] p-2.5">
                  <div className="flex items-center gap-1.5 text-emerald-400 text-xs font-semibold">
                    <Check className="h-3.5 w-3.5 shrink-0" />
                    <span className="truncate">{endpointCount} endpoints</span>
                  </div>
                  <p className="mt-1 text-[11px] text-neutral-500 truncate">
                    {endpointCount > 0 ? 'Ready for graphing' : 'Discovered routes'}
                  </p>
                </div>

                {/* Metric 3: Schemas */}
                <div className="rounded-xl border border-white/5 bg-white/[0.02] p-2.5">
                  <div className="flex items-center gap-1.5 text-emerald-400 text-xs font-semibold">
                    <Check className="h-3.5 w-3.5 shrink-0" />
                    <span className="truncate">{schemaCount} schemas</span>
                  </div>
                  <p className="mt-1 text-[11px] text-neutral-500 truncate">
                    {schemaCount > 0 ? 'Entities discovered' : 'Data models & DTOs'}
                  </p>
                </div>

                {/* Metric 4: Authentication */}
                <div className="rounded-xl border border-white/5 bg-white/[0.02] p-2.5">
                  <div className="flex items-center gap-1.5 text-emerald-400 text-xs font-semibold">
                    <Check className="h-3.5 w-3.5 shrink-0" />
                    <span className="truncate">
                      {authSchemes.length > 0 ? `${authSchemes[0]} auth` : 'API key auth'}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] text-neutral-500 truncate">
                    {authSchemes.length > 0 ? `${authSchemes.join(', ')} supported` : 'petstore_auth supported'}
                  </p>
                </div>
              </div>

              {warningsCount(deprecated, missingSummary, lowConfidence) > 0 && (
                <div className="mt-3 flex items-center gap-2 text-[11px] text-amber-400/90 border-t border-white/5 pt-2">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                  <span>{warningsCount(deprecated, missingSummary, lowConfidence)} non-fatal schema warnings flagged</span>
                </div>
              )}
            </div>

            {/* Pipeline Stage Preview (What happens next?) */}
            <div className="pt-2">
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral-400">
                What happens next?
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
                {NEXT_STAGES.map((stage, i) => (
                  <div key={stage.title} className={`${cardCls} relative p-3.5`}>
                    <div className="mb-1 flex items-center gap-2">
                      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-white/5 text-[10px] font-mono text-neutral-400">
                        {i + 1}
                      </span>
                      <span className="text-xs font-semibold text-white">{stage.title}</span>
                    </div>
                    <p className="text-[11px] leading-relaxed text-neutral-500">{stage.desc}</p>
                    {i < NEXT_STAGES.length - 1 && (
                      <ArrowRight className="absolute -right-2.5 top-1/2 hidden h-3.5 w-3.5 -translate-y-1/2 text-neutral-700 xl:block" />
                    )}
                  </div>
                ))}
              </div>
            </div>
          </>
        )}

        {/* --- SubTab 2: Detailed Analysis View --- */}
        {subTab === 'analysis' && (
          <div className="space-y-4">
            <div className={`${cardCls} p-5`}>
              <div className="mb-4 flex items-center justify-between border-b border-white/5 pb-3">
                <div>
                  <h3 className="text-sm font-semibold text-white">Full Specification Analysis</h3>
                  <p className="text-xs text-neutral-400">
                    Deterministic analysis performed on normalized schema structure.
                  </p>
                </div>
                <StatusBadge status={validation.status} label={validation.label} />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-5">
                <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3 text-center">
                  <div className="text-xl font-bold text-white">{endpointCount}</div>
                  <div className="text-xs text-neutral-400">Discovered Endpoints</div>
                </div>
                <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3 text-center">
                  <div className="text-xl font-bold text-white">{schemaCount}</div>
                  <div className="text-xs text-neutral-400">Models & Schemas</div>
                </div>
                <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3 text-center">
                  <div className="text-xl font-bold text-white">{authSchemes.length}</div>
                  <div className="text-xs text-neutral-400">Security Schemes</div>
                </div>
              </div>

              <div className="space-y-2">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-neutral-500">Validation Checks</h4>
                <div className="space-y-2">
                  <div className="flex items-center gap-2.5 text-sm text-neutral-300">
                    <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
                    <span>Schema syntax parsed without critical errors</span>
                  </div>
                  <div className="flex items-center gap-2.5 text-sm text-neutral-300">
                    <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
                    <span>Authentication configurations extracted: {authSchemes.length > 0 ? authSchemes.join(', ') : 'Public routes'}</span>
                  </div>
                  <div className="flex items-center gap-2.5 text-sm text-neutral-300">
                    <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
                    <span>Deterministic format identified as {detectedFormat}</span>
                  </div>
                </div>
              </div>

              {(deprecated > 0 || missingSummary > 0 || lowConfidence > 0) && (
                <div className="mt-5 border-t border-white/5 pt-4">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-amber-400 mb-2">Warnings & Advisories</h4>
                  <ul className="space-y-1.5 text-xs text-neutral-400">
                    {deprecated > 0 && (
                      <li className="flex items-center gap-2 text-amber-300">
                        <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                        <span>{deprecated} deprecated endpoint{deprecated === 1 ? '' : 's'} discovered.</span>
                      </li>
                    )}
                    {missingSummary > 0 && (
                      <li className="flex items-center gap-2 text-neutral-400">
                        <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-neutral-500" />
                        <span>{missingSummary} endpoint{missingSummary === 1 ? '' : 's'} missing human-readable summary.</span>
                      </li>
                    )}
                    {lowConfidence > 0 && (
                      <li className="flex items-center gap-2 text-amber-300">
                        <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                        <span>{lowConfidence} low-confidence extracted parameter{lowConfidence === 1 ? '' : 's'}.</span>
                      </li>
                    )}
                  </ul>
                </div>
              )}
              <div className="mt-5 flex items-center justify-between border-t border-white/5 pt-4">
                <span className="text-xs text-neutral-400">
                  Ready to construct topological execution plan
                </span>
                <button
                  type="button"
                  onClick={onContinue}
                  className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-black font-semibold text-xs transition-colors"
                >
                  <span>Continue to Dependency Graph</span>
                  <ArrowRight className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </div>
        )}

        {/* --- SubTab 3: History View --- */}
        {subTab === 'history' && (
          <div className="space-y-4">
            <div className={`${cardCls} p-5`}>
              <div className="mb-4 flex items-center justify-between border-b border-white/5 pb-3">
                <div>
                  <h3 className="text-sm font-semibold text-white">Specification Revisions</h3>
                  <p className="text-xs text-neutral-400">
                    Audit log of uploaded specifications and versions for this workspace.
                  </p>
                </div>
                <History className="h-4 w-4 text-neutral-400" />
              </div>

              <div className="space-y-3">
                <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-3 flex items-center justify-between">
                  <div>
                    <div className="text-xs font-semibold text-white flex items-center gap-2">
                      <span className="h-2 w-2 rounded-full bg-emerald-400" />
                      <span>{file?.name || uploadedMeta?.name || 'Active Specification'}</span>
                      <span className="rounded bg-emerald-500/20 text-emerald-400 text-[10px] px-1.5 py-0.2">ACTIVE</span>
                    </div>
                    <div className="text-[11px] text-neutral-400 mt-1">
                      {detectedFormat} · {endpointCount} routes discovered
                    </div>
                  </div>
                  <span className="text-[11px] text-neutral-500 font-mono">Current</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Persistent Fixed Action Footer — Always visible at bottom of Stage 1 */}
      <div className="shrink-0 border-t border-white/10 bg-[#0c0d12]/95 px-5 py-3.5 backdrop-blur-md flex items-center justify-between gap-3 shadow-[0_-4px_16px_rgba(0,0,0,0.5)] z-10">
        <button
          type="button"
          onClick={onReset}
          className={btnGhost}
          disabled={phase === 'working'}
        >
          <RotateCcw className="h-4 w-4" /> Reset
        </button>

        {phase === 'success' || spec ? (
          <button
            type="button"
            onClick={onContinue}
            className={btnPrimary}
          >
            Continue to Dependencies <ArrowRight className="h-4 w-4" />
          </button>
        ) : (
          <button
            type="button"
            onClick={onUpload}
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
  );
};

/* Helper for counting warnings */
function warningsCount(deprecated: number, missingSummary: number, lowConfidence: number): number {
  return (deprecated > 0 ? 1 : 0) + (missingSummary > 0 ? 1 : 0) + (lowConfidence > 0 ? 1 : 0);
}
