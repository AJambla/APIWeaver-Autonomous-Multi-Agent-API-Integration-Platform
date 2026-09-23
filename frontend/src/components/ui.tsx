import React, { useState } from 'react';
import { Search, X } from 'lucide-react';

/* Shared style tokens ------------------------------------------------------ */

export const cardCls =
  'rounded-2xl border border-white/10 bg-white/[0.03] hover:border-white/20 transition-colors';
export const btnPrimary =
  'inline-flex items-center justify-center gap-2 rounded-full bg-white text-black text-sm font-medium px-5 h-10 hover:bg-neutral-200 transition-colors disabled:opacity-50 disabled:pointer-events-none';
export const btnGhost =
  'inline-flex items-center justify-center gap-2 rounded-full border border-white/15 text-neutral-200 text-sm px-5 h-10 hover:bg-white/5 hover:text-white transition-colors disabled:opacity-50 disabled:pointer-events-none';
export const inputCls =
  'w-full rounded-xl border border-white/15 bg-neutral-900 px-4 h-10 text-sm text-white placeholder-neutral-600 focus:outline-none focus:border-white/60 focus:ring-1 focus:ring-white/20 transition-colors';

const STATUS_STYLES: Record<string, string> = {
  // success
  completed: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25',
  ready: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25',
  active: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25',
  // in progress
  running: 'bg-blue-500/10 text-blue-400 border-blue-500/25',
  queued: 'bg-blue-500/10 text-blue-400 border-blue-400/25',
  planning: 'bg-blue-500/10 text-blue-400 border-blue-400/25',
  building: 'bg-blue-500/10 text-blue-400 border-blue-400/25',
  testing: 'bg-blue-500/10 text-blue-400 border-blue-400/25',
  processing: 'bg-blue-500/10 text-blue-400 border-blue-400/25',
  // needs attention
  paused_for_approval: 'bg-amber-500/10 text-amber-400 border-amber-500/25',
  draft: 'bg-neutral-500/10 text-neutral-300 border-neutral-500/25',
  // error
  failed: 'bg-red-500/10 text-red-400 border-red-500/25',
  cancelled: 'bg-neutral-500/10 text-neutral-400 border-neutral-500/25',
  archived: 'bg-neutral-500/10 text-neutral-400 border-neutral-500/25',
};

/* Primitives ---------------------------------------------------------------- */

