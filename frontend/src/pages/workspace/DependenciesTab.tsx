import React from 'react';
import {
  ArrowDown,
  ArrowRight,
  Check,
  CheckCircle2,
  FileCode2,
  FileText,
  Loader2,
  Network,
  ShieldAlert,
} from 'lucide-react';
import { ApiSpec, DependencyGraph, DependencyNode } from '../../lib/types';
import { btnGhost, btnPrimary, cardCls, EmptyState, ErrorBanner } from '../../components/ui';

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

export const DependenciesTab: React.FC<DependenciesTabProps> = ({
  graph,
  resourceGroups,
  spec,
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
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-medium tracking-tight">API Topology & Dependency Graph</h2>
          <p className="text-xs text-neutral-500">
            {graph && graph.nodes.length > 0
              ? `${graph.nodes.length} endpoint${graph.nodes.length === 1 ? '' : 's'} · ${graph.edges.length} ${graph.edges.length === 1 ? 'dependency' : 'dependencies'} extracted from the specification`
              : 'Generated from the uploaded specification'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={onViewPlanDoc} className={btnGhost}>
            <FileText className="h-4 w-4" /> View Topology Doc
          </button>
          <button
            onClick={onApprovePlan}
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
            {planApproved ? 'Topology Approved' : 'Approve Topology'}
          </button>
        </div>
      </div>

      {planError && <ErrorBanner message={planError} onDismiss={onDismissError} />}
      {!pausedRunId && !planApproved && (
        <p className="text-xs text-neutral-500">
          Topological execution order is ready. Review endpoint relationships below before proceeding to FastMCP Tool Synthesis.
        </p>
      )}

      {resourceGroups.length === 0 ? (
        <EmptyState
          icon={<Network className="h-6 w-6" />}
          title="No topology available yet"
          description={
            spec
              ? 'This specification did not yield any endpoints, so there is nothing to plan. Upload a richer specification to build the graph.'
              : 'Upload an API specification in the Ingest stage to generate the endpoint topology.'
          }
          action={
            <button onClick={onGoToIngest} className={btnPrimary}>
              Go to Ingest <ArrowRight className="h-4 w-4" />
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
                        <div className="mt-1 truncate text-[11px] text-neutral-500" title={node.label}>
                          {node.label}
                        </div>
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
          <h3 className="mb-1 text-sm font-medium">Ready for FastMCP Synthesis</h3>
          <p className="text-xs text-neutral-500">
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
