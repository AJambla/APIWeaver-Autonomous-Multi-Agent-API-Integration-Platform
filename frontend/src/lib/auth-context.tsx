import React, { createContext, useContext, useState, useEffect } from 'react';
import { User } from './types';
import { apiFetch } from './api';

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName?: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = sessionStorage.getItem('access_token');
    if (!token) {
      setLoading(false);
      return;
    }

    apiFetch<User>('/auth/me')
      .then(userData => setUser(userData))
      .catch(() => sessionStorage.removeItem('access_token'))
      .finally(() => setLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    const data = await apiFetch<{ access_token: string; user?: User }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    sessionStorage.setItem('access_token', data.access_token);
    if (data.user) {
      setUser(data.user);
    } else {
      const me = await apiFetch<User>('/auth/me');
      setUser(me);
    }
  };

  const register = async (email: string, password: string, fullName?: string) => {
    const orgName = email.split('@')[1]?.split('.')[0] || 'organization';
    await apiFetch('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, full_name: fullName || email.split('@')[0], organization_name: orgName }),
    });
    await login(email, password);
  };

  const logout = () => {
    sessionStorage.removeItem('access_token');
    setUser(null);
    window.location.href = '/login';
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
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
