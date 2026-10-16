import React, { useState, useMemo } from 'react';
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCircle2,
  Copy,
  Download,
  FileCode2,
  FileText,
  KeyRound,
  Layers,
  Loader2,
  Maximize2,
  Minus,
  MoreVertical,
  Network,
  Plus,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { ApiSpec, DependencyGraph, DependencyNode, SpecEndpoint } from '../../lib/types';
import { btnGhost, btnPrimary, cardCls, EmptyState, ErrorBanner } from '../../components/ui';
import { NormalizedSpec, specFormat, specVersion } from '../../lib/format';

const METHOD_STYLES: Record<string, string> = {
  GET: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
  POST: 'bg-sky-500/10 text-sky-400 border-sky-500/30',
  PUT: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  PATCH: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  DELETE: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
};

export const MethodChip: React.FC<{ method: string }> = ({ method }) => (
  <span
    className={`inline-flex shrink-0 items-center rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-bold ${
      METHOD_STYLES[method.toUpperCase()] || 'bg-white/5 text-neutral-400 border-white/15'
    }`}
  >
    {method.toUpperCase()}
  </span>
);

export interface ResourceGroup {
  resource: string;
  nodes: DependencyNode[];
  edgeCounts: Map<string, { in?: number; out: number; targets: string[] }>;
}

export interface DependenciesTabProps {
  graph: DependencyGraph | null;
  resourceGroups: ResourceGroup[];
  spec: ApiSpec | null;
  endpoints?: SpecEndpoint[];
  planBusy: boolean;
  planApproved: boolean;
  planError: string;
  pausedRunId: string | null;
  onApprovePlan: () => void;
  onViewPlanDoc: () => void;
  onGoToIngest: () => void;
  onContinueToTools: () => void;
  onDismissError: () => void;
}

type SubNavTab = 'topology' | 'dependencies' | 'contracts' | 'security';
type GraphFilter = 'all' | 'auth' | 'params' | 'data';
type TopologyView = 'domains' | 'methods' | 'risk';

