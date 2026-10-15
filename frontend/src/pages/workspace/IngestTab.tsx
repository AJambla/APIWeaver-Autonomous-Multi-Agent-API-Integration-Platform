import React from 'react';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clipboard,
  FileCode2,
  FileJson,
  FileText,
  FileType,
  Link2,
  Loader2,
  Maximize2,
  RotateCcw,
  Upload,
} from 'lucide-react';
import Editor from '@monaco-editor/react';
import { ApiSpec, SpecEndpoint, UploadResponse } from '../../lib/types';
import { btnGhost, btnPrimary, cardCls, ErrorBanner, inputCls, StatusBadge } from '../../components/ui';
import { NormalizedSpec, specFormat, validationState } from '../../lib/format';

export type UploadMode = 'file' | 'paste' | 'url';
export type UploadPhase = 'idle' | 'working' | 'success' | 'error';

const FORMAT_CHIPS = [
  { label: 'OpenAPI', ext: '.yaml / .json', icon: FileJson },
  { label: 'Swagger', ext: '.yaml / .json', icon: FileCode2 },
  { label: 'Postman', ext: '.json', icon: FileJson },
  { label: 'Markdown', ext: '.md', icon: FileText },
  { label: 'PDF', ext: '.pdf', icon: FileType },
];

const NEXT_STAGES = [
  { title: 'Deterministic Parsing', desc: 'Parse OpenAPI/Swagger specs or extract endpoints via RAG docs.' },
  { title: 'Dependency Graph', desc: 'Extract endpoint topology, parameters, and auth schemes.' },
  { title: 'FastMCP Synthesis', desc: 'Generate typed tools with deterministic safety classification.' },
  { title: 'Sandbox Verification', desc: 'Ephemeral Docker test runner with synthetic HTTP mocks.' },
];

interface UploadDropzoneProps {
  file: File | null;
  onFile: (f: File | null) => void;
  disabled: boolean;
}

const UploadDropzone: React.FC<UploadDropzoneProps> = ({ file, onFile, disabled }) => {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = React.useState(false);

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
          <div className="text-xs text-neutral-500">or click to browse files (OpenAPI, Swagger, Postman, MD, PDF)</div>
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

export interface IngestTabProps {
  file: File | null;
  setFile: (f: File | null) => void;
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
  return (
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
                  onClick={onUrlImport}
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
                onClick={onPreviewExpand}
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

      {showAnalysis && spec && <AnalysisPanel spec={spec} endpoints={endpoints} />}

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
        <button onClick={onReset} className={btnGhost} disabled={phase === 'working'}>
          <RotateCcw className="h-4 w-4" /> Reset
        </button>
        {phase === 'success' || spec ? (
          <button onClick={onContinue} className={btnPrimary}>
            Continue to Dependencies <ArrowRight className="h-4 w-4" />
          </button>
        ) : (
          <button
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
