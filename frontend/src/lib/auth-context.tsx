"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import {
  clearStoredTokens,
  clearStoredUser,
  getStoredUser,
  setStoredTokens,
  setStoredUser,
} from "@/lib/auth";
import { apiFetch } from "@/lib/api";
import type { User } from "@/lib/types";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (input: {
    email: string;
    password: string;
    full_name: string;
    organization_name: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

interface BackendMeResponse {
  user: {
    id: string;
    email: string;
    full_name: string;
    mfa_enabled: boolean;
  };
  organizations: Array<{
    organization_id: string;
    organization_name: string;
    role: string;
  }>;
}

async function fetchMe(): Promise<User> {
  const data = await apiFetch<BackendMeResponse>("/auth/me");
  const firstOrg = data.organizations[0];
  return {
    id: data.user.id,
    email: data.user.email,
    full_name: data.user.full_name,
    organization_id: firstOrg?.organization_id ?? "",
    organization_name: firstOrg?.organization_name,
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    (async () => {
      const stored = getStoredUser();
      if (stored) {
        try {
          const me = await fetchMe();
          if (active) setUser(me);
        } catch {
          if (active) setUser(null);
        }
      }
      if (active) setLoading(false);
    })();
    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await apiFetch<{
      access_token: string;
      refresh_token: string;
      expires_in: number;
      token_type: string;
    }>("/auth/login", {
      method: "POST",
      body: { email, password },
    });
    setStoredTokens(tokens);
    const me = await fetchMe();
    setStoredUser(me);
    setUser(me);
  }, []);

  const register = useCallback(
    async (input: {
      email: string;
      password: string;
      full_name: string;
      organization_name: string;
    }) => {
      const tokens = await apiFetch<{
        access_token: string;
        refresh_token: string;
        expires_in: number;
        token_type: string;
      }>("/auth/register", {
        method: "POST",
        body: input,
      });
      setStoredTokens(tokens);
      const me = await fetchMe();
      setStoredUser(me);
      setUser(me);
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await apiFetch("/auth/logout", { method: "POST" });
    } catch {
      // ignore — clear local state regardless
    }
    clearStoredTokens();
    clearStoredUser();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
