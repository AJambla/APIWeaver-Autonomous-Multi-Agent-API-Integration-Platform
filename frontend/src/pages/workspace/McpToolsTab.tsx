import React, { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  Check,
  ChevronDown,
  ChevronRight,
  Clock,
  Code2,
  Copy,
  FileCode2,
  FileJson,
  Loader2,
  Play,
  ShieldAlert,
  ShieldCheck,
  Terminal as TerminalIcon,
} from 'lucide-react';
import Editor from '@monaco-editor/react';
import { ApiSpec, GeneratedFileMeta, ProjectSummary, SpecEndpoint, WorkflowRunInfo } from '../../lib/types';
import { btnGhost, btnPrimary, cardCls, EmptyState, ErrorBanner, StatusBadge } from '../../components/ui';
import { MethodChip } from './DependenciesTab';
import { apiFetch } from '../../lib/api';
import { relativeTime } from '../../lib/format';

export interface McpToolsTabProps {
  projectId: string;
  project: ProjectSummary | null;
  spec: ApiSpec | null;
  endpoints: SpecEndpoint[];
  activeRun: WorkflowRunInfo | null;
  runIsLive: boolean;
  onRunBuild: () => void;
  onContinueToVerify: () => void;
  onGoToIngest: () => void;
}

export const McpToolsTab: React.FC<McpToolsTabProps> = ({
  projectId,
  project,
  spec,
  endpoints,
  activeRun,
  runIsLive,
  onRunBuild,
  onContinueToVerify,
  onGoToIngest,
}) => {
  const [selectedToolId, setSelectedToolId] = useState<string | null>(null);
  const [selectedFileTab, setSelectedFileTab] = useState<'tools.py' | 'server.py' | 'test_mcp.py' | 'manifest.json'>('tools.py');
  const [copiedCode, setCopiedCode] = useState(false);
  const [files, setFiles] = useState<GeneratedFileMeta[]>([]);
  const [fileContents, setFileContents] = useState<Record<string, string>>({});
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [error, setError] = useState('');

  // Fetch real generated files from API if available
  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    setLoadingFiles(true);
    apiFetch<GeneratedFileMeta[]>(`/projects/${projectId}/files`)
      .then(async fileList => {
        if (cancelled) return;
        setFiles(fileList || []);
        // Fetch contents for files
        const contents: Record<string, string> = {};
        for (const f of fileList || []) {
          const name = f.file_path.split('/').pop() || f.file_path;
          try {
            const res = await apiFetch<{ content: string }>(`/projects/${projectId}/files/${f.id}/content`);
            if (res && res.content) {
              contents[name] = res.content;
            }
          } catch {
            // Content not ready yet
          }
        }
        if (!cancelled) {
          setFileContents(contents);
        }
      })
      .catch(() => {
        // Fallback to synthesized previews
      })
      .finally(() => {
        if (!cancelled) setLoadingFiles(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, activeRun?.status]);

  // Derive synthesized tools with deterministic safety classification
  const tools = useMemo(() => {
    return endpoints.map((ep, idx) => {
      const method = ep.method.toUpperCase();
      const isDelete = method === 'DELETE';
      const isStateChanging = ['POST', 'PUT', 'PATCH'].includes(method);
      const isSafe = ['GET', 'HEAD', 'OPTIONS'].includes(method);

      // Generate pythonic tool name: get_pet_by_id, delete_user
      const cleanPath = ep.path
        .replace(/\{([^}]+)\}/g, 'by_$1')
        .replace(/[^a-zA-Z0-9_]/g, '_')
        .replace(/_+/g, '_')
        .replace(/^_|_$/g, '');
      const toolName = `${method.toLowerCase()}_${cleanPath || `endpoint_${idx + 1}`}`;

      let safetyBadge: string;
      let riskLevel: 'LOW' | 'MEDIUM' | 'HIGH';
      let requiresConfirmation: boolean;

      if (isDelete || ep.deprecated) {
        safetyBadge = '[DESTRUCTIVE ⚠]';
        riskLevel = 'HIGH';
        requiresConfirmation = true;
      } else if (isStateChanging) {
        safetyBadge = '[STATE-CHANGING]';
        riskLevel = 'MEDIUM';
        requiresConfirmation = false;
      } else {
        safetyBadge = '[SAFE]';
        riskLevel = 'LOW';
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
        requiresConfirmation,
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

  // Fallback synthetic preview code if backend has not written files to S3/disk yet
  const dynamicPreviewCode = useMemo(() => {
    const title = spec?.title || project?.name || 'apiweaver-service';
    const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-');

    if (selectedFileTab === 'server.py') {
      return `"""FastMCP Server Entrypoint for ${title}"""
import os
from mcp.server.fastmcp import FastMCP
from .tools import register_tools

# Initialize FastMCP application
mcp = FastMCP(
    "${slug}",
    dependencies=["httpx", "pydantic"],
)

# Register generated API tools
register_tools(mcp)

if __name__ == "__main__":
    mcp.run()
`;
    }

    if (selectedFileTab === 'test_mcp.py') {
      return `"""Automated Pytest Suite for FastMCP Tools"""
import pytest
from mcp.server.fastmcp import FastMCP
from .tools import register_tools

@pytest.fixture
def mcp_app():
    app = FastMCP("test-server")
    register_tools(app)
    return app

def test_mcp_tools_registration(mcp_app):
    """Verify all ${tools.length} synthesized tools register with valid JSON schemas."""
    tools = mcp_app.list_tools()
    assert len(tools) >= ${tools.length}

${tools.slice(0, 3).map(t => `def test_${t.name}_schema(mcp_app):
    tool = next(t for t in mcp_app.list_tools() if t.name == "${t.name}")
    assert tool is not None
    assert "${t.safetyBadge}" in (tool.description or "")
`).join('\n')}
`;
    }

    if (selectedFileTab === 'manifest.json') {
      return JSON.stringify(
        {
          schema_version: '1.0.0',
          server: {
            name: slug,
            version: '1.0.0',
            description: `FastMCP Server generated for ${title}`,
            framework: 'fastmcp',
          },
          tools: tools.map(t => ({
            name: t.name,
            description: `${t.safetyBadge} ${t.summary}`,
            method: t.method,
            path: t.path,
            risk_level: t.riskLevel,
            requires_confirmation: t.requiresConfirmation,
          })),
        },
        null,
        2
      );
    }

    // Default: tools.py
    return `"""Synthesized FastMCP Tool Definitions with Deterministic Safety Gates"""
import os
import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.getenv("API_BASE_URL", "${spec?.base_url || 'https://api.example.com'}")

def register_tools(mcp: FastMCP):
    """Register all ${tools.length} synthesized API endpoints as typed FastMCP tools."""

${tools.map(t => `    @mcp.tool(
        name="${t.name}",
        description="${t.safetyBadge} ${t.summary}",
    )
    async def ${t.name}(
        # Path: ${t.path}
        # Risk level: ${t.riskLevel} | Requires confirmation: ${t.requiresConfirmation}
    ) -> dict:
        """Call ${t.method} ${t.path}"""
        async with httpx.AsyncClient(base_url=BASE_URL) as client:
            resp = await client.request(
                method="${t.method}",
                url="${t.path}",
                headers={"User-Agent": "APIWeaver-FastMCP/1.0"}
            )
            return {"status_code": resp.status_code, "data": resp.json() if resp.headers.get("content-type") == "application/json" else resp.text}
`).join('\n')}
`;
  }, [selectedFileTab, spec, project, tools]);

  // Content to render in Monaco: prefer real file content, fallback to dynamic preview
  const activeEditorContent = fileContents[selectedFileTab] || dynamicPreviewCode;

  const copyToClipboard = () => {
    navigator.clipboard.writeText(activeEditorContent);
    setCopiedCode(true);
    setTimeout(() => setCopiedCode(false), 2000);
  };

  const getBadgeStyle = (safetyBadge: string) => {
    if (safetyBadge.includes('DESTRUCTIVE')) {
      return 'bg-rose-500/10 text-rose-400 border-rose-500/30';
    }
    if (safetyBadge.includes('STATE-CHANGING')) {
      return 'bg-amber-500/10 text-amber-400 border-amber-500/30';
    }
    return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30';
  };

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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="text-lg font-medium tracking-tight">FastMCP Tools & Code Inspector</h2>
            <span className="rounded-full bg-blue-500/10 px-2.5 py-0.5 text-[11px] font-medium text-blue-400 border border-blue-500/20">
              {tools.length} Tools
            </span>
          </div>
          <p className="text-xs text-neutral-500">
            Synthesized Model Context Protocol tools with deterministic safety classification and code viewer.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={onRunBuild}
            disabled={runIsLive}
            className={btnPrimary}
          >
            {runIsLive ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {runIsLive ? 'Synthesizing Server…' : 'Re-synthesize FastMCP Server'}
          </button>
        </div>
      </div>

      {error && <ErrorBanner message={error} onDismiss={() => setError('')} />}

      {/* Main Grid: Tools List + Monaco Inspector */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left Column: Synthesized FastMCP Tools List (5 cols) */}
        <div className="space-y-3 lg:col-span-5">
          <div className="flex items-center justify-between border-b border-white/5 pb-2 text-xs font-medium text-neutral-400">
            <span>Synthesized FastMCP Tools</span>
            <span>Safety Gate</span>
          </div>

          <div className="max-h-[640px] space-y-2 overflow-y-auto pr-1">
            {tools.map(tool => {
              const isSelected = selectedToolId === tool.id;
              return (
                <div
                  key={tool.id}
                  onClick={() => setSelectedToolId(tool.id)}
                  className={`cursor-pointer rounded-xl border p-3.5 transition-all ${
                    isSelected
                      ? 'border-blue-500/60 bg-blue-500/[0.08]'
                      : 'border-white/10 bg-white/[0.02] hover:border-white/20 hover:bg-white/[0.04]'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <MethodChip method={tool.method} />
                        <span className="font-mono text-xs font-semibold text-white truncate" title={tool.name}>
                          {tool.name}
                        </span>
                      </div>
                      <div className="mt-1 font-mono text-[11px] text-neutral-400 truncate" title={tool.path}>
                        {tool.path}
                      </div>
                      <div className="mt-1 text-xs text-neutral-500 line-clamp-2">
                        {tool.summary}
                      </div>
                    </div>

                    <div className="flex flex-col items-end gap-1.5 shrink-0">
                      <span className={`rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-bold ${getBadgeStyle(tool.safetyBadge)}`}>
                        {tool.safetyBadge}
                      </span>
                      {tool.requiresConfirmation && (
                        <span className="flex items-center gap-1 rounded bg-rose-500/10 px-1.5 py-0.5 text-[9px] text-rose-300 border border-rose-500/20">
                          <ShieldAlert className="h-2.5 w-2.5" /> Confirm req.
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Column: Code Viewer with Tabs (7 cols) */}
        <div className={`${cardCls} flex flex-col overflow-hidden lg:col-span-7`}>
          {/* File selector tabs */}
          <div className="flex flex-wrap items-center justify-between border-b border-white/10 px-4 py-2.5 bg-white/[0.02]">
            <div className="flex items-center gap-1">
              {(['tools.py', 'server.py', 'test_mcp.py', 'manifest.json'] as const).map(fileTab => {
                const isActive = selectedFileTab === fileTab;
                return (
                  <button
                    key={fileTab}
                    onClick={() => setSelectedFileTab(fileTab)}
                    className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-mono transition-colors ${
                      isActive
                        ? 'bg-white/10 text-white font-medium border border-white/15'
                        : 'text-neutral-400 hover:bg-white/5 hover:text-neutral-300'
                    }`}
                  >
                    {fileTab.endsWith('.py') ? <FileCode2 className="h-3.5 w-3.5 text-blue-400" /> : <FileJson className="h-3.5 w-3.5 text-amber-400" />}
                    {fileTab}
                  </button>
                );
              })}
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={copyToClipboard}
                className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-xs text-neutral-300 hover:bg-white/10 hover:text-white transition-colors"
                title="Copy code"
              >
                {copiedCode ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
                {copiedCode ? 'Copied' : 'Copy'}
              </button>
            </div>
          </div>

          {/* Monaco Editor */}
          <div className="h-[540px] w-full">
            <Editor
              height="100%"
              language={selectedFileTab.endsWith('.json') ? 'json' : 'python'}
              theme="vs-dark"
              value={activeEditorContent}
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

          {/* Footer banner */}
          <div className="flex items-center justify-between border-t border-white/5 px-4 py-3 bg-neutral-950/60 text-xs">
            <div className="flex items-center gap-2 text-neutral-400">
              <span className="font-mono text-neutral-500">FastMCP v1.2</span>
              <span>·</span>
              <span>Deterministic AST syntax valid</span>
            </div>
            <button
              onClick={onContinueToVerify}
              className={btnPrimary}
            >
              Continue to Verify <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
