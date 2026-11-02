import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../lib/auth-context';
import { ArrowLeft, Lock, Mail, AlertCircle } from 'lucide-react';
import { EmailVerificationNotice } from '../components/EmailVerificationNotice';

/** Where ProtectedRoute was sending the user before login, if it is an in-app path.
 * Only a same-app absolute path is honoured ("/x", never "//host" or a full URL). */
function returnPath(state: unknown): string {
  const pathname = (state as { from?: { pathname?: unknown } } | null)?.from?.pathname;
  return typeof pathname === 'string' && pathname.startsWith('/') && !pathname.startsWith('//')
    ? pathname
    : '/dashboard';
}

export const LoginPage: React.FC = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [unverifiedEmail, setUnverifiedEmail] = useState<string | null>(null);

  const { loginWithFirebase, loginWithGoogle, resendVerification } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const result = await loginWithFirebase(email, password);
      if (result.needsVerification) {
        setUnverifiedEmail(email);
        return;
      }
      navigate(returnPath(location.state), { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed');
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleSignIn = async () => {
    setError('');
    setGoogleLoading(true);
    try {
      await loginWithGoogle();
      navigate(returnPath(location.state), { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Google sign-in failed');
    } finally {
      setGoogleLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-black text-white flex flex-col justify-center items-center px-6 relative">
      <Link to="/" className="absolute top-8 left-8 flex items-center gap-2 text-neutral-400 hover:text-white transition-colors text-sm">
        <ArrowLeft className="w-4 h-4" />
        <span>Back to home</span>
      </Link>

      {unverifiedEmail ? (
        <EmailVerificationNotice
          email={unverifiedEmail}
          onResend={resendVerification}
          onBackToLogin={() => setUnverifiedEmail(null)}
        />
      ) : (
        <div className="max-w-md w-full glass-card p-8 rounded-3xl border border-white/10 appear">
          <div className="flex items-center gap-3 mb-8">
            <div className="w-10 h-10 rounded-xl bg-white text-black flex items-center justify-center font-bold text-lg shadow-[0_0_20px_rgba(255,255,255,0.3)]">
              AW
            </div>
            <div>
              <h1 className="text-xl font-semibold tracking-tight">Welcome back</h1>
              <p className="text-xs text-neutral-400">Sign in to your API Weaver workspace</p>
            </div>
          </div>

          {error && (
            <div className="mb-6 p-4 rounded-xl bg-red-950/40 border border-red-500/30 text-red-300 text-xs flex items-center gap-3">
              <AlertCircle className="w-4 h-4 shrink-0 text-red-400" />
              <span>{error}</span>
            </div>
          )}

          {/* 1-Click Google Sign In */}
          <button
            type="button"
            onClick={handleGoogleSignIn}
            disabled={loading || googleLoading}
            className="w-full py-3.5 px-4 rounded-xl bg-neutral-900 border border-white/15 hover:bg-neutral-800 text-white font-medium text-sm flex items-center justify-center gap-3 transition-colors mb-6 shadow-sm disabled:opacity-50"
          >
            <svg className="w-4 h-4 shrink-0" viewBox="0 0 24 24">
              <path
                fill="#4285F4"
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
              />
              <path
                fill="#34A853"
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              />
              <path
                fill="#FBBC05"
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
              />
              <path
                fill="#EA4335"
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
              />
            </svg>
            <span>{googleLoading ? 'Signing in with Google...' : 'Continue with Google'}</span>
          </button>

          <div className="relative flex items-center justify-center mb-6">
            <div className="border-t border-white/10 w-full" />
            <span className="bg-black px-3 text-[11px] text-neutral-500 uppercase tracking-wider shrink-0">
              or continue with email
            </span>
            <div className="border-t border-white/10 w-full" />
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-xs font-medium text-neutral-300 mb-2">Email address</label>
              <div className="relative">
                <Mail className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500" />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder="name@company.com"
                  className="w-full bg-neutral-900 border border-white/15 rounded-xl px-4 py-3 pl-11 text-sm text-white placeholder-neutral-600 focus:outline-none focus:border-white transition-colors"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-neutral-300 mb-2">Password</label>
              <div className="relative">
                <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500" />
                <input
                  type="password"
                  required
                  maxLength={256}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full bg-neutral-900 border border-white/15 rounded-xl px-4 py-3 pl-11 text-sm text-white placeholder-neutral-600 focus:outline-none focus:border-white transition-colors"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading || googleLoading}
              className="w-full py-3.5 rounded-xl bg-white text-black font-medium text-sm hover:bg-neutral-200 transition-all shadow-[0_0_20px_rgba(255,255,255,0.2)] disabled:opacity-50"
            >
              {loading ? 'Authenticating...' : 'Sign in'}
            </button>
          </form>

          <div className="mt-8 text-center text-xs text-neutral-400">
            Don't have an account?{' '}
            <Link to="/register" className="text-white font-medium hover:underline">
              Create workspace
            </Link>
          </div>
        </div>
      )}
    </div>
  );
};
