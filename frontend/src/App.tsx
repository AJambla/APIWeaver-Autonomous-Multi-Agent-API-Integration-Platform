import React, { Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { RouteErrorBoundary } from './components/ErrorBoundary';
import { AuthProvider, useAuth } from './lib/auth-context';

const LandingPage = React.lazy(() => import('./pages/LandingPage').then(m => ({ default: m.LandingPage })));
const LoginPage = React.lazy(() => import('./pages/LoginPage').then(m => ({ default: m.LoginPage })));
const RegisterPage = React.lazy(() => import('./pages/RegisterPage').then(m => ({ default: m.RegisterPage })));
const DashboardLayout = React.lazy(() => import('./components/DashboardLayout').then(m => ({ default: m.DashboardLayout })));
const DashboardPage = React.lazy(() => import('./pages/DashboardPage').then(m => ({ default: m.DashboardPage })));
const OverviewPage = React.lazy(() => import('./pages/OverviewPage').then(m => ({ default: m.OverviewPage })));
const SpecsPage = React.lazy(() => import('./pages/SpecsPage').then(m => ({ default: m.SpecsPage })));
const SpecDetailPage = React.lazy(() => import('./pages/SpecDetailPage').then(m => ({ default: m.SpecDetailPage })));
const AgentsPage = React.lazy(() => import('./pages/AgentsPage').then(m => ({ default: m.AgentsPage })));
const RunsPage = React.lazy(() => import('./pages/RunsPage').then(m => ({ default: m.RunsPage })));
const RunDetailPage = React.lazy(() => import('./pages/RunDetailPage').then(m => ({ default: m.RunDetailPage })));
const SettingsPage = React.lazy(() => import('./pages/SettingsPage').then(m => ({ default: m.SettingsPage })));
const ProjectWorkspace = React.lazy(() => import('./pages/ProjectWorkspace').then(m => ({ default: m.ProjectWorkspace })));

const PageFallback: React.FC = () => (
  <div className="min-h-[50vh] flex items-center justify-center">
    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-white" />
  </div>
);

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
        <Suspense fallback={<PageFallback />}>
          <Routes>
            <Route path="/" element={<RouteErrorBoundary><LandingPage /></RouteErrorBoundary>} />
            <Route path="/login" element={<RouteErrorBoundary><LoginPage /></RouteErrorBoundary>} />
            <Route path="/register" element={<RouteErrorBoundary><RegisterPage /></RouteErrorBoundary>} />
            <Route
              path="/dashboard"
              element={
                <ProtectedRoute>
                  <RouteErrorBoundary>
                    <DashboardLayout />
                  </RouteErrorBoundary>
                </ProtectedRoute>
              }
            >
              <Route index element={<RouteErrorBoundary compact><DashboardPage /></RouteErrorBoundary>} />
              <Route path="overview" element={<RouteErrorBoundary compact><OverviewPage /></RouteErrorBoundary>} />
              <Route path="specs" element={<RouteErrorBoundary compact><SpecsPage /></RouteErrorBoundary>} />
              <Route path="specs/:projectId" element={<RouteErrorBoundary compact><SpecDetailPage /></RouteErrorBoundary>} />
              <Route path="agents" element={<RouteErrorBoundary compact><AgentsPage /></RouteErrorBoundary>} />
              <Route path="runs" element={<RouteErrorBoundary compact><RunsPage /></RouteErrorBoundary>} />
              <Route path="runs/:runId" element={<RouteErrorBoundary compact><RunDetailPage /></RouteErrorBoundary>} />
              <Route path="settings" element={<RouteErrorBoundary compact><SettingsPage /></RouteErrorBoundary>} />
            </Route>
            <Route
              path="/projects/:id"
              element={
                <ProtectedRoute>
                  <RouteErrorBoundary>
                    <ProjectWorkspace />
                  </RouteErrorBoundary>
                </ProtectedRoute>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </AuthProvider>
  );
};

export default App;
