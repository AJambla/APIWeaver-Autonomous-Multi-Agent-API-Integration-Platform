import React, { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Check,
  Copy,
  Github,
  KeyRound,
  Link2Off,
  Plus,
  Trash2,
  User as UserIcon,
  Users,
  X,
} from 'lucide-react';
import { useAuth } from '../lib/auth-context';
import { apiFetch } from '../lib/api';
import { ApiKey, ApiKeyCreated, GitHubStatus, Page } from '../lib/types';
import { initials, relativeTime } from '../lib/format';
import {
  btnGhost,
  btnPrimary,
  cardCls,
  EmptyState,
  ErrorBanner,
  inputCls,
  Modal,
  PageHeader,
  rowCls,
  Skeleton,
  StatusBadge,
  tableCls,
  Td,
  Th,
} from '../components/ui';

const errorMessage = (error: unknown) => (error instanceof Error ? error.message : 'Something went wrong.');

type SectionKey = 'account' | 'workspace' | 'keys' | 'github';

const SECTIONS: Array<{ key: SectionKey; label: string; icon: React.FC<{ className?: string }> }> = [
  { key: 'account', label: 'Account', icon: UserIcon },
  { key: 'workspace', label: 'Workspace', icon: Users },
  { key: 'keys', label: 'API Keys', icon: KeyRound },
  { key: 'github', label: 'GitHub', icon: Github },
];

const InfoRow: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="flex items-center justify-between gap-6 py-3">
    <span className="text-sm text-neutral-500">{label}</span>
    <span className="min-w-0 truncate text-right text-sm text-neutral-200">{children}</span>
  </div>
);

