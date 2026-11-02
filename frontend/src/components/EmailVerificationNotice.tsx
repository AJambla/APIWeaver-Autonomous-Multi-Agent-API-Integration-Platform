import React, { useState, useEffect } from 'react';
import { Mail, CheckCircle, AlertCircle, RefreshCw, ArrowLeft } from 'lucide-react';

interface EmailVerificationNoticeProps {
  email: string;
  onResend: () => Promise<void>;
  onBackToLogin: () => void;
}

export const EmailVerificationNotice: React.FC<EmailVerificationNoticeProps> = ({
  email,
  onResend,
  onBackToLogin,
}) => {
  const [resending, setResending] = useState(false);
  const [cooldown, setCooldown] = useState(60);
  const [statusMessage, setStatusMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => setCooldown(prev => prev - 1), 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  const handleResend = async () => {
    if (cooldown > 0 || resending) return;
    setResending(true);
    setStatusMessage(null);
    try {
      await onResend();
      setStatusMessage({ text: 'A fresh verification email has been sent.', type: 'success' });
      setCooldown(60);
    } catch (err) {
      setStatusMessage({
        text: err instanceof Error ? err.message : 'Failed to resend verification email.',
        type: 'error',
      });
    } finally {
      setResending(false);
    }
  };

  return (
    <div className="max-w-md w-full glass-card p-8 rounded-3xl border border-white/10 appear text-center">
      <div className="w-14 h-14 rounded-2xl bg-white/10 border border-white/20 flex items-center justify-center mx-auto mb-6 shadow-[0_0_25px_rgba(255,255,255,0.15)]">
        <Mail className="w-7 h-7 text-white" />
      </div>

      <h2 className="text-xl font-semibold tracking-tight text-white mb-2">Check your email</h2>
      <p className="text-xs text-neutral-400 mb-6 leading-relaxed">
        We sent a verification link to <span className="text-white font-medium">{email}</span>. Click the link in your email to verify your account and activate your workspace.
      </p>

      {statusMessage && (
        <div
          className={`mb-6 p-3.5 rounded-xl text-xs flex items-center justify-center gap-2 border ${
            statusMessage.type === 'success'
              ? 'bg-emerald-950/40 border-emerald-500/30 text-emerald-300'
              : 'bg-red-950/40 border-red-500/30 text-red-300'
          }`}
        >
          {statusMessage.type === 'success' ? (
            <CheckCircle className="w-4 h-4 shrink-0 text-emerald-400" />
          ) : (
            <AlertCircle className="w-4 h-4 shrink-0 text-red-400" />
          )}
          <span>{statusMessage.text}</span>
        </div>
      )}

      <div className="space-y-4">
        <button
          type="button"
          onClick={handleResend}
          disabled={cooldown > 0 || resending}
          className="w-full py-3 rounded-xl bg-white/10 border border-white/15 text-white font-medium text-xs hover:bg-white/20 transition-all disabled:opacity-40 flex items-center justify-center gap-2"
        >
          {resending ? (
            <>
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              <span>Sending...</span>
            </>
          ) : cooldown > 0 ? (
            <span>Resend email in {cooldown}s</span>
          ) : (
            <span>Resend verification email</span>
          )}
        </button>

        <button
          type="button"
          onClick={onBackToLogin}
          className="w-full py-3 rounded-xl text-neutral-400 hover:text-white transition-colors text-xs flex items-center justify-center gap-1.5"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Back to sign in</span>
        </button>
      </div>
    </div>
  );
};
