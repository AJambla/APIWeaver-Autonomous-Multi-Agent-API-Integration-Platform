export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const future = diff < 0;
  const s = Math.abs(diff) / 1000;
  const fmt = (v: number, unit: string) => (future ? `in ${Math.floor(v)} ${unit}` : `${Math.floor(v)} ${unit} ago`);
  if (s < 60) return 'just now';
  if (s < 3600) return fmt(s / 60, 'min');
  if (s < 86400) return fmt(s / 3600, 'hr');
  if (s < 86400 * 30) return fmt(s / 86400, 'day');
  return new Date(iso).toLocaleDateString();
}

export function duration(startIso: string | null | undefined, endIso: string | null | undefined): string {
  if (!startIso) return '—';
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  const mins = (end - new Date(startIso).getTime()) / 60000;
  if (mins < 1) return '<1 min';
  if (mins < 60) return `${mins.toFixed(1)} min`;
  return `${(mins / 60).toFixed(1)} hr`;
}

export function formatNumber(n: number): string {
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(n);
}

export function formatUsd(n: number): string {
  return `$${n.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
}

export function formatPercent(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return '—';
  return `${Math.round(ratio * 100)}%`;
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}

export function initials(name: string | undefined, email?: string): string {
  const source = (name || email || '?').trim();
  const parts = source.split(/[\s@._-]+/).filter(Boolean);
  return (parts[0]?.[0] || '?').toUpperCase() + (parts[1]?.[0] || '').toUpperCase();
}

/* Normalized OpenAPI document helpers (SpecResponse.raw_normalized) */

export interface NormalizedSpec {
  openapi?: string;
  swagger?: string;
  info?: { title?: string; version?: string; description?: string };
  servers?: Array<{ url?: string }>;
  paths?: Record<string, Record<string, unknown>>;
  components?: { schemas?: Record<string, unknown> };
}

export function specFormat(raw: NormalizedSpec | null | undefined): string {
  if (!raw) return '—';
  if (raw.openapi) return `OpenAPI ${raw.openapi}`;
  if (raw.swagger) return `Swagger ${raw.swagger}`;
  return 'Normalized';
}

export function specVersion(raw: NormalizedSpec | null | undefined): string {
  return raw?.info?.version || '—';
}

export function validationState(confidence: number | null | undefined): { label: string; status: string } {
  if (confidence === null || confidence === undefined) return { label: 'No spec', status: 'draft' };
  if (confidence >= 0.8) return { label: 'Valid', status: 'completed' };
  if (confidence >= 0.5) return { label: 'Warnings', status: 'paused_for_approval' };
  return { label: 'Low confidence', status: 'failed' };
}