const CopyButton: React.FC<{ text: string }> = ({ text }) => {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      className={btnGhost}
    >
      {copied ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
};

const AccountSection: React.FC = () => {
  const { user } = useAuth();
  return (
    <div className={`${cardCls} px-5 py-1`}>
      <div className="flex items-center gap-4 border-b border-white/5 py-5">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-white/5 text-sm font-semibold">
          {initials(user?.full_name || user?.email || '?')}
        </div>
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">{user?.full_name || user?.email}</div>
          <div className="truncate text-xs text-neutral-500">{user?.email}</div>
        </div>
      </div>
      <div className="divide-y divide-white/5">
        <InfoRow label="Full name">{user?.full_name || '—'}</InfoRow>
        <InfoRow label="Email">{user?.email || '—'}</InfoRow>
        <InfoRow label="Role">{user?.role || 'member'}</InfoRow>
        <InfoRow label="User ID">
          <span className="font-mono text-xs">{user?.id}</span>
        </InfoRow>
      </div>
    </div>
  );
};

const WorkspaceSection: React.FC = () => {
  const { organizations, organizationId, selectOrganization } = useAuth();
  if (organizations.length === 0) {
    return (
      <EmptyState
        icon={<Users className="h-6 w-6" />}
        title="No workspaces"
        description="This account is not a member of any organization yet."
      />
    );
  }
  return (
    <div className="space-y-2">
      {organizations.map(org => {
        const current = org.organization_id === organizationId;
        return (
          <div key={org.organization_id} className={`${cardCls} flex items-center gap-4 p-4`}>
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/5 text-xs font-semibold">
              {initials(org.organization_name)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-medium">{org.organization_name}</span>
                {current && <StatusBadge status="ready" label="current" />}
              </div>
              <div className="truncate font-mono text-xs text-neutral-500">{org.organization_id}</div>
            </div>
            <span className="shrink-0 text-xs uppercase tracking-wider text-neutral-500">{org.role}</span>
            {!current && (
              <button type="button" onClick={() => selectOrganization(org.organization_id)} className={btnGhost}>
                Switch
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
};

const KeysSection: React.FC = () => {
  const { organizationId } = useAuth();
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState('');
  const [expiresInDays, setExpiresInDays] = useState('');
  const [creating, setCreating] = useState(false);
  const [createdKey, setCreatedKey] = useState<ApiKeyCreated | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);

  const load = useCallback(async () => {
    if (!organizationId) return;
    setLoading(true);
    setError('');
    try {
      const page = await apiFetch<Page<ApiKey>>(`/org/${organizationId}/api-keys?limit=50`);
      setKeys(page.data);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async () => {
    if (!organizationId || !name.trim()) return;
    setCreating(true);
    setError('');
    try {
      const body: Record<string, unknown> = { name: name.trim() };
      const days = Number(expiresInDays);
      if (expiresInDays.trim() && Number.isInteger(days) && days > 0) {
        body.expires_in_days = days;
      }
      const created = await apiFetch<ApiKeyCreated>(`/org/${organizationId}/api-keys`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      setCreatedKey(created);
      setCreateOpen(false);
      setName('');
      setExpiresInDays('');
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async () => {
    if (!organizationId || !revoking) return;
    setError('');
    try {
      await apiFetch(`/org/${organizationId}/api-keys/${revoking.id}`, { method: 'DELETE' });
      setRevoking(null);
      load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div>
      {error && <div className="mb-4"><ErrorBanner message={error} onDismiss={() => setError('')} /></div>}

      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-neutral-500">
          Keys authenticate programmatic access for this workspace. The full key is shown only once.
        </p>
        <button type="button" onClick={() => setCreateOpen(true)} className={btnPrimary}>
          <Plus className="h-4 w-4" /> Create Key
        </button>
      </div>

      <div className={`${cardCls} overflow-hidden`}>
        {loading ? (
          <div className="space-y-3 p-4">
            {[1, 2, 3].map(i => <Skeleton key={i} className="h-10" />)}
          </div>
        ) : keys.length === 0 ? (
          <EmptyState
            icon={<KeyRound className="h-6 w-6" />}
            title="No API keys"
            description="Create a key to call exported integrations programmatically."
          />
        ) : (
          <table className={tableCls}>
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-neutral-500">
                <Th>Name</Th>
                <Th>Prefix</Th>
                <Th>Created</Th>
                <Th>Expires</Th>
                <Th>Status</Th>
                <Th className="w-10">Actions</Th>
              </tr>
            </thead>
            <tbody>
              {keys.map(key => {
                const revoked = key.revoked_at !== null;
                const expired = key.expires_at !== null && new Date(key.expires_at).getTime() < Date.now();
                return (
                  <tr key={key.id} className={rowCls}>
                    <Td>
                      <span className="font-medium">{key.name}</span>
                      {key.project_id && <span className="ml-2 text-xs text-neutral-500">project-scoped</span>}
                    </Td>
                    <Td><span className="font-mono text-xs">{key.prefix}…</span></Td>
                    <Td><span className="text-xs text-neutral-400">{relativeTime(key.created_at)}</span></Td>
                    <Td>
                      <span className="text-xs text-neutral-400">
                        {key.expires_at ? new Date(key.expires_at).toLocaleDateString() : 'Never'}
                      </span>
                    </Td>
                    <Td>
                      {revoked ? (
                        <StatusBadge status="cancelled" label="revoked" />
                      ) : expired ? (
                        <StatusBadge status="failed" label="expired" />
                      ) : (
                        <StatusBadge status="ready" label="active" />
                      )}
                    </Td>
                    <Td>
                      {!revoked && (
                        <button
                          type="button"
                          onClick={() => setRevoking(key)}
                          className="text-neutral-500 hover:text-red-400 transition-colors"
                          title="Revoke key"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {createOpen && (
      <Modal onClose={() => setCreateOpen(false)} title="Create API key">
        <div className="space-y-4">
          <div>
            <label htmlFor="key-name" className="mb-1.5 block text-xs uppercase tracking-wider text-neutral-500">
              Name
            </label>
            <input
              id="key-name"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="ci-pipeline"
              className={inputCls}
              maxLength={255}
            />
          </div>
          <div>
            <label htmlFor="key-expiry" className="mb-1.5 block text-xs uppercase tracking-wider text-neutral-500">
              Expires in (days, optional)
            </label>
            <input
              id="key-expiry"
              value={expiresInDays}
              onChange={e => setExpiresInDays(e.target.value)}
              placeholder="90"
              type="number"
              min={1}
              max={3650}
              className={inputCls}
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={() => setCreateOpen(false)} className={btnGhost}>
              Cancel
            </button>
            <button
              type="button"
              onClick={handleCreate}
              disabled={creating || !name.trim()}
              className={btnPrimary}
            >
              {creating ? 'Creating…' : 'Create Key'}
            </button>
          </div>
        </div>
      </Modal>
      )}

      {createdKey && (
      <Modal onClose={() => setCreatedKey(null)} title="API key created">
        <div className="space-y-4">
          <div className="flex items-start gap-3 rounded-lg border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-amber-200">
            <span>
              This is the only time the full key will be shown. Copy it now and store it securely.
            </span>
          </div>
          <div className={`${cardCls} flex items-center gap-3 bg-black/40 p-3`}>
            <code className="min-w-0 flex-1 break-all font-mono text-xs text-neutral-200">{createdKey.key}</code>
            <CopyButton text={createdKey.key} />
          </div>
          <div className="flex justify-end">
            <button type="button" onClick={() => setCreatedKey(null)} className={btnPrimary}>
              Done
            </button>
          </div>
        </div>
      </Modal>
      )}

      {revoking && (
      <Modal onClose={() => setRevoking(null)} title="Revoke API key">
        <div className="space-y-4">
          <p className="text-sm text-neutral-400">
            Revoke <span className="font-medium text-white">{revoking.name}</span> ({revoking.prefix}…)?
            Requests using this key will stop working immediately. This cannot be undone.
          </p>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setRevoking(null)} className={btnGhost}>
              Cancel
            </button>
            <button
              type="button"
              onClick={handleRevoke}
              className="inline-flex items-center gap-2 rounded-lg bg-red-500/90 px-4 py-2 text-sm font-medium text-white hover:bg-red-500 transition-colors"
            >
              <Trash2 className="h-4 w-4" /> Revoke Key
            </button>
          </div>
        </div>
      </Modal>
      )}
    </div>
  );
};

const GitHubSection: React.FC = () => {
  const [status, setStatus] = useState<GitHubStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setStatus(await apiFetch<GitHubStatus>('/github/status'));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const connect = async () => {
    setBusy(true);
    setError('');
    try {
      const { auth_url } = await apiFetch<{ auth_url: string }>('/github/connect', { method: 'POST' });
      window.open(auth_url, '_blank', 'noopener');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async () => {
    setBusy(true);
    setError('');
    try {
      await apiFetch('/github/disconnect', { method: 'DELETE' });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`${cardCls} p-5`}>
      {error && <div className="mb-4"><ErrorBanner message={error} onDismiss={() => setError('')} /></div>}
      {loading ? (
        <Skeleton className="h-20" />
      ) : status?.connected ? (
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-white/5">
              <Github className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-medium">
                Connected as <span className="font-mono">@{status.github_username}</span>
              </div>
              <div className="text-xs text-neutral-500">
                {status.installations.length > 0
                  ? `${status.installations.length} installation${status.installations.length > 1 ? 's' : ''} available`
                  : 'Repository export is enabled for your account.'}
              </div>
            </div>
          </div>
          <div className="flex shrink-0 gap-2">
            <button type="button" onClick={load} className={btnGhost}>
              Refresh
            </button>
            <button
              type="button"
              onClick={disconnect}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm font-medium text-red-300 hover:bg-red-500/20 transition-colors disabled:opacity-50"
            >
              <Link2Off className="h-4 w-4" /> Disconnect
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-white/5 text-neutral-500">
              <X className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-medium">Not connected</div>
              <div className="text-xs text-neutral-500">
                Link a GitHub account to export generated integration code directly to repositories.
              </div>
            </div>
          </div>
          <button type="button" onClick={connect} disabled={busy} className={btnPrimary}>
            <Github className="h-4 w-4" /> {busy ? 'Opening…' : 'Connect GitHub'}
          </button>
        </div>
      )}
    </div>
  );
};

export const SettingsPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const param = searchParams.get('section') as SectionKey | null;
  const active: SectionKey = param && SECTIONS.some(s => s.key === param) ? param : 'account';

  const setActive = (key: SectionKey) => setSearchParams({ section: key });

  return (
    <div className="px-6 py-10 lg:px-10">
      <PageHeader title="Settings" subtitle="Account, workspace, and integration preferences." />

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[200px_1fr]">
        <nav className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible">
          {SECTIONS.map(section => {
            const Icon = section.icon;
            const selected = active === section.key;
            return (
              <button
                key={section.key}
                type="button"
                onClick={() => setActive(section.key)}
                className={`flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                  selected ? 'bg-white/10 font-medium text-white' : 'text-neutral-400 hover:bg-white/5 hover:text-white'
                }`}
              >
                <Icon className="h-4 w-4" /> {section.label}
              </button>
            );
          })}
        </nav>

        <div className="min-w-0">
          {active === 'account' && <AccountSection />}
          {active === 'workspace' && <WorkspaceSection />}
          {active === 'keys' && <KeysSection />}
          {active === 'github' && <GitHubSection />}
        </div>
      </div>
    </div>
  );
};
