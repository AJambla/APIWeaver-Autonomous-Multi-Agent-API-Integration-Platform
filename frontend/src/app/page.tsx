"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/Button";

export default function LandingPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user) {
      router.replace("/dashboard");
    }
  }, [loading, user, router]);

  return (
    <div className="min-h-screen bg-bg-primary text-text-primary">
      <header className="flex items-center justify-between px-8 py-5">
        <div className="flex items-center gap-2 font-semibold">
          <span className="text-brand-primary">◆</span> APIWeaver
        </div>
        <div className="flex items-center gap-3">
          <Link href="/auth/login" className="text-sm text-text-secondary hover:text-text-primary">
            Sign in
          </Link>
          <Link href="/auth/login">
            <Button size="sm">Get Started</Button>
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-24 text-center">
        <h1 className="text-4xl font-bold leading-tight md:text-5xl">
          Turn API docs into production-ready integrations
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-lg text-text-secondary">
          APIWeaver parses your OpenAPI, Swagger, or Postman specs, plans the build,
          generates idiomatic Python and TypeScript clients, tests them, and exports
          SDKs, Docker images, and MCP servers.
        </p>
        <div className="mt-8 flex justify-center gap-3">
          <Link href="/auth/login">
            <Button size="lg">Start building</Button>
          </Link>
          <Link href="/auth/login">
            <Button size="lg" variant="secondary">
              View docs
            </Button>
          </Link>
        </div>
      </main>
    </div>
  );
}