export const DependenciesTab: React.FC<DependenciesTabProps> = ({
  graph,
  resourceGroups,
  spec,
  endpoints = [],
  planBusy,
  planApproved,
  planError,
  pausedRunId,
  onApprovePlan,
  onViewPlanDoc,
  onGoToIngest,
  onContinueToTools,
  onDismissError,
}) => {
  const [activeSubTab, setActiveSubTab] = useState<SubNavTab>('topology');
  const [graphFilter, setGraphFilter] = useState<GraphFilter>('all');
  const [topologyView, setTopologyView] = useState<TopologyView>('domains');
  const [selectedEntity, setSelectedEntity] = useState<string | null>(null);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const [copiedToast, setCopiedToast] = useState(false);

  // Parse raw normalized spec
  const rawSpec = useMemo(() => (spec?.raw_normalized ?? {}) as NormalizedSpec, [spec]);

  const specMeta = useMemo(() => {
    const title = spec?.title || rawSpec.info?.title || 'OpenAPI Spec';
    const fmt = specFormat(rawSpec);
    const ver = specVersion(rawSpec);
    return {
      title,
      format: fmt,
      version: ver !== '—' ? `v${ver}` : 'v3.0',
      subtitle: `${fmt.toLowerCase().replace(/\s+/g, '-')} · ${ver !== '—' ? `v${ver}` : 'v3.0'}`,
    };
  }, [spec, rawSpec]);

  // Detected Auth info
  const authInfo = useMemo(() => {
    const schemes = rawSpec.components?.securitySchemes ?? rawSpec.securityDefinitions ?? {};
    const entries = Object.entries(schemes);
    if (entries.length === 0) {
      return { title: 'No Auth Detected', subtitle: 'Public endpoints', type: 'none', raw: null };
    }
    const [name, def] = entries[0];
    const d = (def || {}) as Record<string, unknown>;
    const type = String(d.type || 'apiKey');
    let subtitle = '';
    if (type.toLowerCase().includes('apikey')) {
      subtitle = `${d.in || 'header'}: ${d.name || name}`;
    } else if (type.toLowerCase().includes('http')) {
      subtitle = `${d.scheme || 'bearer'} token`;
    } else if (type.toLowerCase().includes('oauth')) {
      subtitle = 'OAuth 2.0 flows';
    } else {
      subtitle = `${name} auth`;
    }
    const formattedTitle = name
      .replace(/[_-]/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
    return { title: `${formattedTitle} Auth`, subtitle, type, name, raw: entries };
  }, [rawSpec]);

  // Derived metrics
  const totalEndpoints = useMemo(() => {
    return graph?.nodes?.length || endpoints.length || resourceGroups.reduce((acc, g) => acc + g.nodes.length, 0);
  }, [graph, endpoints, resourceGroups]);

  const totalEntities = resourceGroups.length;
  const totalDependencies = graph?.edges?.length || 0;

  const safetyFlagsCount = useMemo(() => {
    if (graph?.nodes?.length) {
      return graph.nodes.filter(n => n.is_destructive).length;
    }
    return endpoints.filter(e => e.method.toUpperCase() === 'DELETE').length;
  }, [graph, endpoints]);

  // Top entities for canvas display
  const canvasEntities = useMemo(() => {
    return resourceGroups.slice(0, 3);
  }, [resourceGroups]);

  // Auto-select first entity if none selected
  const activeEntityKey = selectedEntity || canvasEntities[0]?.resource || null;

  // Zoom handlers
  const handleZoomIn = () => setZoomLevel(prev => Math.min(1.3, prev + 0.1));
  const handleZoomOut = () => setZoomLevel(prev => Math.max(0.8, prev - 0.1));
  const handleZoomReset = () => setZoomLevel(1);

  // Export dependency graph as JSON
  const handleExportGraph = () => {
    if (!graph && resourceGroups.length === 0) return;
    const exportData = {
      spec_title: specMeta.title,
      spec_format: specMeta.format,
      spec_version: specMeta.version,
      auth: authInfo,
      metrics: {
        total_endpoints: totalEndpoints,
        total_entities: totalEntities,
        total_dependencies: totalDependencies,
        safety_flags: safetyFlagsCount,
      },
      graph: graph || { nodes: [], edges: [] },
      entities: resourceGroups.map(g => ({
        resource: g.resource,
        endpoint_count: g.nodes.length,
        endpoints: g.nodes.map(n => ({
          method: n.method,
          path: n.path,
          label: n.label,
          is_destructive: n.is_destructive,
        })),
      })),
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${specMeta.title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-dependency-graph.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setCopiedToast(true);
    setTimeout(() => setCopiedToast(false), 2500);
  };

  const handleCopyGraphJson = () => {
    if (!graph) return;
    navigator.clipboard.writeText(JSON.stringify(graph, null, 2));
    setCopiedToast(true);
    setMoreMenuOpen(false);
    setTimeout(() => setCopiedToast(false), 2500);
  };

  // Groupings for 'methods' and 'risk' views
  const methodGroups = useMemo(() => {
    const allNodes = graph?.nodes?.length
      ? graph.nodes
      : endpoints.map(e => ({
          id: e.id,
          label: e.summary || `${e.method} ${e.path}`,
          method: e.method,
          path: e.path,
          is_destructive: e.method.toUpperCase() === 'DELETE',
        }));

    const map = new Map<string, typeof allNodes>();
    for (const node of allNodes) {
      const m = node.method.toUpperCase();
      const list = map.get(m) || [];
      list.push(node);
      map.set(m, list);
    }
    const order = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];
    return order
      .filter(m => map.has(m))
      .map(m => ({ method: m, nodes: map.get(m)! }));
  }, [graph, endpoints]);

  const riskGroups = useMemo(() => {
    const allNodes = graph?.nodes?.length
      ? graph.nodes
      : endpoints.map(e => ({
          id: e.id,
          label: e.summary || `${e.method} ${e.path}`,
          method: e.method,
          path: e.path,
          is_destructive: e.method.toUpperCase() === 'DELETE',
        }));

    const destructive = allNodes.filter(n => n.is_destructive || n.method.toUpperCase() === 'DELETE');
    const mutating = allNodes.filter(n => !destructive.includes(n) && ['POST', 'PUT', 'PATCH'].includes(n.method.toUpperCase()));
    const readOnly = allNodes.filter(n => ['GET', 'HEAD', 'OPTIONS'].includes(n.method.toUpperCase()));

    return [
      {
        key: 'destructive',
        label: 'High Risk / Destructive',
        subtitle: 'State deletions and irreversible operations',
        badgeColor: 'border-rose-500/30 bg-rose-500/10 text-rose-400',
        nodes: destructive,
      },
      {
        key: 'mutating',
        label: 'State Mutation',
        subtitle: 'Entity creations, updates and partial patches',
        badgeColor: 'border-amber-500/30 bg-amber-500/10 text-amber-400',
        nodes: mutating,
      },
      {
        key: 'readonly',
        label: 'Idempotent / Safe Read',
        subtitle: 'Read queries and status retrievals',
        badgeColor: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400',
        nodes: readOnly,
      },
    ].filter(g => g.nodes.length > 0);
  }, [graph, endpoints]);

  return (
    <div className="flex flex-col h-full min-h-0 bg-[#07080c] text-white">
      {/* Toast Notification */}
      {copiedToast && (
        <div className="fixed top-5 right-5 z-50 rounded-xl border border-emerald-500/30 bg-[#0d1210] px-4 py-2.5 text-xs text-emerald-300 shadow-2xl flex items-center gap-2 animate-in fade-in slide-in-from-top-2">
          <Check className="h-4 w-4 text-emerald-400" />
          <span>Dependency graph exported successfully</span>
        </div>
      )}

      {/* Main Scrollable Content */}
      <div className="flex-1 min-h-0 overflow-y-auto p-5 sm:p-6 space-y-6">
        {/* Top Header: Dependency Intelligence */}
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-white flex items-center gap-2">
              Dependency Intelligence
            </h1>
            <p className="text-xs text-neutral-400 mt-0.5">
              API topology, relationships, contracts and execution dependencies
            </p>
          </div>

          <div className="flex items-center gap-2 relative">
            <button
              onClick={handleExportGraph}
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg border border-white/10 bg-white/[0.04] hover:bg-white/[0.08] text-xs font-medium text-white transition-colors"
            >
              <ArrowUpRight className="h-3.5 w-3.5 text-neutral-400" />
              <span>Export Graph</span>
            </button>

            {pausedRunId && !planApproved && (
              <button
                onClick={onApprovePlan}
                disabled={planBusy}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/20 hover:bg-emerald-500/30 text-xs font-medium text-emerald-300 transition-colors"
              >
                {planBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                <span>Approve Topology</span>
              </button>
            )}

            {/* More Menu Dropdown */}
            <div className="relative">
              <button
                onClick={() => setMoreMenuOpen(prev => !prev)}
                className="p-1.5 rounded-lg border border-white/10 bg-white/[0.04] hover:bg-white/[0.08] text-neutral-400 hover:text-white transition-colors"
                aria-label="More options"
              >
                <MoreVertical className="h-4 w-4" />
              </button>

              {moreMenuOpen && (
                <div className="absolute right-0 top-full mt-1.5 w-48 rounded-xl border border-white/15 bg-[#0f1017] p-1.5 shadow-2xl z-40 text-xs">
                  <button
                    onClick={() => {
                      setMoreMenuOpen(false);
                      onViewPlanDoc();
                    }}
                    className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-neutral-300 hover:text-white hover:bg-white/10 text-left transition-colors"
                  >
                    <FileText className="h-3.5 w-3.5 text-neutral-400" />
                    <span>View Topology Doc</span>
                  </button>
                  <button
                    onClick={handleCopyGraphJson}
                    className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-neutral-300 hover:text-white hover:bg-white/10 text-left transition-colors"
                  >
                    <Copy className="h-3.5 w-3.5 text-neutral-400" />
                    <span>Copy Graph JSON</span>
                  </button>
                  {pausedRunId && !planApproved && (
                    <button
                      onClick={() => {
                        setMoreMenuOpen(false);
                        onApprovePlan();
                      }}
                      className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-emerald-400 hover:bg-emerald-500/10 text-left transition-colors"
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      <span>Approve Topology</span>
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 4-Stat Metric Summary Bar */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-4 py-3 border-y border-white/10">
          <div className="px-3">
            <span className="block text-[10px] font-mono tracking-wider uppercase text-neutral-400">
              ENDPOINTS
            </span>
            <span className="block text-2xl font-bold tracking-tight text-white mt-0.5">
              {totalEndpoints}
            </span>
          </div>

          <div className="px-3 border-l border-white/5 sm:border-white/10">
            <span className="block text-[10px] font-mono tracking-wider uppercase text-neutral-400">
              ENTITIES
            </span>
            <span className="block text-2xl font-bold tracking-tight text-white mt-0.5">
              {totalEntities}
            </span>
          </div>

          <div className="px-3 border-t sm:border-t-0 border-l-0 sm:border-l border-white/5 sm:border-white/10 pt-2 sm:pt-0">
            <span className="block text-[10px] font-mono tracking-wider uppercase text-neutral-400">
              DEPENDENCIES
            </span>
            <span className="block text-2xl font-bold tracking-tight text-emerald-400 mt-0.5">
              {totalDependencies}
            </span>
          </div>

          <div className="px-3 border-t sm:border-t-0 border-l border-white/5 sm:border-white/10 pt-2 sm:pt-0">
            <span className="block text-[10px] font-mono tracking-wider uppercase text-neutral-400">
              SAFETY FLAGS
            </span>
            <span className="block text-2xl font-bold tracking-tight text-amber-400 mt-0.5">
              {safetyFlagsCount}
            </span>
          </div>
        </div>

        {/* Sub-Navigation Tabs */}
        <div className="flex items-center gap-1.5">
          {(['topology', 'dependencies', 'contracts', 'security'] as SubNavTab[]).map(tab => {
            const isActive = activeSubTab === tab;
            return (
              <button
                key={tab}
                type="button"
                onClick={() => setActiveSubTab(tab)}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-medium capitalize transition-all ${
                  isActive
                    ? 'border border-white/20 bg-white/10 text-white shadow-sm'
                    : 'text-neutral-400 hover:text-neutral-200 hover:bg-white/[0.04]'
                }`}
              >
                {tab}
              </button>
            );
          })}
        </div>

        {planError && <ErrorBanner message={planError} onDismiss={onDismissError} />}

        {/* TAB 1: TOPOLOGY VIEW */}
        {activeSubTab === 'topology' && (
          <div className="space-y-6">
            {/* SECTION 1: DEPENDENCY GRAPH */}
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold tracking-tight text-white">Dependency Graph</h2>
                  <p className="text-xs text-neutral-400">
                    Resolved relationships between API resources and execution dependencies
                  </p>
                </div>

                {/* Filters */}
                <div className="flex items-center gap-1 bg-white/[0.02] border border-white/5 rounded-lg p-0.5">
                  {(['all', 'auth', 'params', 'data'] as GraphFilter[]).map(f => {
                    const isActive = graphFilter === f;
                    return (
                      <button
                        key={f}
                        type="button"
                        onClick={() => setGraphFilter(f)}
                        className={`px-2.5 py-1 rounded-md text-xs font-medium capitalize transition-all ${
                          isActive
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                            : 'text-neutral-400 hover:text-white'
                        }`}
                      >
                        {f}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Interactive Canvas Box */}
              <div className="relative rounded-2xl border border-white/10 bg-[#050609] p-4 sm:p-6 overflow-hidden min-h-[350px]">
                {/* Background Grid */}
                <div
                  className="absolute inset-0 pointer-events-none opacity-40"
                  style={{
                    backgroundImage: `
                      linear-gradient(to right, rgba(255, 255, 255, 0.05) 1px, transparent 1px),
                      linear-gradient(to bottom, rgba(255, 255, 255, 0.05) 1px, transparent 1px)
                    `,
                    backgroundSize: '24px 24px',
                  }}
                />

                {/* Floating Canvas Controls: Zoom */}
                <div className="absolute top-4 right-4 z-20 flex items-center bg-[#0d0e14]/90 border border-white/15 rounded-xl shadow-lg backdrop-blur-md p-0.5">
                  <button
                    onClick={handleZoomIn}
                    className="p-1.5 text-neutral-400 hover:text-white transition-colors"
                    title="Zoom in"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={handleZoomOut}
                    className="p-1.5 text-neutral-400 hover:text-white transition-colors border-l border-white/10"
                    title="Zoom out"
                  >
                    <Minus className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={handleZoomReset}
                    className="p-1.5 text-neutral-400 hover:text-white transition-colors border-l border-white/10"
                    title="Reset view"
                  >
                    <Maximize2 className="h-3.5 w-3.5" />
                  </button>
                </div>

                {/* Zoomable Canvas Inner Container */}
                <div
                  className="relative w-full transition-transform duration-150 origin-top"
                  style={{ transform: `scale(${zoomLevel})` }}
                >
                  <svg
                    className="w-full h-auto min-h-[340px] overflow-visible"
                    viewBox="0 0 820 340"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                  >
                    <defs>
                      <filter id="emerald-glow" x="-20%" y="-20%" width="140%" height="140%">
                        <feDropShadow dx="0" dy="0" stdDeviation="4" floodColor="#10b981" floodOpacity="0.5" />
                      </filter>
                    </defs>

                    {/* CONNECTING BEZIER CURVES */}
                    {/* Path 1: Source (200, 68) -> Entity 1 (320, 58) */}
                    <path
                      d="M 200 68 C 260 68, 260 58, 320 58"
                      stroke="#10b981"
                      strokeWidth="2"
                      filter="url(#emerald-glow)"
                      className={`transition-opacity duration-200 ${
                        ['all', 'data'].includes(graphFilter) ? 'opacity-100' : 'opacity-15'
                      }`}
                    />
                    {/* Label Pill 1 */}
                    {['all', 'data'].includes(graphFilter) && (
                      <g transform="translate(242, 53)">
                        <rect width="40" height="18" rx="4" fill="#07080c" stroke="#10b981" strokeWidth="1" />
                        <text x="20" y="12" fill="#34d399" fontSize="9" fontWeight="600" textAnchor="middle" fontFamily="monospace">
                          schema
                        </text>
                      </g>
                    )}

                    {/* Path 2: Entity 1 (500, 58) -> Entity 3 (620, 98) */}
                    <path
                      d="M 500 58 C 560 58, 560 98, 620 98"
                      stroke="#10b981"
                      strokeWidth="2"
                      filter="url(#emerald-glow)"
                      className={`transition-opacity duration-200 ${
                        ['all', 'params'].includes(graphFilter) ? 'opacity-100' : 'opacity-15'
                      }`}
                    />
                    {/* Label Pill 2 */}
                    {['all', 'params'].includes(graphFilter) && (
                      <g transform="translate(538, 70)">
                        <rect width="56" height="18" rx="4" fill="#07080c" stroke="#10b981" strokeWidth="1" />
                        <text x="28" y="12" fill="#34d399" fontSize="9" fontWeight="600" textAnchor="middle" fontFamily="monospace">
                          path param
                        </text>
                      </g>
                    )}

                    {/* Path 3: Security (200, 228) -> Entity 2 (320, 228) */}
                    <path
                      d="M 200 228 C 260 228, 260 228, 320 228"
                      stroke="#71717a"
                      strokeWidth="1.5"
                      strokeDasharray="4 4"
                      className={`transition-opacity duration-200 ${
                        ['all', 'auth'].includes(graphFilter) ? 'opacity-100' : 'opacity-15'
                      }`}
                    />
                    {/* Label Pill 3 */}
                    {['all', 'auth'].includes(graphFilter) && (
                      <g transform="translate(248, 219)">
                        <rect width="32" height="18" rx="4" fill="#07080c" stroke="#71717a" strokeWidth="1" />
                        <text x="16" y="12" fill="#a1a1aa" fontSize="9" fontWeight="600" textAnchor="middle" fontFamily="monospace">
                          auth
                        </text>
                      </g>
                    )}

                    {/* Path 4: Entity 2 (500, 228) -> Output (620, 248) */}
                    <path
                      d="M 500 228 C 560 228, 560 248, 620 248"
                      stroke="#71717a"
                      strokeWidth="1.5"
                      strokeDasharray="4 4"
                      className={`transition-opacity duration-200 ${
                        ['all', 'data'].includes(graphFilter) ? 'opacity-100' : 'opacity-15'
                      }`}
                    />
                    {/* Label Pill 4 */}
                    {['all', 'data'].includes(graphFilter) && (
                      <g transform="translate(538, 230)">
                        <rect width="52" height="18" rx="4" fill="#07080c" stroke="#71717a" strokeWidth="1" />
                        <text x="26" y="12" fill="#a1a1aa" fontSize="9" fontWeight="600" textAnchor="middle" fontFamily="monospace">
                          response
                        </text>
                      </g>
                    )}

                    {/* Path 5: Entity 3 (710, 136) -> Output (710, 210) */}
                    <path
                      d="M 710 136 C 710 160, 710 180, 710 210"
                      stroke="#10b981"
                      strokeWidth="1.5"
                      strokeDasharray="3 3"
                      className="opacity-40"
                    />

                    {/* NODES AS FOREIGNOBJECT CARDS */}
                    {/* NODE 1: SOURCE */}
                    <foreignObject x="20" y="30" width="180" height="76">
                      <div className="rounded-xl border border-white/10 bg-[#0f1017] p-3 text-left shadow-lg h-full flex flex-col justify-between">
                        <span className="text-[9px] font-mono uppercase tracking-wider text-neutral-400">SOURCE</span>
                        <div>
                          <div className="text-xs font-semibold text-white truncate" title={specMeta.title}>
                            {specMeta.title}
                          </div>
                          <div className="text-[10px] text-neutral-500 font-mono truncate">{specMeta.subtitle}</div>
                        </div>
                      </div>
                    </foreignObject>

                    {/* NODE 2: SECURITY */}
                    <foreignObject x="20" y="190" width="180" height="76">
                      <div className="rounded-xl border border-white/10 bg-[#0f1017] p-3 text-left shadow-lg h-full flex flex-col justify-between">
                        <span className="text-[9px] font-mono uppercase tracking-wider text-neutral-400">SECURITY</span>
                        <div>
                          <div className="text-xs font-semibold text-white truncate" title={authInfo.title}>
                            {authInfo.title}
                          </div>
                          <div className="text-[10px] text-neutral-500 font-mono truncate">{authInfo.subtitle}</div>
                        </div>
                      </div>
                    </foreignObject>

                    {/* NODE 3: ENTITY 1 (e.g. Pet) */}
                    <foreignObject x="320" y="20" width="180" height="76">
                      <div
                        onClick={() => setSelectedEntity(canvasEntities[0]?.resource || null)}
                        className={`rounded-xl p-3 text-left shadow-lg cursor-pointer transition-all h-full flex flex-col justify-between ${
                          activeEntityKey === (canvasEntities[0]?.resource || '')
                            ? 'border-2 border-emerald-400 bg-emerald-950/20 shadow-[0_0_24px_rgba(16,185,129,0.25)] ring-1 ring-emerald-400/50'
                            : 'border border-white/10 bg-[#0f1017] hover:border-white/20'
                        }`}
                      >
                        <span className="text-[9px] font-mono uppercase tracking-wider text-neutral-400">ENTITY</span>
                        <div>
                          <div className="text-xs font-semibold text-white capitalize truncate">
                            {canvasEntities[0]?.resource || 'Domain 1'}
                          </div>
                          <div className="text-[10px] text-neutral-400 font-mono truncate">
                            {canvasEntities[0]?.nodes?.length || 0} endpoints · {canvasEntities[0]?.nodes?.length ? Math.max(1, canvasEntities[0].nodes.length - 1) : 0} relations
                          </div>
                        </div>
                      </div>
                    </foreignObject>

                    {/* NODE 4: ENTITY 2 (e.g. User) */}
                    <foreignObject x="320" y="190" width="180" height="76">
                      <div
                        onClick={() => setSelectedEntity(canvasEntities[1]?.resource || null)}
                        className={`rounded-xl p-3 text-left shadow-lg cursor-pointer transition-all h-full flex flex-col justify-between ${
                          activeEntityKey === (canvasEntities[1]?.resource || '')
                            ? 'border-2 border-emerald-400 bg-emerald-950/20 shadow-[0_0_24px_rgba(16,185,129,0.25)] ring-1 ring-emerald-400/50'
                            : 'border border-white/10 bg-[#0f1017] hover:border-white/20'
                        }`}
                      >
                        <span className="text-[9px] font-mono uppercase tracking-wider text-neutral-400">ENTITY</span>
                        <div>
                          <div className="text-xs font-semibold text-white capitalize truncate">
                            {canvasEntities[1]?.resource || 'Domain 2'}
                          </div>
                          <div className="text-[10px] text-neutral-400 font-mono truncate">
                            {canvasEntities[1]?.nodes?.length || 0} endpoints · {canvasEntities[1]?.nodes?.length ? Math.max(1, canvasEntities[1].nodes.length - 1) : 0} relations
                          </div>
                        </div>
                      </div>
                    </foreignObject>

                    {/* NODE 5: ENTITY 3 (e.g. Store) */}
                    <foreignObject x="620" y="60" width="180" height="76">
                      <div
                        onClick={() => setSelectedEntity(canvasEntities[2]?.resource || null)}
                        className={`rounded-xl p-3 text-left shadow-lg cursor-pointer transition-all h-full flex flex-col justify-between ${
                          activeEntityKey === (canvasEntities[2]?.resource || '')
                            ? 'border-2 border-emerald-400 bg-emerald-950/20 shadow-[0_0_24px_rgba(16,185,129,0.25)] ring-1 ring-emerald-400/50'
                            : 'border border-white/10 bg-[#0f1017] hover:border-white/20'
                        }`}
                      >
                        <span className="text-[9px] font-mono uppercase tracking-wider text-neutral-400">ENTITY</span>
                        <div>
                          <div className="text-xs font-semibold text-white capitalize truncate">
                            {canvasEntities[2]?.resource || 'Domain 3'}
                          </div>
                          <div className="text-[10px] text-neutral-400 font-mono truncate">
                            {canvasEntities[2]?.nodes?.length || 0} endpoints · {canvasEntities[2]?.nodes?.length ? Math.max(1, canvasEntities[2].nodes.length - 1) : 0} relations
                          </div>
                        </div>
                      </div>
                    </foreignObject>

                    {/* NODE 6: OUTPUT (FastMCP Tools) */}
                    <foreignObject x="620" y="210" width="180" height="76">
                      <div className="rounded-xl border border-white/10 bg-[#0f1017] p-3 text-left shadow-lg h-full flex flex-col justify-between">
                        <span className="text-[9px] font-mono uppercase tracking-wider text-neutral-400">OUTPUT</span>
                        <div>
                          <div className="text-xs font-semibold text-white truncate">FastMCP Tools</div>
                          <div className="text-[10px] text-neutral-500 font-mono truncate">
                            {totalEndpoints} tools planned
                          </div>
                        </div>
                      </div>
                    </foreignObject>
                  </svg>
                </div>

                {/* Canvas Legend */}
                <div className="mt-4 pt-3 border-t border-white/5 flex items-center gap-6 text-[11px] text-neutral-400">
                  <div className="flex items-center gap-2">
                    <span className="h-0.5 w-4 bg-emerald-400 rounded-full" />
                    <span>Resolved</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="h-0.5 w-4 border-t border-dashed border-neutral-500" />
                    <span>Dependency</span>
                  </div>
                </div>
              </div>
            </div>

            {/* SECTION 2: API TOPOLOGY */}
            <div className="space-y-4 pt-2">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold tracking-tight text-white">API Topology</h2>
                  <p className="text-xs text-neutral-400">Domain-level view of the API surface</p>
                </div>

                {/* View Switchers: Domains | Methods | Risk */}
                <div className="flex items-center gap-1 bg-white/[0.02] border border-white/5 rounded-lg p-0.5">
                  {(['domains', 'methods', 'risk'] as TopologyView[]).map(v => {
                    const isActive = topologyView === v;
                    return (
                      <button
                        key={v}
                        type="button"
                        onClick={() => setTopologyView(v)}
                        className={`px-2.5 py-1 rounded-md text-xs font-medium capitalize transition-all ${
                          isActive
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                            : 'text-neutral-400 hover:text-white'
                        }`}
                      >
                        {v}
                      </button>
                    );
                  })}
                </div>
              </div>

              {resourceGroups.length === 0 ? (
                <EmptyState
                  icon={<Network className="h-6 w-6" />}
                  title="No topology available yet"
                  description={
                    spec
                      ? 'This specification did not yield any endpoints. Upload a richer specification to build the graph.'
                      : 'Upload an API specification in the Ingest stage to generate the endpoint topology.'
                  }
                  action={
                    <button onClick={onGoToIngest} className={btnPrimary}>
                      Go to Ingest <ArrowRight className="h-4 w-4" />
                    </button>
                  }
                />
              ) : topologyView === 'domains' ? (
                /* DOMAINS VIEW */
                <div className="flex items-stretch gap-3 overflow-x-auto pb-2">
                  {resourceGroups.map(group => {
                    const initial = group.resource.slice(0, 1).toUpperCase();
                    return (
                      <div
                        key={group.resource}
                        className={`${cardCls} w-72 shrink-0 p-4 hover:bg-white/[0.04] flex flex-col`}
                      >
                        <div className="mb-3 flex items-center justify-between">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="w-6 h-6 rounded-md bg-sky-500/15 border border-sky-500/30 text-sky-400 font-bold text-xs flex items-center justify-center shrink-0">
                              {initial}
                            </span>
                            <span className="truncate text-sm font-semibold capitalize text-white">
                              {group.resource}
                            </span>
                          </div>
                          <span className="ml-2 shrink-0 rounded-full bg-white/5 px-2 py-0.5 text-[10px] font-mono text-neutral-400">
                            {group.nodes.length}
                          </span>
                        </div>

                        <div className="space-y-2 flex-1 overflow-y-auto max-h-[360px] pr-1">
                          {group.nodes.map(node => {
                            const deps = group.edgeCounts.get(node.id);
                            return (
                              <div
                                key={node.id}
                                className="rounded-xl border border-white/10 bg-white/[0.02] p-2.5 hover:border-white/20 transition-colors"
                              >
                                <div className="flex items-center gap-2">
                                  <MethodChip method={node.method} />
                                  <span
                                    className="min-w-0 flex-1 truncate font-mono text-[11px] text-neutral-300"
                                    title={node.path}
                                  >
                                    {node.path}
                                  </span>
                                  {node.is_destructive && (
                                    <ShieldAlert
                                      className="h-3.5 w-3.5 shrink-0 text-rose-400"
                                      aria-label="Destructive operation"
                                    />
                                  )}
                                </div>
                                {node.label && node.label !== `${node.method} ${node.path}` && (
                                  <div className="mt-1 truncate text-[11px] text-neutral-400" title={node.label}>
                                    {node.label}
                                  </div>
                                )}
                                {deps && deps.out > 0 && (
                                  <div className="mt-1.5 flex items-start gap-1.5 text-[10px] text-neutral-400">
                                    <ArrowDown className="mt-0.5 h-3 w-3 shrink-0" />
                                    <span className="min-w-0">
                                      depends on {deps.out} endpoint{deps.out === 1 ? '' : 's'}
                                      {deps.targets.length > 0 &&
                                        ` (${deps.targets.join(', ')}${
                                          deps.out > deps.targets.length ? ', …' : ''
                                        })`}
                                    </span>
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : topologyView === 'methods' ? (
                /* METHODS VIEW */
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                  {methodGroups.map(group => (
                    <div key={group.method} className={`${cardCls} p-4 flex flex-col`}>
                      <div className="mb-3 flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <MethodChip method={group.method} />
                          <span className="text-xs text-neutral-400 font-mono">Operations</span>
                        </div>
                        <span className="rounded-full bg-white/5 px-2 py-0.5 text-[10px] font-mono text-neutral-400">
                          {group.nodes.length}
                        </span>
                      </div>
                      <div className="space-y-2 flex-1 overflow-y-auto max-h-[300px] pr-1">
                        {group.nodes.map(node => (
                          <div
                            key={node.id}
                            className="rounded-lg border border-white/5 bg-white/[0.01] p-2 hover:border-white/15"
                          >
                            <div className="font-mono text-[11px] text-neutral-300 truncate" title={node.path}>
                              {node.path}
                            </div>
                            {node.label && (
                              <div className="text-[10px] text-neutral-400 truncate mt-0.5">{node.label}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                /* RISK VIEW */
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {riskGroups.map(group => (
                    <div key={group.key} className={`${cardCls} p-4 flex flex-col`}>
                      <div className="mb-2">
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-semibold text-white">{group.label}</span>
                          <span className={`rounded-full border px-2 py-0.5 text-[10px] font-mono ${group.badgeColor}`}>
                            {group.nodes.length}
                          </span>
                        </div>
                        <p className="text-[11px] text-neutral-400 mt-0.5">{group.subtitle}</p>
                      </div>
                      <div className="space-y-2 flex-1 overflow-y-auto max-h-[300px] mt-2 pr-1">
                        {group.nodes.map(node => (
                          <div
                            key={node.id}
                            className="rounded-lg border border-white/5 bg-white/[0.01] p-2.5 hover:border-white/15"
                          >
                            <div className="flex items-center gap-2">
                              <MethodChip method={node.method} />
                              <span className="font-mono text-[11px] text-neutral-300 truncate" title={node.path}>
                                {node.path}
                              </span>
                            </div>
                            {node.label && (
                              <div className="text-[10px] text-neutral-400 truncate mt-1">{node.label}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* TAB 2: DEPENDENCIES DETAILED CHAINS */}
        {activeSubTab === 'dependencies' && (
          <div className="space-y-4">
            <div>
              <h2 className="text-sm font-semibold text-white">Execution Prerequisite Chains</h2>
              <p className="text-xs text-neutral-400">
                Extracted topological dependencies between API calls based on ID passing and schema inheritance
              </p>
            </div>

            {graph?.edges && graph.edges.length > 0 ? (
              <div className="rounded-xl border border-white/10 bg-white/[0.02] divide-y divide-white/5 overflow-hidden">
                {graph.edges.map((edge, idx) => {
                  const fromNode = graph.nodes.find(n => n.id === edge.from_id);
                  const toNode = graph.nodes.find(n => n.id === edge.to_id);
                  return (
                    <div key={idx} className="p-3.5 flex flex-wrap items-center justify-between gap-3 text-xs">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-neutral-500 font-mono text-[11px]">#{idx + 1}</span>
                        {fromNode && <MethodChip method={fromNode.method} />}
                        <span className="font-mono text-neutral-300 truncate max-w-[200px]" title={fromNode?.path}>
                          {fromNode?.path || edge.from_id}
                        </span>
                        <ArrowRight className="h-3 w-3 text-emerald-400 shrink-0" />
                        {toNode && <MethodChip method={toNode.method} />}
                        <span className="font-mono text-neutral-300 truncate max-w-[200px]" title={toNode?.path}>
                          {toNode?.path || edge.to_id}
                        </span>
                      </div>
                      <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 px-2 py-0.5 text-[10px] font-mono">
                        {edge.relationship || 'prerequisite'}
                      </span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="rounded-xl border border-white/10 bg-white/[0.02] p-8 text-center text-xs text-neutral-400">
                <Network className="h-8 w-8 mx-auto text-neutral-400 mb-2" />
                <p className="font-medium text-neutral-200">No explicit parameter dependencies found</p>
                <p className="text-neutral-400 mt-1">
                  Endpoints can be invoked independently or use session state managed by the MCP server.
                </p>
              </div>
            )}
          </div>
        )}

        {/* TAB 3: CONTRACTS VIEW */}
        {activeSubTab === 'contracts' && (
          <div className="space-y-4">
            <div>
              <h2 className="text-sm font-semibold text-white">Schema Models & Data Contracts</h2>
              <p className="text-xs text-neutral-400">
                Entities, payloads, and parameter schemas defined in the uploaded specification
              </p>
            </div>

            {(() => {
              const schemas = rawSpec.components?.schemas ?? rawSpec.definitions ?? {};
              const entries = Object.entries(schemas);
              if (entries.length === 0) {
                return (
                  <div className="rounded-xl border border-white/10 bg-white/[0.02] p-8 text-center text-xs text-neutral-400">
                    <FileCode2 className="h-8 w-8 mx-auto text-neutral-400 mb-2" />
                    <p className="font-medium text-neutral-200">No explicit schemas found in spec</p>
                    <p className="text-neutral-400 mt-1">
                      Models are inferred directly from request/response parameters on endpoints.
                    </p>
                  </div>
                );
              }

              return (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {entries.map(([name, schemaDef]) => {
                    const s = (schemaDef || {}) as Record<string, unknown>;
                    const props = (s.properties || {}) as Record<string, unknown>;
                    const propKeys = Object.keys(props);
                    const required = Array.isArray(s.required) ? s.required : [];
                    return (
                      <div key={name} className={`${cardCls} p-4`}>
                        <div className="flex items-center justify-between mb-2">
                          <span className="font-mono text-xs font-semibold text-white">{name}</span>
                          <span className="text-[10px] font-mono text-neutral-400 bg-white/5 px-2 py-0.5 rounded-full">
                            {propKeys.length} props
                          </span>
                        </div>
                        <div className="space-y-1 text-[11px] text-neutral-400 max-h-36 overflow-y-auto pr-1">
                          {propKeys.slice(0, 8).map(pk => {
                            const isReq = required.includes(pk);
                            const pObj = (props[pk] || {}) as Record<string, unknown>;
                            const typeStr = String(pObj.type || 'any');
                            return (
                              <div key={pk} className="flex items-center justify-between font-mono">
                                <span className={isReq ? 'text-neutral-200 font-medium' : 'text-neutral-400'}>
                                  {pk} {isReq && <span className="text-rose-400">*</span>}
                                </span>
                                <span className="text-neutral-400 text-[10px]">{typeStr}</span>
                              </div>
                            );
                          })}
                          {propKeys.length > 8 && (
                            <div className="text-[10px] text-neutral-400 pt-1">+{propKeys.length - 8} more properties…</div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              );
            })()}
          </div>
        )}

        {/* TAB 4: SECURITY VIEW */}
        {activeSubTab === 'security' && (
          <div className="space-y-4">
            <div>
              <h2 className="text-sm font-semibold text-white">Security Schemes & Permissions</h2>
              <p className="text-xs text-neutral-400">
                Authentication mechanisms and security scopes defined for this API
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className={`${cardCls} p-5 space-y-3`}>
                <div className="flex items-center gap-2.5">
                  <KeyRound className="h-5 w-5 text-emerald-400" />
                  <div>
                    <h3 className="text-sm font-semibold text-white">{authInfo.title}</h3>
                    <p className="text-xs text-neutral-400">{authInfo.subtitle}</p>
                  </div>
                </div>

                <div className="rounded-xl border border-white/5 bg-white/[0.01] p-3 space-y-2 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-neutral-400">Auth Type</span>
                    <span className="font-mono text-neutral-200 uppercase">{authInfo.type}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-neutral-400">Target Location</span>
                    <span className="font-mono text-neutral-200">{authInfo.subtitle}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-neutral-400">Vault Integration</span>
                    <span className="text-emerald-400 font-medium flex items-center gap-1">
                      <ShieldCheck className="h-3.5 w-3.5" /> Ready for AWS KMS
                    </span>
                  </div>
                </div>
              </div>

              <div className={`${cardCls} p-5 space-y-3`}>
                <div className="flex items-center gap-2.5">
                  <Shield className="h-5 w-5 text-sky-400" />
                  <div>
                    <h3 className="text-sm font-semibold text-white">Access Scopes & Gating</h3>
                    <p className="text-xs text-neutral-400">Autonomous MCP tool execution bounds</p>
                  </div>
                </div>

                <p className="text-xs text-neutral-400 leading-relaxed">
                  FastMCP servers synthesized from this API will inject auth headers securely at runtime from your configured Vault / Environment secrets. Destructive endpoints require human approval gates before execution.
                </p>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Persistent Fixed Action Footer — Always visible at bottom of Stage 2 */}
      <div className="shrink-0 border-t border-white/10 bg-[#0c0d12]/95 px-5 py-3.5 backdrop-blur-md flex flex-wrap items-center justify-between gap-3 shadow-[0_-4px_16px_rgba(0,0,0,0.5)] z-10">
        <div>
          <h3 className="mb-0.5 text-sm font-medium text-white">Ready for FastMCP Synthesis</h3>
          <p className="text-xs text-neutral-400">
            Dependencies, auth schemes, and parameter propagation are mapped. Next, synthesize FastMCP tools with safety badges.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={onViewPlanDoc} className={btnGhost}>
            <FileCode2 className="h-4 w-4" /> Open Graph Details
          </button>
          <button onClick={onContinueToTools} className={btnPrimary}>
            Continue to MCP Tools <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
};
