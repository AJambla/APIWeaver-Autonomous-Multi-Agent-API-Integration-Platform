import React, { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../lib/auth-context';
import {
  LayoutDashboard,
  FolderKanban,
  FileCode2,
  Bot,
  Activity,
  Settings,
  LogOut,
  Menu,
  X,
} from 'lucide-react';

const navItems = [
  { to: '/dashboard/overview', label: 'Overview', icon: LayoutDashboard },
  { to: '/dashboard', label: 'Projects', icon: FolderKanban, end: true },
  { to: '/dashboard/specs', label: 'API Specs', icon: FileCode2 },
  { to: '/dashboard/agents', label: 'Agents', icon: Bot },
  { to: '/dashboard/runs', label: 'Runs', icon: Activity },
];

const SidebarContent: React.FC<{ onNavigate?: () => void }> = ({ onNavigate }) => {
  const { user, logout } = useAuth();

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-6 h-20 shrink-0">
        <div className="w-9 h-9 rounded-xl bg-white text-black flex items-center justify-center font-bold tracking-tighter text-lg shadow-[0_0_20px_rgba(255,255,255,0.3)]">
          AW
        </div>
        <span className="font-semibold tracking-tight text-lg">API Weaver</span>
      </div>

      <nav className="flex-1 px-3 py-6 space-y-1 overflow-y-auto">
        {navItems.map(item => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              onClick={onNavigate}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm transition-colors ${
                  isActive
                    ? 'bg-white text-black font-medium shadow-[0_0_20px_rgba(255,255,255,0.15)]'
                    : 'text-neutral-400 hover:text-white hover:bg-white/5'
                }`
              }
            >
              <Icon className="w-4 h-4 shrink-0" />
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </nav>

      <div className="px-3 pb-6 space-y-1 border-t border-white/10 pt-6 mx-3">
        <NavLink
          to="/dashboard/settings"
          onClick={onNavigate}
          className={({ isActive }) =>
            `flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm transition-colors ${
              isActive
                ? 'bg-white text-black font-medium shadow-[0_0_20px_rgba(255,255,255,0.15)]'
                : 'text-neutral-400 hover:text-white hover:bg-white/5'
            }`
          }
        >
          <Settings className="w-4 h-4 shrink-0" />
          <span>Settings</span>
        </NavLink>

        <div className="flex items-center justify-between gap-3 px-4 pt-4">
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">{user?.full_name || user?.email || 'Operator'}</div>
            <div className="text-xs text-neutral-500 truncate">{user?.email}</div>
          </div>
          <button
            onClick={logout}
            className="p-2 rounded-xl glass-pill hover:bg-white/10 text-neutral-300 hover:text-white transition-colors shrink-0"
            title="Sign out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
};

export const DashboardLayout: React.FC = () => {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="min-h-screen bg-black text-white flex selection:bg-white selection:text-black">
      {/* Desktop sidebar */}
      <aside className="hidden lg:flex w-64 shrink-0 border-r border-white/10 bg-neutral-950/60 backdrop-blur-xl sticky top-0 h-screen">
        <SidebarContent />
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/80 backdrop-blur-md" onClick={() => setMobileOpen(false)} />
          <aside className="relative w-64 h-full border-r border-white/10 bg-neutral-950">
            <button
              onClick={() => setMobileOpen(false)}
              className="absolute top-6 right-4 p-2 text-neutral-400 hover:text-white transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
            <SidebarContent onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 min-w-0 flex flex-col">
        <div className="lg:hidden sticky top-0 z-40 flex items-center gap-3 border-b border-white/10 bg-black/60 backdrop-blur-xl px-4 h-16">
          <button
            onClick={() => setMobileOpen(true)}
            className="p-2 rounded-xl glass-pill text-neutral-300 hover:text-white transition-colors"
            title="Open menu"
          >
            <Menu className="w-5 h-5" />
          </button>
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-white text-black flex items-center justify-center font-bold text-xs">
              AW
            </div>
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
