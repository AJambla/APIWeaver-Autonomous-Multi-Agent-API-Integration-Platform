"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/Button";

const PROJECT_NAV = [
  { id: "overview", label: "Overview", href: "" },
  { id: "upload", label: "Upload", href: "/upload" },
  { id: "plan", label: "Plan", href: "/plan" },
  { id: "build", label: "Build", href: "/build" },
  { id: "test", label: "Test", href: "/test" },
  { id: "monitoring", label: "Monitoring", href: "/monitoring" },
  { id: "export", label: "Export", href: "/export" },
  { id: "logs", label: "Logs", href: "/logs" },
  { id: "history", label: "History", href: "/history" },
  { id: "settings", label: "Settings", href: "/settings" },
];

export function AppShell({
  projectId,
  children,
}: {
  projectId?: string;
  children: React.ReactNode;
}) {
  const { user, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  const nav = projectId
    ? PROJECT_NAV.map((n) => {
        const href = `/projects/${projectId}${n.href}`;
        const active = pathname === href || (n.id === "overview" && pathname === `/projects/${projectId}`);
        return { label: n.label, href, active };
      })
    : [];

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b border-border bg-bg-secondary px-6 py-3">
        <Link href="/dashboard" className="flex items-center gap-2 font-semibold">
          <span className="text-brand-primary">◆</span> APIWeaver
        </Link>
        <nav className="flex items-center gap-4 text-sm text-text-secondary">
          <Link href="/dashboard">Projects</Link>
          <Link href="/dashboard">Docs</Link>
          <span className="text-text-secondary/60">Marketplace</span>
          {user && (
            <span className="text-text-primary">{user.full_name || user.email}</span>
          )}
          {user && (
            <Button
              variant="ghost"
              size="sm"
              onClick={async () => {
                await logout();
                router.push("/auth/login");
              }}
            >
              Sign out
            </Button>
          )}
        </nav>
      </header>
      <div className="flex flex-1">
        {projectId && nav.length > 0 && (
          <aside className="w-56 shrink-0 border-r border-border bg-bg-secondary p-3">
            <nav className="flex flex-col gap-1">
              {nav.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={
                    "rounded-md px-3 py-2 text-sm transition-colors " +
                    (item.active
                      ? "bg-bg-tertiary font-medium text-text-primary"
                      : "text-text-secondary hover:bg-bg-tertiary")
                  }
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </aside>
        )}
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
