import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Lock } from 'lucide-react';

export const PrivacyPage: React.FC = () => {
  return (
    <div className="min-h-screen bg-black text-white selection:bg-white selection:text-black">
      {/* Top Header */}
      <header className="border-b border-white/10 bg-black/60 backdrop-blur-xl sticky top-0 z-50">
        <div className="max-w-4xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2 text-sm text-neutral-400 hover:text-white transition-colors">
            <ArrowLeft className="w-4 h-4" />
            Back to Home
          </Link>
          <div className="flex items-center gap-2">
            <Lock className="w-4 h-4 text-neutral-400" />
            <span className="text-sm font-medium">Privacy Policy</span>
          </div>
        </div>
      </header>

      {/* Content Container */}
      <main className="max-w-4xl mx-auto px-6 py-12">
        <div className="mb-10">
          <span className="text-xs font-mono text-neutral-400 uppercase tracking-widest">Privacy & Data Governance</span>
          <h1 className="text-3xl font-bold tracking-tight mt-2 mb-3">Privacy Policy</h1>
          <p className="text-sm text-neutral-400">Last updated: November 2, 2026</p>
        </div>

        <div className="space-y-8 text-neutral-300 text-sm leading-relaxed">
          <section className="glass-card p-6 rounded-2xl border border-white/10">
            <h2 className="text-lg font-semibold text-white mb-3">1. Information We Collect</h2>
            <p className="mb-3">
              We collect information to provide, maintain, and protect our autonomous API integration services:
            </p>
            <ul className="list-disc pl-5 space-y-1 text-neutral-400">
              <li><strong>Account Credentials:</strong> Email address, hashed password (using Argon2id with per-user salt), and full name.</li>
              <li><strong>Project Data:</strong> API specifications, documentation uploads, endpoint schemas, and test configuration scripts.</li>
              <li><strong>Target Credentials:</strong> Third-party API keys or OAuth tokens you configure for sandbox live testing.</li>
              <li><strong>Operational Logs:</strong> Request timestamps, IP addresses, audit event logs, and aggregate performance telemetry.</li>
            </ul>
          </section>

          <section className="glass-card p-6 rounded-2xl border border-white/10">
            <h2 className="text-lg font-semibold text-white mb-3">2. How Secrets & Target Credentials are Protected</h2>
            <p>
              Target API keys and OAuth tokens are encrypted at rest using AES-256-GCM authenticated encryption (or HashiCorp Vault).
              Credentials are never logged in plaintext, never exposed in LLM prompt templates, and are decrypted only inside isolated,
              ephemeral sandbox test containers.
            </p>
          </section>

          <section className="glass-card p-6 rounded-2xl border border-white/10">
            <h2 className="text-lg font-semibold text-white mb-3">3. AI Processing & Third-Party LLM Providers</h2>
            <p>
              When an agent parses your API documentation or repairs generated code, relevant schema fragments are sent to our configured
              LLM providers. Authorization tokens, cookies, and sensitive headers are stripped before transmitting traces to LLMs.
              Your data is not retained by third-party model providers for model training.
            </p>
          </section>

          <section className="glass-card p-6 rounded-2xl border border-white/10">
            <h2 className="text-lg font-semibold text-white mb-3">4. Cookies and Session Storage</h2>
            <p>
              We utilize secure, same-origin, <code>HttpOnly</code> cookies for session refresh tokens with strict CSRF protection.
              Short-lived JWT access tokens reside in memory or session storage for authorized API communication.
            </p>
          </section>

          <section className="glass-card p-6 rounded-2xl border border-white/10">
            <h2 className="text-lg font-semibold text-white mb-3">5. Data Retention & Deletion Rights (GDPR & CCPA)</h2>
            <p>
              You maintain the right to access, export, or permanently delete your organizations, projects, and associated artifact bundles
              at any time. Permanent deletion by organization owners permanently purges all project metadata, generated code, and encrypted
              secrets from database and object storage.
            </p>
          </section>
        </div>
      </main>
    </div>
  );
};
