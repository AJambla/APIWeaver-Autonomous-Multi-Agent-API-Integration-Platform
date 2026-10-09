import React from 'react';
import { Copy, GitBranch } from 'lucide-react';
import { ApiSpec, ProjectSummary } from '../../lib/types';
import { NormalizedSpec, shortId, specFormat } from '../../lib/format';
import { cardCls } from '../../components/ui';

interface SettingsTabProps {
  project: ProjectSummary;
  spec: ApiSpec | null;
  rawSpec: NormalizedSpec;
}

export const SettingsTab: React.FC<SettingsTabProps> = ({ project, spec, rawSpec }) => {
  return (
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
  );
};
