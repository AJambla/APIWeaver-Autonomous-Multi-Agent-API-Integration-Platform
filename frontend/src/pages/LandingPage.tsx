import React from 'react';
import { Link } from 'react-router-dom';
import { Shield, Cpu, Zap, ArrowRight, CheckCircle2, ChevronRight, Play, Activity } from 'lucide-react';

export const LandingPage: React.FC = () => {
  return (
    <div className="min-h-screen bg-black text-white overflow-x-hidden selection:bg-white selection:text-black">
      {/* Background ambient glow */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[1000px] h-[500px] bg-gradient-to-b from-white/10 via-white/5 to-transparent blur-[120px] pointer-events-none rounded-full" />

      {/* Header */}
      <header className="fixed top-0 left-0 right-0 z-50 border-b border-white/10 bg-black/60 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-6 h-20 grid grid-cols-3 items-center">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-white text-black flex items-center justify-center font-bold tracking-tighter text-lg shadow-[0_0_20px_rgba(255,255,255,0.3)]">
              AW
            </div>
            <span className="font-semibold tracking-tight text-lg">API Weaver</span>
          </div>

          <nav className="hidden md:flex items-center justify-center">
            <div className="glass-pill px-6 py-2.5 rounded-full flex items-center gap-8 text-sm text-neutral-300">
              <a href="#benefits" className="hover:text-white transition-colors">Benefits</a>
              <a href="#how-it-works" className="hover:text-white transition-colors">How it works</a>
              <a href="#faqs" className="hover:text-white transition-colors">FAQs</a>
              <a href="#pricing" className="hover:text-white transition-colors">Pricing</a>
            </div>
          </nav>

          <div className="flex items-center justify-end gap-4">
            <Link to="/login" className="text-sm text-neutral-300 hover:text-white transition-colors px-4 py-2">
              Sign in
            </Link>
            <Link
              to="/register"
              className="px-5 py-2.5 rounded-full bg-white text-black text-sm font-medium hover:bg-neutral-200 transition-all shadow-[0_0_25px_rgba(255,255,255,0.2)]"
            >
              Get Started
            </Link>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section className="relative pt-36 pb-24 md:pt-48 md:pb-36 flex flex-col items-center justify-center text-center px-6">
        <div className="absolute inset-0 overflow-hidden opacity-25 pointer-events-none z-0">
          <video
            autoPlay
            loop
            muted
            playsInline
            className="w-full h-full object-cover filter contrast-125"
            src="https://d8j0ntlcm91z4.cloudfront.net/public/hero-bg.mp4"
          />
          <div className="absolute inset-0 bg-gradient-to-b from-black via-black/80 to-black" />
        </div>

        <div className="relative z-10 max-w-4xl mx-auto flex flex-col items-center appear">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-white/20 bg-white/5 backdrop-blur-md text-xs font-medium text-neutral-200 mb-8 shadow-inner">
            <Activity className="w-3.5 h-3.5 text-white animate-pulse" />
            <span>Vesper.ai Operational AI Infrastructure</span>
            <ChevronRight className="w-3.5 h-3.5 text-neutral-400" />
          </div>

          <h1 className="text-5xl md:text-7xl lg:text-8xl font-normal tracking-tight leading-[1.05] mb-8">
            Train AI agents on your workflows in <span className="font-serif-italic font-light text-neutral-300">minutes</span>
          </h1>

          <p className="text-lg md:text-xl text-neutral-400 max-w-2xl font-light leading-relaxed mb-12">
            Transform complex OpenAPI specs, database schemas, and documentation into autonomous, self-healing engineering workflows with military-grade precision.
          </p>

          <div className="flex flex-col sm:flex-row items-center gap-4 w-full justify-center">
            <Link
              to="/register"
              className="w-full sm:w-auto px-8 py-4 rounded-full bg-white text-black font-medium text-base hover:bg-neutral-200 transition-all flex items-center justify-center gap-3 shadow-[0_0_35px_rgba(255,255,255,0.25)] group"
            >
              <span>Deploy Infrastructure</span>
              <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </Link>
            <Link
              to="/login"
              className="w-full sm:w-auto px-8 py-4 rounded-full glass-pill text-white font-medium text-base hover:bg-white/10 transition-all flex items-center justify-center gap-3"
            >
              <Play className="w-4 h-4 fill-white" />
              <span>Watch Architecture Demo</span>
            </Link>
          </div>
        </div>
      </section>

      {/* Stats Footer */}
      <section className="border-y border-white/10 bg-neutral-950/50 backdrop-blur-md py-12">
        <div className="max-w-7xl mx-auto px-6 grid grid-cols-1 md:grid-cols-3 gap-8 text-center md:text-left">
          <div className="glass-card p-8 rounded-2xl flex flex-col gap-2">
            <div className="text-4xl md:text-5xl font-semibold tracking-tight">10.4M+</div>
            <div className="text-sm text-neutral-400 font-medium">Workflows Automated Monthly</div>
            <div className="text-xs text-neutral-500 mt-2 flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-white" /> 99.99% Execution uptime across clusters
            </div>
          </div>

          <div className="glass-card p-8 rounded-2xl flex flex-col gap-2">
            <div className="text-4xl md:text-5xl font-semibold tracking-tight">84.2%</div>
            <div className="text-sm text-neutral-400 font-medium">Manual Operation Reduction</div>
            <div className="text-xs text-neutral-500 mt-2 flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-white" /> Self-healing DAG recovery loops
            </div>
          </div>

          <div className="glass-card p-8 rounded-2xl flex flex-col gap-2">
            <div className="text-4xl md:text-5xl font-semibold tracking-tight">1,250+</div>
            <div className="text-sm text-neutral-400 font-medium">Operational Teams Onboarded</div>
            <div className="text-xs text-neutral-500 mt-2 flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-white" /> Enterprise compliance & SOC2 Type II
            </div>
          </div>
        </div>
      </section>

      {/* Benefits Section */}
      <section id="benefits" className="py-28 px-6 max-w-7xl mx-auto">
        <div className="text-center max-w-3xl mx-auto mb-20">
          <h2 className="text-3xl md:text-5xl font-normal tracking-tight mb-6">
            Engineered for <span className="font-serif-italic text-neutral-300">autonomous</span> scale
          </h2>
          <p className="text-neutral-400 font-light text-base md:text-lg">
            Built from the ground up to replace fragile brittle scripts with resilient agentic workflows.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          <div className="glass-card p-8 rounded-2xl border border-white/10 hover:border-white/30 transition-all group">
            <div className="w-12 h-12 rounded-xl bg-white/10 flex items-center justify-center text-white mb-6 group-hover:scale-110 transition-transform">
              <Cpu className="w-6 h-6" />
            </div>
            <h3 className="text-xl font-medium mb-3">Topological DAG Planning</h3>
            <p className="text-neutral-400 text-sm leading-relaxed">
              Automatically parses API specifications and generates optimized execution graphs with dependency validation and automated rollback safety.
            </p>
          </div>

          <div className="glass-card p-8 rounded-2xl border border-white/10 hover:border-white/30 transition-all group">
            <div className="w-12 h-12 rounded-xl bg-white/10 flex items-center justify-center text-white mb-6 group-hover:scale-110 transition-transform">
              <Shield className="w-6 h-6" />
            </div>
            <h3 className="text-xl font-medium mb-3">Self-Healing Execution</h3>
            <p className="text-neutral-400 text-sm leading-relaxed">
              Real-time telemetry and error boundary detection allow agents to patch syntax errors, adjust retries, and recover failed endpoints seamlessly.
            </p>
          </div>

          <div className="glass-card p-8 rounded-2xl border border-white/10 hover:border-white/30 transition-all group">
            <div className="w-12 h-12 rounded-xl bg-white/10 flex items-center justify-center text-white mb-6 group-hover:scale-110 transition-transform">
              <Zap className="w-6 h-6" />
            </div>
            <h3 className="text-xl font-medium mb-3">Instant Multi-Target Export</h3>
            <p className="text-neutral-400 text-sm leading-relaxed">
              Instantly compile your generated workflow into FastAPI SDKs, Docker compose microservices, GitHub repositories, or Model Context Protocol servers.
            </p>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/10 py-12 px-6 text-center text-sm text-neutral-500">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 rounded-lg bg-white text-black flex items-center justify-center font-bold text-sm">
              AW
            </div>
            <span className="text-neutral-400">© 2026 API Weaver. Vesper.ai Aesthetic Infrastructure.</span>
          </div>
          <div className="flex items-center gap-6 text-neutral-400">
            <a href="#" className="hover:text-white transition-colors">Documentation</a>
            <a href="#" className="hover:text-white transition-colors">API Reference</a>
            <a href="#" className="hover:text-white transition-colors">Security</a>
            <a href="#" className="hover:text-white transition-colors">Terms</a>
          </div>
        </div>
      </footer>
    </div>
  );
};
