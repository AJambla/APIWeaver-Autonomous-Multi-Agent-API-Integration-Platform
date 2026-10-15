import React, { useState } from 'react';
import { AlertTriangle, CheckCircle2, Lock, ShieldAlert, Sparkles, X } from 'lucide-react';
import { btnGhost, btnPrimary, inputCls, Modal } from '../../components/ui';

export interface LiveTestModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (params: { baseUrl: string; authType: string; headerName: string; secretValue: string }) => Promise<void> | void;
  hasDestructiveEndpoints: boolean;
  defaultBaseUrl?: string;
  busy?: boolean;
}

export const LiveTestModal: React.FC<LiveTestModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
  hasDestructiveEndpoints,
  defaultBaseUrl = '',
  busy = false,
}) => {
  const [baseUrl, setBaseUrl] = useState(defaultBaseUrl);
  const [authType, setAuthType] = useState<'bearer' | 'apikey' | 'basic' | 'none'>('bearer');
  const [headerName, setHeaderName] = useState('Authorization');
  const [secretValue, setSecretValue] = useState('');
  const [confirmedDestructive, setConfirmedDestructive] = useState(!hasDestructiveEndpoints);
  const [validationError, setValidationError] = useState('');

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setValidationError('');

    if (!baseUrl.trim() || !baseUrl.startsWith('http')) {
      setValidationError('Please enter a valid HTTP/HTTPS Base URL.');
      return;
    }

    if (authType !== 'none' && !secretValue.trim()) {
      setValidationError('Credential secret value is required for authenticated live testing.');
      return;
    }

    if (hasDestructiveEndpoints && !confirmedDestructive) {
      setValidationError('You must acknowledge the destructive endpoint risk before proceeding.');
      return;
    }

    onSubmit({
      baseUrl: baseUrl.trim(),
      authType,
      headerName: authType === 'bearer' ? 'Authorization' : headerName.trim(),
      secretValue: secretValue.trim(),
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-md" onClick={onClose}>
      <div
        className="relative w-full max-w-lg rounded-3xl border border-white/15 bg-neutral-950 p-6 sm:p-8"
        onClick={e => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute right-5 top-5 rounded-lg p-1.5 text-neutral-400 hover:bg-white/5 hover:text-white transition-colors"
        >
          <X className="h-4 w-4" />
        </button>

        <div className="flex items-center gap-2.5 mb-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-500/10 text-amber-400">
            <Lock className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-xl font-medium tracking-tight">Level 3: Live API Verification</h2>
            <p className="text-xs text-neutral-400">Execute verified tests against your real remote API.</p>
          </div>
        </div>

        {validationError && (
          <div className="mt-4 rounded-xl border border-rose-500/30 bg-rose-950/20 p-3 text-xs text-rose-300">
            {validationError}
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-5 space-y-4">
          {/* Target Base URL */}
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wider text-neutral-400 font-medium">
              API Base URL <span className="text-rose-400">*</span>
            </label>
            <input
              type="url"
              value={baseUrl}
              onChange={e => setBaseUrl(e.target.value)}
              placeholder="https://api.stripe.com/v1"
              className={inputCls}
              required
            />
          </div>

          {/* Auth Scheme */}
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wider text-neutral-400 font-medium">
              Authentication Scheme
            </label>
            <div className="grid grid-cols-4 gap-2">
              {(
                [
                  { id: 'bearer', label: 'Bearer Token' },
                  { id: 'apikey', label: 'API Key Header' },
                  { id: 'basic', label: 'Basic Auth' },
                  { id: 'none', label: 'None (Public)' },
                ] as const
              ).map(scheme => (
                <button
                  key={scheme.id}
                  type="button"
                  onClick={() => {
                    setAuthType(scheme.id);
                    if (scheme.id === 'bearer') setHeaderName('Authorization');
                    if (scheme.id === 'apikey') setHeaderName('X-API-Key');
                  }}
                  className={`rounded-xl border py-2 text-xs font-medium transition-colors ${
                    authType === scheme.id
                      ? 'border-white bg-white text-black'
                      : 'border-white/10 bg-white/5 text-neutral-300 hover:bg-white/10'
                  }`}
                >
                  {scheme.label}
                </button>
              ))}
            </div>
          </div>

          {/* Header Name (for API Key) */}
          {authType === 'apikey' && (
            <div>
              <label className="mb-1 block text-xs uppercase tracking-wider text-neutral-400 font-medium">
                Header Name
              </label>
              <input
                type="text"
                value={headerName}
                onChange={e => setHeaderName(e.target.value)}
                placeholder="X-API-Key or Authorization"
                className={inputCls}
              />
            </div>
          )}

          {/* Secret Token / Key (Masked) */}
          {authType !== 'none' && (
            <div>
              <label className="mb-1 block text-xs uppercase tracking-wider text-neutral-400 font-medium">
                {authType === 'bearer' ? 'Bearer Token' : authType === 'apikey' ? 'API Key Value' : 'Credentials'} <span className="text-rose-400">*</span>
              </label>
              <input
                type="password"
                value={secretValue}
                onChange={e => setSecretValue(e.target.value)}
                placeholder="••••••••••••••••••••••••"
                className={inputCls}
                autoComplete="new-password"
                required
              />
              <p className="mt-1 text-[11px] text-neutral-500">
                Credentials are encrypted in-memory and injected strictly into runtime execution headers. Never logged or stored in plain text.
              </p>
            </div>
          )}

          {/* Destructive Warning Gate */}
          {hasDestructiveEndpoints && (
            <div className="rounded-2xl border border-rose-500/30 bg-rose-950/20 p-4 space-y-2.5">
              <div className="flex items-center gap-2 text-rose-300 text-xs font-semibold uppercase tracking-wider">
                <ShieldAlert className="h-4 w-4 text-rose-400" />
                Destructive Operations Warning
              </div>
              <p className="text-xs text-rose-200/80 leading-relaxed">
                This API specification contains destructive endpoints (e.g. <code>DELETE</code>, <code>PUT</code>) that can permanently modify live system data.
              </p>
              <label className="flex items-start gap-2.5 text-xs text-rose-100 cursor-pointer pt-1">
                <input
                  type="checkbox"
                  checked={confirmedDestructive}
                  onChange={e => setConfirmedDestructive(e.target.checked)}
                  className="mt-0.5 rounded border-rose-500/50 bg-rose-950 text-rose-500 focus:ring-0"
                />
                <span>I understand that live testing will execute operations against the target API and assume full responsibility.</span>
              </label>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-3 border-t border-white/10">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className={btnGhost}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy || (hasDestructiveEndpoints && !confirmedDestructive)}
              className={btnPrimary}
            >
              {busy ? 'Initiating Live Tests…' : 'Execute Live Verification'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