export const StatusBadge: React.FC<{ status: string | null | undefined; label?: string }> = ({
  status,
  label,
}) => {
  const key = (status || 'unknown').toLowerCase();
  const style = STATUS_STYLES[key] || 'bg-neutral-500/10 text-neutral-300 border-neutral-500/25';
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-medium capitalize ${style}`}
    >
      {label || key.replace(/_/g, ' ')}
    </span>
  );
};

export const PageHeader: React.FC<{
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}> = ({ title, subtitle, actions }) => (
  <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
    <div>
      <h1 className="text-2xl md:text-3xl font-normal tracking-tight">{title}</h1>
      {subtitle && <p className="mt-1 text-sm text-neutral-400">{subtitle}</p>}
    </div>
    {actions && <div className="flex items-center gap-3 shrink-0">{actions}</div>}
  </div>
);

export const StatCard: React.FC<{
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: React.ReactNode;
}> = ({ icon, label, value, sub }) => (
  <div className={`${cardCls} group p-5 hover:bg-white/[0.05] transition-colors`}>
    <div className="flex items-center justify-between mb-3">
      <span className="text-xs font-medium text-neutral-400">{label}</span>
      <span className="text-neutral-500 group-hover:text-neutral-300 transition-colors">{icon}</span>
    </div>
    <div className="text-2xl font-semibold tracking-tight">{value}</div>
    {sub && <div className="mt-1.5 text-xs text-neutral-500">{sub}</div>}
  </div>
);

export const EmptyState: React.FC<{
  icon: React.ReactNode;
  title: string;
  description: string;
  action?: React.ReactNode;
}> = ({ icon, title, description, action }) => (
  <div className={`${cardCls} flex flex-col items-center justify-center px-6 py-16 text-center`}>
    <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-white/5 text-neutral-400">
      {icon}
    </div>
    <h3 className="mb-1.5 text-base font-medium">{title}</h3>
    <p className="mb-6 max-w-sm text-sm text-neutral-400">{description}</p>
    {action}
  </div>
);

export const SearchInput: React.FC<{
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
}> = ({ value, onChange, placeholder = 'Search...', className = '' }) => (
  <div className={`relative ${className}`}>
    <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-500" />
    <input
      type="search"
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      className={`${inputCls} pl-10`}
    />
  </div>
);

export const FilterSelect: React.FC<{
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
  className?: string;
}> = ({ value, onChange, options, className = '' }) => (
  <select
    value={value}
    onChange={e => onChange(e.target.value)}
    className={`h-10 rounded-xl border border-white/15 bg-neutral-900 px-3 text-sm text-neutral-300 capitalize focus:outline-none focus:border-white/60 transition-colors ${className}`}
  >
    {options.map(o => (
      <option key={o.value} value={o.value}>
        {o.label}
      </option>
    ))}
  </select>
);

export const Tabs: React.FC<{
  tabs: Array<{ id: string; label: string }>;
  active: string;
  onChange: (id: string) => void;
}> = ({ tabs, active, onChange }) => (
  <div className="flex items-center gap-1 overflow-x-auto border-b border-white/10 pb-px">
    {tabs.map(t => (
      <button
        key={t.id}
        onClick={() => onChange(t.id)}
        className={`shrink-0 border-b-2 px-4 py-2.5 text-sm transition-colors ${
          active === t.id
            ? 'border-white text-white font-medium'
            : 'border-transparent text-neutral-400 hover:text-white'
        }`}
      >
        {t.label}
      </button>
    ))}
  </div>
);

export const Modal: React.FC<{
  title: string;
  description?: string;
  onClose: () => void;
  children: React.ReactNode;
}> = ({ title, description, onClose, children }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6 backdrop-blur-md" onClick={onClose}>
    <div
      className="relative w-full max-w-md rounded-3xl border border-white/15 bg-neutral-950 p-8"
      onClick={e => e.stopPropagation()}
    >
      <button
        onClick={onClose}
        className="absolute right-5 top-5 rounded-lg p-1.5 text-neutral-400 hover:bg-white/5 hover:text-white transition-colors"
      >
        <X className="h-4 w-4" />
      </button>
      <h2 className="mb-1 text-xl font-normal tracking-tight">{title}</h2>
      {description && <p className="mb-6 text-xs text-neutral-400">{description}</p>}
      {children}
    </div>
  </div>
);

export const Skeleton: React.FC<{ className?: string }> = ({ className = 'h-10' }) => (
  <div className={`animate-pulse rounded-xl bg-white/5 ${className}`} />
);

export const ErrorBanner: React.FC<{ message: string; onDismiss?: () => void }> = ({ message, onDismiss }) => (
  <div role="alert" className="mb-6 flex items-start justify-between gap-4 rounded-xl border border-red-500/25 bg-red-950/30 p-4 text-xs text-red-300">
    <span>{message}</span>
    {onDismiss && (
      <button onClick={onDismiss} className="shrink-0 text-red-400 hover:text-white transition-colors">
        <X className="h-3.5 w-3.5" />
      </button>
    )}
  </div>
);

/* Options menu --------------------------------------------------------------- */

export const OptionsMenu: React.FC<{ items: Array<{ label: string; onSelect: () => void; danger?: boolean }> }> = ({
  items,
}) => {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        onClick={e => {
          e.stopPropagation();
          setOpen(o => !o);
        }}
        className="rounded-lg p-1.5 text-neutral-400 hover:bg-white/5 hover:text-white transition-colors"
        aria-label="More options"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
          <circle cx="8" cy="3" r="1.25" />
          <circle cx="8" cy="8" r="1.25" />
          <circle cx="8" cy="13" r="1.25" />
        </svg>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={e => { e.stopPropagation(); setOpen(false); }} />
          <div className="absolute right-0 z-50 mt-1 w-44 overflow-hidden rounded-xl border border-white/10 bg-neutral-900 py-1 shadow-xl">
            {items.map(item => (
              <button
                key={item.label}
                onClick={e => {
                  e.stopPropagation();
                  setOpen(false);
                  item.onSelect();
                }}
                className={`block w-full px-4 py-2 text-left text-sm transition-colors ${
                  item.danger ? 'text-red-400 hover:bg-red-500/10' : 'text-neutral-300 hover:bg-white/5 hover:text-white'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
};

/* Table helpers --------------------------------------------------------------- */

export const Th: React.FC<{ children?: React.ReactNode; className?: string }> = ({ children, className = '' }) => (
  <th className={`px-4 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-neutral-500 ${className}`}>
    {children}
  </th>
);

export const Td: React.FC<{ children: React.ReactNode; className?: string }> = ({ children, className = '' }) => (
  <td className={`px-4 py-3 text-sm text-neutral-300 ${className}`}>{children}</td>
);

export const tableCls = 'w-full border-collapse';
export const rowCls = 'border-t border-white/5 hover:bg-white/[0.02] transition-colors';
