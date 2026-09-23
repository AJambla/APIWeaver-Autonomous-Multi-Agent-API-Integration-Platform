import React, { createContext, useContext, useEffect, useState } from 'react';
import { AuthTokens, MeResponse, User } from './types';
import { apiFetch } from './api';

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
  getRefreshToken,
  setStoredTokens,
  setStoredUser,
} from "@/lib/auth";
import { apiFetch } from "@/lib/api";
import type { User } from "@/lib/types";

interface AuthContextValue {
  user: User | null;
  organizationId: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName?: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [organizationId, setOrganizationId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const setCurrentUser = (data: MeResponse) => {
    setUser(data.user);
    setOrganizationId(data.organizations[0]?.organization_id ?? null);
  };

  const clearSession = () => {
    sessionStorage.removeItem('access_token');
    sessionStorage.removeItem('refresh_token');
    setUser(null);
    setOrganizationId(null);
  };

  useEffect(() => {
    if (!sessionStorage.getItem('access_token')) {
      setLoading(false);
      return;
    }

    apiFetch<MeResponse>('/auth/me')
      .then(setCurrentUser)
      .catch(clearSession)
      .finally(() => setLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    const tokens = await apiFetch<AuthTokens>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    sessionStorage.setItem('access_token', tokens.access_token);
    if (tokens.refresh_token) {
      sessionStorage.setItem('refresh_token', tokens.refresh_token);
    }
    const me = await apiFetch<MeResponse>('/auth/me');
    setCurrentUser(me);
  };

  const logout = useCallback(async () => {
    try {
      const refreshToken = getRefreshToken();
      await apiFetch("/auth/logout", {
        method: "POST",
        body: { refresh_token: refreshToken },
      });
    } catch {
      // ignore — clear local state regardless
    }
    const me = await apiFetch<MeResponse>('/auth/me');
    setCurrentUser(me);
  };

  const logout = () => {
    clearSession();
    window.location.href = '/login';
  };

  return (
    <AuthContext.Provider value={{ user, organizationId, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
