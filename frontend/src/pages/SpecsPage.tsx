import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../lib/auth-context';
import { apiFetch } from '../lib/api';
import { ApiSpec, Page, Project, SpecEndpoint } from '../lib/types';
import { NormalizedSpec, relativeTime, specFormat, specVersion, validationState } from '../lib/format';
import {
  cardCls,
  EmptyState,
  ErrorBanner,
  FilterSelect,
  PageHeader,
  rowCls,
  SearchInput,
  Skeleton,
  StatusBadge,
  tableCls,
  Td,
  Th,
} from '../components/ui';
import { FileCode2, ChevronRight } from 'lucide-react';

const errorMessage = (error: unknown) => (error instanceof Error ? error.message : 'Unable to load specifications.');

interface SpecRow {
  project: Project;
  spec: ApiSpec | null;
  endpoints: number;
  raw: NormalizedSpec | null;
}

export const SpecsPage: React.FC = () => {
  const { organizationId } = useAuth();
  const [rows, setRows] = useState<SpecRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [formatFilter, setFormatFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');

  useEffect(() => {
    if (!organizationId) return;
    let cancelled = false;
    apiFetch<Page<Project>>(`/projects?limit=50&organization_id=${organizationId}`)
      .then(async ({ data }) => {
        const results = await Promise.allSettled(
          data.map(async project => {
            const [spec, endpoints] = await Promise.allSettled([
              apiFetch<ApiSpec>(`/projects/${project.id}/spec`),
              apiFetch<SpecEndpoint[]>(`/projects/${project.id}/endpoints`),
            ]);
            return {
              project,
              spec: spec.status === 'fulfilled' ? spec.value : null,
              endpoints: endpoints.status === 'fulfilled' ? endpoints.value.length : 0,
              raw: spec.status === 'fulfilled' ? (spec.value.raw_normalized as NormalizedSpec) : null,
            };
          }),
        );
        if (!cancelled) setRows(results.filter(r => r.status === 'fulfilled').map(r => r.value));
      })
      .catch(err => !cancelled && setError(errorMessage(err)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [organizationId]);

  const summary = useMemo(() => {
    const withSpec = rows.filter(r => r.spec);
    return {
      total: withSpec.length,
      openapi: withSpec.filter(r => r.raw?.openapi).length,
      swagger: withSpec.filter(r => r.raw?.swagger).length,
      endpoints: rows.reduce((sum, r) => sum + r.endpoints, 0),
    };
  }, [rows]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return rows
      .filter(r => !term || r.project.name.toLowerCase().includes(term) || (r.spec?.title || '').toLowerCase().includes(term))
      .filter(r => {
        if (formatFilter === 'openapi') return !!r.raw?.openapi;
        if (formatFilter === 'swagger') return !!r.raw?.swagger;
        return true;
      })
      .filter(r => {
        if (statusFilter === 'all') return true;
        return validationState(r.spec?.confidence_score).status === statusFilter;
      })
      .sort((a, b) => new Date(b.project.updated_at).getTime() - new Date(a.project.updated_at).getTime());
  }, [rows, search, formatFilter, statusFilter]);

  return (
    <div className="px-6 py-10 lg:px-10">
      <PageHeader
        title="API Specifications"
        subtitle="OpenAPI and Swagger documents ingested across your projects."
      />

      {error && <ErrorBanner message={error} onDismiss={() => setError('')} />}

      <div className="mb-8 grid grid-cols-2 gap-4 xl:grid-cols-4">
        {[
          { label: 'Total Specs', value: summary.total },
          { label: 'OpenAPI', value: summary.openapi },
          { label: 'Swagger', value: summary.swagger },
          { label: 'Endpoints', value: summary.endpoints },
        ].map(item => (
          <div key={item.label} className={`${cardCls} p-4`}>
            <div className="text-xs text-neutral-400">{item.label}</div>
            <div className="mt-1 text-xl font-semibold">{loading ? '—' : item.value}</div>
          </div>
        ))}
      </div>

      <div className="mb-6 flex flex-col gap-3 sm:flex-row">
        <SearchInput value={search} onChange={setSearch} placeholder="Search specs..." className="flex-1 sm:max-w-sm" />
        <FilterSelect
          value={formatFilter}
          onChange={setFormatFilter}
          options={[
            { value: 'all', label: 'All formats' },
            { value: 'openapi', label: 'OpenAPI' },
            { value: 'swagger', label: 'Swagger' },
          ]}
        />
        <FilterSelect
          value={statusFilter}
          onChange={setStatusFilter}
          options={[
            { value: 'all', label: 'All statuses' },
            { value: 'completed', label: 'Valid' },
            { value: 'paused_for_approval', label: 'Warnings' },
            { value: 'failed', label: 'Low confidence' },
            { value: 'draft', label: 'No spec' },
          ]}
        />
      </div>

      {loading ? (
        <Skeleton className="h-64" />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<FileCode2 className="h-6 w-6" />}
          title="No API specifications yet"
          description="Upload your first OpenAPI or Swagger document from a project workspace to start building an integration."
          action={
            <Link to="/dashboard" className="inline-flex h-10 items-center rounded-full bg-white px-5 text-sm font-medium text-black hover:bg-neutral-200 transition-colors">
              Go to Projects
            </Link>
          }
        />
      ) : (
        <div className={`${cardCls} overflow-x-auto hover:border-white/10`}>
          <table className={tableCls}>
            <thead>
              <tr>
                <Th>Specification</Th>
                <Th>Format</Th>
                <Th>Version</Th>
                <Th>Validation</Th>
                <Th>Endpoints</Th>
                <Th>Updated</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {visible.map(row => {
                const validation = validationState(row.spec?.confidence_score);
                return (
                  <tr key={row.project.id} className={rowCls}>
                    <Td>
                      <div className="font-medium text-white">{row.spec?.title || row.project.name}</div>
                      <div className="text-xs text-neutral-500">{row.project.name}</div>
                    </Td>
                    <Td className="whitespace-nowrap">{specFormat(row.raw)}</Td>
                    <Td>{specVersion(row.raw)}</Td>
                    <Td><StatusBadge status={validation.status} label={validation.label} /></Td>
                    <Td>{row.endpoints}</Td>
                    <Td className="whitespace-nowrap text-neutral-500">{relativeTime(row.project.updated_at)}</Td>
                    <Td>
                      <Link
                        to={`/dashboard/specs/${row.project.id}`}
                        className="inline-flex items-center gap-1 text-xs font-medium text-neutral-300 hover:text-white transition-colors"
                      >
                        View <ChevronRight className="h-3.5 w-3.5" />
                      </Link>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {visible.length === 0 && (
            <div className="p-8 text-center text-sm text-neutral-500">No specifications match the current filters.</div>
          )}
        </div>
      )}
    </div>
  );
};
