import React, { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../lib/auth-context';
import { initials } from '../lib/format';
import {
  LayoutDashboard,
  FolderKanban,
  FileCode2,
  Bot,
  Activity,
  Settings,
  Check,
  ChevronDown,
  LogOut,
  Menu,
  X,
  KeyRound,
  UserCircle,
} from 'lucide-react';

const NAV_GROUPS: Array<{ label: string; items: Array<{ to: string; label: string; icon: React.ElementType; end?: boolean }> }> = [
  {
    label: 'Workspace',
    items: [
      { to: '/dashboard/overview', label: 'Overview', icon: LayoutDashboard },
      { to: '/dashboard', label: 'Projects', icon: FolderKanban, end: true },
      { to: '/dashboard/specs', label: 'API Specs', icon: FileCode2 },
      { to: '/dashboard/agents', label: 'Agents', icon: Bot },
      { to: '/dashboard/runs', label: 'Runs', icon: Activity },
    ],
  },
];

const useDismissOnClickOutside = (onDismiss: () => void) => {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onDismiss();
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onDismiss]);
  return ref;
};

const WorkspaceSelector: React.FC = () => {
  const { organizations, organizationId, selectOrganization } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useDismissOnClickOutside(() => setOpen(false));
  const current = organizations.find(o => o.organization_id === organizationId);

  return (
    <div className="relative px-3" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        className="flex w-full items-center justify-between gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 text-left hover:bg-white/[0.06] transition-colors"
      >
        <div className="min-w-0">
          <div className="text-[11px] uppercase tracking-wider text-neutral-500">Workspace</div>
          <div className="truncate text-sm font-medium">{current?.organization_name || 'Select workspace'}</div>
        </div>
        <ChevronDown className={`h-4 w-4 shrink-0 text-neutral-500 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && organizations.length > 0 && (
        <div className="absolute left-3 right-3 z-50 mt-1 overflow-hidden rounded-xl border border-white/10 bg-neutral-900 py-1 shadow-xl">
          {organizations.map(org => (
            <button
              key={org.organization_id}
              onClick={() => {
                selectOrganization(org.organization_id);
                setOpen(false);
              }}
              className="flex w-full items-center justify-between px-4 py-2 text-left text-sm text-neutral-300 hover:bg-white/5 hover:text-white transition-colors"
            >
              <span className="truncate">{org.organization_name}</span>
              {org.organization_id === organizationId && <Check className="h-4 w-4 shrink-0" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const ProfileMenu: React.FC<{ onNavigate?: () => void }> = ({ onNavigate }) => {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useDismissOnClickOutside(() => setOpen(false));
  const navigate = useNavigate();

  const go = (path: string) => {
    setOpen(false);
    onNavigate?.();
    navigate(path);
  };

  return (
    <div className="relative px-3 pb-4" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        className="flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left hover:bg-white/5 transition-colors"
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-semibold">
          {initials(user?.full_name, user?.email)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{user?.full_name || 'Operator'}</span>
          <span className="block truncate text-xs text-neutral-500">{user?.email}</span>
        </span>
      </button>
      {open && (
        <div className="absolute bottom-full left-3 right-3 z-50 mb-1 overflow-hidden rounded-xl border border-white/10 bg-neutral-900 py-1 shadow-xl">
          <button
            onClick={() => go('/dashboard/settings')}
            className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm text-neutral-300 hover:bg-white/5 hover:text-white transition-colors"
          >
            <UserCircle className="h-4 w-4" /> Profile
          </button>
          <button
            onClick={() => go('/dashboard/settings')}
            className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm text-neutral-300 hover:bg-white/5 hover:text-white transition-colors"
          >
            <Settings className="h-4 w-4" /> Account Settings
          </button>
          <button
            onClick={() => go('/dashboard/settings?section=keys')}
            className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm text-neutral-300 hover:bg-white/5 hover:text-white transition-colors"
          >
            <KeyRound className="h-4 w-4" /> API Keys
          </button>
          <div className="my-1 border-t border-white/10" />
          <button
            onClick={logout}
            className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm text-red-400 hover:bg-red-500/10 transition-colors"
          >
            <LogOut className="h-4 w-4" /> Sign Out
          </button>
        </div>
      )}
    </div>
  );
};

const SidebarContent: React.FC<{ onNavigate?: () => void }> = ({ onNavigate }) => (
  <div className="flex h-full flex-col">
    <div className="flex h-16 shrink-0 items-center gap-2.5 px-6">
      <img src="/favicon.png" alt="" className="h-7 w-7 rounded-lg" />
      <span className="font-semibold tracking-tight">API Weaver</span>
    </div>

    <WorkspaceSelector />

    <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-6">
      {NAV_GROUPS.map(group => (
        <div key={group.label}>
          <div className="mb-1.5 px-3 text-[11px] font-medium uppercase tracking-wider text-neutral-600">
            {group.label}
          </div>
          <div className="space-y-0.5">
            {group.items.map(item => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                      isActive
                        ? 'bg-white text-black font-medium'
                        : 'text-neutral-400 hover:bg-white/5 hover:text-white'
                    }`
                  }
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span>{item.label}</span>
                </NavLink>
              );
            })}
          </div>
        </div>
      ))}
    </nav>

    <div className="border-t border-white/10 pt-2">
      <ProfileMenu onNavigate={onNavigate} />
    </div>
  </div>
);

export const DashboardLayout: React.FC = () => {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="min-h-screen bg-black text-white flex selection:bg-white selection:text-black">
      <aside className="hidden lg:flex w-64 shrink-0 border-r border-white/10 bg-neutral-950/60 backdrop-blur-xl sticky top-0 h-screen">
        <SidebarContent />
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/80 backdrop-blur-md" onClick={() => setMobileOpen(false)} />
          <aside className="relative w-64 h-full border-r border-white/10 bg-neutral-950">
            <button
              onClick={() => setMobileOpen(false)}
              className="absolute top-5 right-4 z-10 p-2 text-neutral-400 hover:text-white transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
            <SidebarContent onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex-1 min-w-0 flex flex-col">
        <div className="lg:hidden sticky top-0 z-40 flex items-center gap-3 border-b border-white/10 bg-black/60 backdrop-blur-xl px-4 h-16">
          <button
            onClick={() => setMobileOpen(true)}
            className="rounded-lg p-2 text-neutral-300 hover:bg-white/5 hover:text-white transition-colors border border-white/10"
            title="Open menu"
          >
            <Menu className="w-5 h-5" />
          </button>
          <div className="flex items-center gap-2">
            <img src="/favicon.png" alt="" className="h-6 w-6 rounded-md" />
            <span className="font-semibold tracking-tight">API Weaver</span>
          </div>
        </div>
        <main className="flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
};
