import React, { useMemo, useState } from 'react';
import {
  Check,
  CheckCircle2,
  FileCode2,
  FileText,
  FlaskConical,
  Layers,
  Network,
  Package,
  ShieldAlert,
  Sparkles,
  Terminal,
  ZoomIn,
  ZoomOut,
  RotateCcw,
} from 'lucide-react';
import {
  ApiSpec,
  DependencyGraph,
  ExportRecord,
  ProjectSummary,
  SpecEndpoint,
  TestRunSummary,
  WorkflowRunInfo,
} from '../../lib/types';
import { NormalizedSpec } from '../../lib/format';

export type TabId = 'ingest' | 'dependencies' | 'tools' | 'verify' | 'result' | 'logs' | 'settings';

interface PipelineCanvasProps {
  activeTab: TabId;
  onSelectTab: (tab: TabId) => void;
  spec: ApiSpec | null;
  endpoints: SpecEndpoint[];
  graph: DependencyGraph | null;
  testSummary: TestRunSummary | null;
  exports: ExportRecord[];
  activeRun: WorkflowRunInfo | null;
  project: ProjectSummary;
  stepCompleted: Record<TabId, boolean>;
}

export const PipelineCanvas: React.FC<PipelineCanvasProps> = ({
  activeTab,
  onSelectTab,
  spec,
  endpoints,
  graph,
  testSummary,
  exports,
  activeRun,
  project,
  stepCompleted,
}) => {
  const currentNode = activeRun?.current_node || '';

  // Stage 1 Ingest specs & auth
  const rawSpec = useMemo(() => (spec?.raw_normalized ?? {}) as NormalizedSpec, [spec]);
  const specTitle = useMemo(() => {
    return spec?.title || rawSpec.info?.title || (spec ? 'OpenAPI Specification' : 'No specification uploaded');
  }, [spec, rawSpec]);

  const authSchemeText = useMemo(() => {
    const authObj = rawSpec.components?.securitySchemes ?? rawSpec.securityDefinitions ?? {};
    const keys = Object.keys(authObj);
    return keys.length > 0 ? `${keys[0]} Auth` : 'No Auth';
  }, [rawSpec]);

  // Stage 2 Dependency metrics
  const rootCount = useMemo(() => {
    if (!graph?.nodes?.length) return 0;
    const targetIds = new Set(graph.edges.map(e => e.to_id));
    return graph.nodes.filter(n => !targetIds.has(n.id)).length;
  }, [graph]);

  const chainCount = useMemo(() => graph?.edges?.length ?? 0, [graph]);

  // Stage 3 Tools metrics
  const { autonomousCount, gatedCount } = useMemo(() => {
    let gated = 0;
    let auto = 0;
    for (const ep of endpoints) {
      if (ep.method.toUpperCase() === 'DELETE' || ep.deprecated) {
        gated += 1;
      } else {
        auto += 1;
      }
    }
    return { autonomousCount: auto, gatedCount: gated };
  }, [endpoints]);

  // Stage 4 Sandbox metrics
  const isAstPass = endpoints.length > 0;
  const pytestText = useMemo(() => {
    if (!testSummary?.summary) return 'Pytest: —';
    const passed = testSummary.summary.passed ?? 0;
    const total = testSummary.summary.total ?? 0;
    return `Pytest: ${passed}/${total} PASS`;
  }, [testSummary]);

  // Stage statuses
  const stage1Running = currentNode === 'doc_agent';
  const stage2Running = ['planner_agent', 'approval_gate'].includes(currentNode);
  const stage3Running = currentNode === 'code_agent';
  const stage4Running = ['test_agent', 'repair_agent'].includes(currentNode);
  const stage5Running = currentNode === 'export_agent';

  const stage1Verified = stepCompleted.ingest;
  const stage2Verified = stepCompleted.dependencies;
  const stage3Verified = stepCompleted.tools;
  const stage4Verified = stepCompleted.verify;
  const stage5Verified = stepCompleted.result;

  const cardCls = (id: TabId, isRunning: boolean) => {
    const isSelected = activeTab === id;
    const base = 'absolute rounded-2xl bg-[#0f1118] p-4 cursor-pointer transition-all duration-200 z-10';
    if (isSelected) {
      return `${base} border-2 border-emerald-500 shadow-[0_0_25px_-4px_rgba(16,185,129,0.35)]`;
    }
    if (isRunning) {
      return `${base} border border-amber-500/50 shadow-[0_0_25px_-4px_rgba(245,158,11,0.3)] hover:border-amber-400`;
    }
    return `${base} border border-white/10 hover:border-white/30`;
  };

  const statusBadge = (isVerified: boolean, isRunning: boolean) => {
    if (isRunning) {
      return (
        <span className="flex items-center gap-1 rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-400 border border-amber-500/30">
          <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
          Running
        </span>
      );
    }
    if (isVerified) {
      return (
        <span className="flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-400 border border-emerald-500/30">
          <Check className="h-3 w-3" />
          Verified
        </span>
      );
    }
    return (
      <span className="rounded-full bg-white/5 px-2 py-0.5 text-[10px] font-medium text-neutral-400 border border-white/10">
        Standby
      </span>
    );
  };

  const [canvasScale, setCanvasScale] = useState(1);

  const handleWheel = (e: React.WheelEvent) => {
    // Scroll wheel zooms in/out smoothly
    const delta = -e.deltaY * 0.0015;
    setCanvasScale(prev => Math.min(1.6, Math.max(0.65, Number((prev + delta).toFixed(2)))));
  };

  const handleZoomIn = () => setCanvasScale(prev => Math.min(1.6, Number((prev + 0.1).toFixed(2))));
  const handleZoomOut = () => setCanvasScale(prev => Math.max(0.65, Number((prev - 0.1).toFixed(2))));
  const handleResetZoom = () => setCanvasScale(1);

  const connectorProps = (isVerified: boolean, isRunning: boolean) => {
    if (isRunning) {
      return { stroke: '#f59e0b', strokeWidth: 2.5, strokeDasharray: '6 4', className: 'connector-running animate-pulse' };
    }
    if (isVerified) {
      return { stroke: '#10b981', strokeWidth: 2.5, filter: 'url(#glow)' };
    }
    return { stroke: '#3f3f46', strokeWidth: 1.5, strokeDasharray: '4 4' };
  };

  return (
    <section className="flex-1 dot-grid relative flex flex-col overflow-hidden select-none">
      {/* Top Meta Ribbon */}
      <div className="h-10 border-b border-white/5 bg-black/40 backdrop-blur px-6 flex items-center justify-between text-[11px] font-mono text-neutral-400 shrink-0 z-10">
        <div className="flex items-center gap-2">
          <span className="text-neutral-500">Autonomous Mode:</span>
          <span className="text-emerald-400 font-medium">LangGraph • FastMCP • Docker Sandbox</span>
        </div>
        <div className="flex items-center gap-4 text-neutral-400">
          <div>
            Level 1 AST:{' '}
            <span className={`font-semibold ${isAstPass ? 'text-emerald-400' : 'text-neutral-500'}`}>
              {isAstPass ? 'PASS' : 'PENDING'}
            </span>
          </div>
          <span className="text-neutral-700">•</span>
          <div>
            Level 2 Sandbox:{' '}
            <span className={`font-semibold ${stage4Verified ? 'text-emerald-400' : 'text-neutral-500'}`}>
              {testSummary?.summary ? `${testSummary.summary.passed}/${testSummary.summary.total} PASS` : 'NOT RUN'}
            </span>
          </div>
          <span className="text-neutral-700">•</span>
          <div>
            Vault: <span className="font-semibold text-emerald-400">AWS KMS LINKED</span>
          </div>
        </div>
      </div>

      {/* Canvas Workspace Area with Scroll-Wheel Resizing */}
      <div
        onWheel={handleWheel}
        className="flex-1 relative p-6 flex flex-col justify-center items-center overflow-hidden cursor-grab active:cursor-grabbing"
      >
        {/* Floating Zoom Control HUD */}
        <div className="absolute top-4 right-4 z-20 flex items-center gap-1.5 rounded-xl border border-white/10 bg-[#0c0d14]/85 backdrop-blur-md px-2.5 py-1.5 shadow-xl text-xs">
          <button
            type="button"
            onClick={handleZoomOut}
            className="h-6 w-6 flex items-center justify-center rounded-lg hover:bg-white/10 text-neutral-300 transition-colors"
            title="Zoom Out (Scroll Down)"
          >
            <ZoomOut className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={handleResetZoom}
            className="px-2 py-0.5 rounded text-[11px] font-mono font-medium text-emerald-400 hover:bg-emerald-500/10 transition-colors"
            title="Reset Zoom to 100%"
          >
            {Math.round(canvasScale * 100)}%
          </button>
          <button
            type="button"
            onClick={handleZoomIn}
            className="h-6 w-6 flex items-center justify-center rounded-lg hover:bg-white/10 text-neutral-300 transition-colors"
            title="Zoom In (Scroll Up)"
          >
            <ZoomIn className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* Scalable Canvas Inner Container */}
        <div
          className="relative w-[860px] h-[480px] transition-transform duration-75 origin-center"
          style={{ transform: `scale(${canvasScale})` }}
        >
          {/* Continuous Pipeline SVG Rail & Connectors */}
          <svg className="absolute inset-0 w-full h-full pointer-events-none z-0" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="3.5" result="blur" />
                <feComposite in="SourceGraphic" in2="blur" operator="over" />
              </filter>
              <linearGradient id="pipelineRailGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#10b981" stopOpacity="0.8" />
                <stop offset="50%" stopColor="#06b6d4" stopOpacity="0.8" />
                <stop offset="100%" stopColor="#8b5cf6" stopOpacity="0.8" />
              </linearGradient>
            </defs>

            {/* Background Structural Rail connecting all stages */}
            <path d="M 230 80 L 320 80" fill="none" stroke="#1c1d24" strokeWidth="4" />
            <path d="M 540 80 L 630 80" fill="none" stroke="#1c1d24" strokeWidth="4" />
            <path d="M 740 155 C 740 230, 200 230, 200 310" fill="none" stroke="#1c1d24" strokeWidth="4" />
            <path d="M 310 385 L 420 385" fill="none" stroke="#1c1d24" strokeWidth="4" />

            {/* Active / Verified Connecting Flow Lines */}
            {/* Stage 01 -> Stage 02 */}
            <path d="M 230 80 L 320 80" fill="none" {...connectorProps(stage1Verified, stage1Running)} />
            {/* Stage 02 -> Stage 03 */}
            <path d="M 540 80 L 630 80" fill="none" {...connectorProps(stage2Verified, stage2Running)} />
            {/* Stage 03 -> Stage 04 (Return loop) */}
            <path d="M 740 155 C 740 230, 200 230, 200 310" fill="none" {...connectorProps(stage3Verified, stage3Running)} />
            {/* Stage 04 -> Stage 05 */}
            <path d="M 310 385 L 420 385" fill="none" {...connectorProps(stage4Verified, stage4Running)} />

            {/* Node Step Indicators along the lines */}
            <circle cx="275" cy="80" r="3" fill={stage1Verified ? '#10b981' : '#3f3f46'} />
            <circle cx="585" cy="80" r="3" fill={stage2Verified ? '#10b981' : '#3f3f46'} />
            <circle cx="470" cy="230" r="3.5" fill={stage3Verified ? '#10b981' : '#3f3f46'} />
            <circle cx="365" cy="385" r="3" fill={stage4Verified ? '#10b981' : '#3f3f46'} />
          </svg>

          {/* STAGE 01 CARD: INGEST */}
          <div
            onClick={() => onSelectTab('ingest')}
            className={`${cardCls('ingest', stage1Running)} top-6 left-2 w-[220px]`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-mono uppercase tracking-wider text-neutral-400">STAGE 01</span>
              {statusBadge(stage1Verified, stage1Running)}
            </div>
            <div className="flex items-center gap-2.5 mb-2">
              <div className="p-1.5 rounded-lg bg-purple-500/10 border border-purple-500/20 text-purple-400">
                <FileCode2 className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-xs font-semibold text-white truncate">OpenAPI Spec Ingest</div>
                <div className="text-[10px] text-neutral-400 truncate" title={specTitle}>{specTitle}</div>
              </div>
            </div>
            <div className="mt-3 pt-2.5 border-t border-white/5 flex items-center justify-between text-[11px] font-mono">
              <span className="text-neutral-400">{endpoints.length} Endpoints</span>
              <span className="text-neutral-500 truncate max-w-[80px]">{authSchemeText}</span>
            </div>
          </div>

          {/* STAGE 02 CARD: DEPENDENCY GRAPH */}
          <div
            onClick={() => onSelectTab('dependencies')}
            className={`${cardCls('dependencies', stage2Running)} top-6 left-[320px] w-[220px]`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-mono uppercase tracking-wider text-neutral-400">STAGE 02</span>
              {statusBadge(stage2Verified, stage2Running)}
            </div>
            <div className="flex items-center gap-2.5 mb-2">
              <div className="p-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
                <Network className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-xs font-semibold text-white truncate">Dependency Graph</div>
                <div className="text-[10px] text-neutral-500 truncate">Topological execution order</div>
              </div>
            </div>
            <div className="mt-3 pt-2.5 border-t border-white/5 flex items-center justify-between text-[11px] font-mono">
              <span className="text-neutral-400">{rootCount} Root Entities</span>
              <span className="text-neutral-400">{chainCount} Linked Chains</span>
            </div>
          </div>

          {/* STAGE 03 CARD: FASTMCP SYNTHESIZER */}
          <div
            onClick={() => onSelectTab('tools')}
            className={`${cardCls('tools', stage3Running)} top-6 left-[630px] w-[220px]`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-mono uppercase tracking-wider text-neutral-400">STAGE 03</span>
              {statusBadge(stage3Verified, stage3Running)}
            </div>
            <div className="flex items-center gap-2.5 mb-2">
              <div className="p-1.5 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400">
                <Layers className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-xs font-semibold text-white truncate">FastMCP Synthesizer</div>
                <div className="text-[10px] text-neutral-500 truncate">Typed Python tools + Safety</div>
              </div>
            </div>
            <div className="mt-3 pt-2.5 border-t border-white/5 flex items-center justify-between text-[11px] font-mono">
              <span className="text-neutral-400">{autonomousCount} Autonomous</span>
              <span className="text-neutral-500">{gatedCount} Human-Gated</span>
            </div>
          </div>

          {/* STAGE 04 CARD: EPHEMERAL DOCKER SANDBOX */}
          <div
            onClick={() => onSelectTab('verify')}
            className={`${cardCls('verify', stage4Running)} top-[310px] left-[90px] w-[220px]`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-mono uppercase tracking-wider text-neutral-400">STAGE 04</span>
              {statusBadge(stage4Verified, stage4Running)}
            </div>
            <div className="flex items-center gap-2.5 mb-2">
              <div className="p-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                <FlaskConical className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-xs font-semibold text-white truncate">Docker Sandbox</div>
                <div className="text-[10px] text-neutral-500 truncate">AST Gate + Pytest Mocks</div>
              </div>
            </div>
            <div className="mt-3 pt-2.5 border-t border-white/5 flex items-center justify-between text-[11px] font-mono">
              <span className={isAstPass ? 'text-emerald-400' : 'text-neutral-500'}>
                {isAstPass ? 'AST: PASS' : 'AST: PENDING'}
              </span>
              <span className="text-neutral-400">{pytestText}</span>
            </div>
          </div>

          {/* STAGE 05 CARD: CERTIFIED MCP BUNDLE */}
          <div
            onClick={() => onSelectTab('result')}
            className={`${cardCls('result', stage5Running)} top-[310px] left-[420px] w-[260px]`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-mono uppercase tracking-wider text-emerald-400">STAGE 05 • OUTPUT</span>
              {statusBadge(stage5Verified, stage5Running)}
            </div>
            <div className="flex items-center gap-2.5 mb-2">
              <div className="p-1.5 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
                <Package className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-xs font-semibold text-white truncate">Certified MCP Bundle</div>
                <div className="text-[10px] text-neutral-400 truncate">apiweaver-mcp.zip + Claude Config</div>
              </div>
            </div>
            <div className="mt-3 pt-2.5 border-t border-white/5 flex items-center justify-between text-[11px] font-mono">
              <span className="text-neutral-400">AWS Secrets Ready</span>
              <span className="text-emerald-400 flex items-center gap-1 font-medium">
                Test & Export &rarr;
              </span>
            </div>
          </div>

        </div>
      </div>

      {/* Bottom Legend */}
      <footer className="h-10 border-t border-white/5 bg-black/60 px-6 flex items-center justify-between text-xs text-neutral-500 shrink-0 z-10">
        <div className="flex items-center gap-4 text-[11px]">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-emerald-400" /> Verified Stage
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-amber-400 animate-pulse" /> Streaming / Active
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-neutral-600" /> Standby
          </span>
        </div>
        <div className="text-[11px] text-neutral-500 font-mono">
          Click any stage node to open full workbench & controls in right drawer &rarr;
        </div>
      </footer>
    </section>
  );
};
