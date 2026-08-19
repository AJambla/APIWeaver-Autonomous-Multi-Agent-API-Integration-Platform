"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useToast } from "@/components/Toast";
import { ApiError } from "@/lib/types";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";

export default function LoginPage() {
  const { login, register } = useAuth();
  const router = useRouter();
  const { notify } = useToast();

  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register({
          email,
          password,
          full_name: fullName,
          organization_name: orgName,
        });
      }
      router.push("/dashboard");
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Something went wrong. Please try again.";
      notify(message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg-primary p-6">
      <Card className="w-full max-w-md">
        <h1 className="mb-1 text-2xl font-bold">
          {mode === "login" ? "Sign in" : "Create your account"}
        </h1>
        <p className="mb-6 text-sm text-text-secondary">
          {mode === "login"
            ? "Welcome back to APIWeaver."
            : "Start generating API integrations in minutes."}
        </p>

        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <Field label="Email">
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-border bg-bg-primary px-3 py-2 text-sm"
            />
          </Field>
          <Field label="Password">
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-border bg-bg-primary px-3 py-2 text-sm"
            />
          </Field>

          {mode === "register" && (
            <>
              <Field label="Full name">
                <input
                  required
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  className="w-full rounded-md border border-border bg-bg-primary px-3 py-2 text-sm"
                />
              </Field>
              <Field label="Organization name">
                <input
                  required
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  className="w-full rounded-md border border-border bg-bg-primary px-3 py-2 text-sm"
                />
              </Field>
            </>
          )}

          <Button type="submit" loading={busy} className="mt-2">
            {mode === "login" ? "Sign in" : "Create account"}
          </Button>
        </form>

        <p className="mt-4 text-center text-sm text-text-secondary">
          {mode === "login" ? (
            <>
              No account?{" "}
              <button
                className="text-brand-primary hover:underline"
                onClick={() => setMode("register")}
              >
                Sign up
              </button>
            </>
          ) : (
            <>
              Already have an account?{" "}
              <button
                className="text-brand-primary hover:underline"
                onClick={() => setMode("login")}
              >
                Sign in
              </button>
            </>
          )}
        </p>

        {mode === "login" && (
          <p className="mt-2 text-center text-xs text-text-secondary">
            <Link href="/dashboard" className="hover:underline">
              Continue without an account (demo)
            </Link>
          </p>
        )}
      </Card>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-text-secondary">{label}</span>
      {children}
    </label>
  );
}
