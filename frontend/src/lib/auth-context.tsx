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
  register: (email: string, password: string, fullName?: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [organizations, setOrganizations] = useState<OrganizationMembership[]>([]);
  const [organizationId, setOrganizationId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const setCurrentUser = (data: MeResponse) => {
    setUser(data.user);
    setOrganizations(data.organizations);
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

  const register = async (email: string, password: string, fullName?: string) => {
    const organizationName = email.split('@')[1]?.split('.')[0] || 'organization';
    const tokens = await apiFetch<AuthTokens>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({
        email,
        password,
        full_name: fullName || email.split('@')[0],
        organization_name: organizationName,
      }),
    });
    sessionStorage.setItem('access_token', tokens.access_token);
    if (tokens.refresh_token) {
      sessionStorage.setItem('refresh_token', tokens.refresh_token);
    }
    const me = await apiFetch<MeResponse>('/auth/me');
    setCurrentUser(me);
  };

  const logout = () => {
    clearSession();
    window.location.href = '/login';
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        organizationId,
        organizations,
        selectOrganization: setOrganizationId,
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
