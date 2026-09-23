import React, { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { apiFetch } from '../lib/api';
import { ApiSpec, ProjectSummary, SpecEndpoint } from '../lib/types';
import { NormalizedSpec, formatPercent, specFormat, specVersion } from '../lib/format';
import {
  cardCls,
  EmptyState,
  ErrorBanner,
  PageHeader,
  rowCls,
  Skeleton,
  StatusBadge,
  tableCls,
  Tabs,
  Td,
  Th,
} from '../components/ui';
import { ChevronLeft, FileCode2 } from 'lucide-react';

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'endpoints', label: 'Endpoints' },
  { id: 'schemas', label: 'Schemas' },
  { id: 'validation', label: 'Validation' },
];

const InfoRow: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div className="flex items-center justify-between gap-6 border-b border-white/5 py-3 last:border-0">
    <span className="text-xs text-neutral-500">{label}</span>
    <span className="min-w-0 truncate text-sm text-neutral-200">{value}</span>
  </div>
);

export const SpecDetailPage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [spec, setSpec] = useState<ApiSpec | null>(null);
  const [endpoints, setEndpoints] = useState<SpecEndpoint[]>([]);
  const [active, setActive] = useState('overview');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    setLoading(true);
    Promise.allSettled([
      apiFetch<ProjectSummary>(`/projects/${projectId}`),
      apiFetch<ApiSpec>(`/projects/${projectId}/spec`),
      apiFetch<SpecEndpoint[]>(`/projects/${projectId}/endpoints`),
    ]).then(([p, s, e]) => {
      if (cancelled) return;
      if (p.status === 'fulfilled') setProject(p.value);
      else setError('Project not found or access denied.');
      if (s.status === 'fulfilled') setSpec(s.value);
      if (e.status === 'fulfilled') setEndpoints(e.value);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const raw = (spec?.raw_normalized || null) as NormalizedSpec | null;

  const schemas = useMemo(() => Object.keys(raw?.components?.schemas || {}), [raw]);

  const issues = useMemo(() => {
    const list: Array<{ kind: string; detail: string }> = [];
    endpoints.forEach(ep => {
      if (ep.deprecated) list.push({ kind: 'Deprecated', detail: `${ep.method} ${ep.path}` });
      if (ep.confidence_score !== null && ep.confidence_score !== undefined && ep.confidence_score < 0.6)
        list.push({ kind: 'Low confidence', detail: `${ep.method} ${ep.path} (${formatPercent(ep.confidence_score)})` });
      if (!ep.summary) list.push({ kind: 'Missing summary', detail: `${ep.method} ${ep.path}` });
    });
    return list;
  }, [endpoints]);

  if (loading) {
    return (
      <div className="px-6 py-10 lg:px-10">
        <Skeleton className="mb-8 h-10 w-72" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  return (
    <div className="px-6 py-10 lg:px-10">
      <Link
        to="/dashboard/specs"
        className="mb-6 inline-flex items-center gap-1 text-xs text-neutral-400 hover:text-white transition-colors"
      >
        <ChevronLeft className="h-3.5 w-3.5" /> Back to specifications
      </Link>

      <PageHeader
        title={spec?.title || project?.name || 'Specification'}
        subtitle={project ? `Project: ${project.name}` : undefined}
      />

      {error && <ErrorBanner message={error} onDismiss={() => setError('')} />}

      {!spec ? (
        <EmptyState
          icon={<FileCode2 className="h-6 w-6" />}
          title="No specification uploaded"
          description="Upload an OpenAPI or Swagger document from this project's workspace to see its analysis here."
          action={
            <Link
              to={`/projects/${projectId}`}
              className="inline-flex h-10 items-center rounded-full bg-white px-5 text-sm font-medium text-black hover:bg-neutral-200 transition-colors"
            >
              Open Workspace
            </Link>
          }
        />
      ) : (
        <>
          <div className="mb-6">
            <Tabs tabs={TABS} active={active} onChange={setActive} />
          </div>

          {active === 'overview' && (
            <div className={`${cardCls} max-w-2xl p-6`}>
              <InfoRow label="Title" value={spec.title || '—'} />
              <InfoRow label="Format" value={specFormat(raw)} />
              <InfoRow label="Version" value={specVersion(raw)} />
              <InfoRow label="Base URL" value={spec.base_url || raw?.servers?.[0]?.url || '—'} />
              <InfoRow label="Parse confidence" value={formatPercent(spec.confidence_score)} />
              <InfoRow label="Endpoints" value={endpoints.length} />
              <InfoRow label="Schemas" value={schemas.length} />
            </div>
          )}

          {active === 'endpoints' && (
            <div className={`${cardCls} overflow-x-auto hover:border-white/10`}>
              {endpoints.length === 0 ? (
                <div className="p-8 text-center text-sm text-neutral-500">No endpoints discovered.</div>
              ) : (
                <table className={tableCls}>
                  <thead>
                    <tr>
                      <Th>Method</Th>
                      <Th>Path</Th>
                      <Th>Summary</Th>
                      <Th>Confidence</Th>
                      <Th>Flags</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {endpoints.map(ep => (
                      <tr key={ep.id} className={rowCls}>
                        <Td>
                          <span className="rounded-md bg-white/5 px-2 py-0.5 font-mono text-xs">{ep.method}</span>
                        </Td>
                        <Td className="font-mono text-xs">{ep.path}</Td>
                        <Td className="max-w-md truncate">{ep.summary || '—'}</Td>
                        <Td>{formatPercent(ep.confidence_score)}</Td>
                        <Td>{ep.deprecated && <StatusBadge status="failed" label="deprecated" />}</Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {active === 'schemas' && (
            <div className={`${cardCls} p-6 hover:border-white/10`}>
              {schemas.length === 0 ? (
                <div className="text-sm text-neutral-500">This specification declares no reusable schemas.</div>
              ) : (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {schemas.map(name => (
                    <div key={name} className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2 font-mono text-xs text-neutral-300">
                      {name}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {active === 'validation' && (
            <div className={`${cardCls} p-6 hover:border-white/10`}>
              <div className="mb-4 flex items-center gap-3">
                <span className="text-sm text-neutral-400">Parse confidence:</span>
                <StatusBadge
                  status={spec.confidence_score !== null && spec.confidence_score >= 0.8 ? 'completed' : spec.confidence_score !== null && spec.confidence_score >= 0.5 ? 'paused_for_approval' : 'failed'}
                  label={formatPercent(spec.confidence_score)}
                />
              </div>
              {issues.length === 0 ? (
                <div className="text-sm text-neutral-500">No documentation issues detected across {endpoints.length} endpoints.</div>
              ) : (
                <div className="divide-y divide-white/5">
                  {issues.slice(0, 50).map((issue, i) => (
                    <div key={i} className="flex items-center justify-between gap-4 py-2.5">
                      <span className="font-mono text-xs text-neutral-300">{issue.detail}</span>
                      <StatusBadge status={issue.kind === 'Deprecated' ? 'paused_for_approval' : 'draft'} label={issue.kind} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
};
