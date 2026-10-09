import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { RouteErrorBoundary } from './components/ErrorBoundary';
import { AuthProvider, useAuth } from './lib/auth-context';
import { LandingPage } from './pages/LandingPage';
import { LoginPage } from './pages/LoginPage';
import { RegisterPage } from './pages/RegisterPage';
import { DashboardPage } from './pages/DashboardPage';
import { OverviewPage } from './pages/OverviewPage';
import { SpecsPage } from './pages/SpecsPage';
import { SpecDetailPage } from './pages/SpecDetailPage';
import { AgentsPage } from './pages/AgentsPage';
import { RunsPage } from './pages/RunsPage';
import { RunDetailPage } from './pages/RunDetailPage';
import { SettingsPage } from './pages/SettingsPage';
import { ProjectWorkspace } from './pages/ProjectWorkspace';
import { DashboardLayout } from './components/DashboardLayout';

const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, loading, connectionError, retrySession } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <div className="min-h-screen bg-black text-white flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-white" />
      </div>
    );
  }
  if (!user && connectionError) {
    return (
      <div className="min-h-screen bg-black text-white flex flex-col items-center justify-center gap-4 px-4 text-center">
        <p className="text-neutral-300">{connectionError}</p>
        <button
          type="button"
          onClick={retrySession}
          className="rounded-md bg-white px-4 py-2 text-sm font-medium text-black hover:bg-neutral-200"
        >
          Retry
        </button>
      </div>
    );
  }
  // Remember where the user was going so login can send them back there.
  return user ? <>{children}</> : <Navigate to="/login" replace state={{ from: location }} />;
};

export const App: React.FC = () => {
  return (
    <AuthProvider>
      <BrowserRouter>
        <RouteErrorBoundary>
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
            <Route path="overview" element={<OverviewPage />} />
            <Route path="specs" element={<SpecsPage />} />
            <Route path="specs/:projectId" element={<SpecDetailPage />} />
            <Route path="agents" element={<AgentsPage />} />
            <Route path="runs" element={<RunsPage />} />
            <Route path="runs/:runId" element={<RunDetailPage />} />
            <Route path="settings" element={<SettingsPage />} />
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
        </RouteErrorBoundary>
      </BrowserRouter>
    </AuthProvider>
  );
};

export default App;
