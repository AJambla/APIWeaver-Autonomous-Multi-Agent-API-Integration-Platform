import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './lib/auth-context';
import { LandingPage } from './pages/LandingPage';
import { LoginPage } from './pages/LoginPage';
import { RegisterPage } from './pages/RegisterPage';
import { DashboardPage } from './pages/DashboardPage';
import { ProjectWorkspace } from './pages/ProjectWorkspace';
import { DashboardLayout } from './components/DashboardLayout';
import { PlaceholderPage } from './pages/PlaceholderPage';

const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen bg-black text-white flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-white" />
      </div>
    );
  }
  return user ? <>{children}</> : <Navigate to="/login" replace />;
};

export const App: React.FC = () => {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <DashboardLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<DashboardPage />} />
            <Route
              path="overview"
              element={
                <PlaceholderPage
                  title="Overview"
                  description="A cross-project summary of runs, agent activity, and export health is being built."
                />
              }
            />
            <Route
              path="specs"
              element={
                <PlaceholderPage
                  title="API Specs"
                  description="Browse and manage every uploaded OpenAPI spec and schema across your projects."
                />
              }
            />
            <Route
              path="agents"
              element={
                <PlaceholderPage
                  title="Agents"
                  description="Monitor the autonomous agents that build, test, and repair your workflows."
                />
              }
            />
            <Route
              path="runs"
              element={
                <PlaceholderPage
                  title="Runs"
                  description="Track every workflow execution, its live event stream, and its outcome."
                />
              }
            />
            <Route
              path="settings"
              element={
                <PlaceholderPage
                  title="Settings"
                  description="Organization, member, and integration settings will live here."
                />
              }
            />
          </Route>
          <Route
            path="/projects/:id"
            element={
              <ProtectedRoute>
                <ProjectWorkspace />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
};

export default App;
