import React, { createContext, useContext, useEffect, useState } from 'react';
import { AuthTokens, MeResponse, OrganizationMembership, User } from './types';
import { apiFetch } from './api';

interface AuthContextType {
  user: User | null;
  organizationId: string | null;
  organizations: OrganizationMembership[];
  selectOrganization: (orgId: string) => void;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName?: string, organizationName?: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);
const ORG_STORAGE_KEY = 'apiweaver.organization';

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [organizations, setOrganizations] = useState<OrganizationMembership[]>([]);
  const [organizationId, setOrganizationId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const setCurrentUser = (data: MeResponse) => {
    setUser(data.user);
    setOrganizations(data.organizations);
    // Restore the workspace chosen earlier in this browser, if still a member of it.
    let remembered: string | null = null;
    try {
      remembered = localStorage.getItem(ORG_STORAGE_KEY);
    } catch {
      /* storage unavailable: fall back to the first organization */
    }
    const stillMember = data.organizations.some(o => o.organization_id === remembered);
    setOrganizationId(stillMember ? remembered : data.organizations[0]?.organization_id ?? null);
  };

  const selectOrganization = (orgId: string) => {
    setOrganizationId(orgId);
    try {
      localStorage.setItem(ORG_STORAGE_KEY, orgId);
    } catch {
      /* best effort */
    }
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

  const register = async (email: string, password: string, fullName?: string, organizationName?: string) => {
    const userPart = fullName?.trim() || email.split('@')[0] || 'User';
    const domainPart = email.split('@')[1]?.split('.')[0] || 'workspace';
    const randomSuffix = Math.random().toString(36).substring(2, 6);
    const resolvedOrgName = organizationName?.trim() || `${userPart}'s ${domainPart} ${randomSuffix}`;
    const tokens = await apiFetch<AuthTokens>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({
        email,
        password,
        full_name: fullName || email.split('@')[0],
        organization_name: resolvedOrgName,
      }),
    });
    sessionStorage.setItem('access_token', tokens.access_token);
    if (tokens.refresh_token) {
      sessionStorage.setItem('refresh_token', tokens.refresh_token);
    }
    const me = await apiFetch<MeResponse>('/auth/me');
    setCurrentUser(me);
  };

  const logout = async () => {
    const refreshToken = sessionStorage.getItem('refresh_token');
    try {
      await apiFetch('/auth/logout', {
        method: 'POST',
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch {
      // Server-side revocation failed — clear local state regardless.
    }
    clearSession();
    window.location.href = '/login';
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        organizationId,
        organizations,
        selectOrganization,
        loading,
        login,
        register,
        logout,
      }}
    >
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
