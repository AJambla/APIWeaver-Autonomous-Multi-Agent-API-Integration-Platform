import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { apiFetch } from '../lib/api';
import { Project, WorkflowEvent } from '../lib/types';
import {
  ArrowLeft, Upload, GitBranch, Terminal as TerminalIcon, PlayCircle,
  Download, Settings as SettingsIcon, CheckCircle2, Cpu
} from 'lucide-react';
import Editor from '@monaco-editor/react';

export const ProjectWorkspace: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [activeTab, setActiveTab] = useState<'upload' | 'plan' | 'build' | 'test' | 'export' | 'logs' | 'settings'>('upload');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [specContent, setSpecContent] = useState('openapi: 3.0.0\ninfo:\n  title: Sample API\n  version: 1.0.0\npaths: {}');
  const [uploading, setUploading] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState(false);

  const [dagPlan, setDagPlan] = useState('1. Parse OpenAPI schema & extract models\n2. Generate FastAPI routers & Pydantic validation\n3. Initialize Celery background tasks & storage service\n4. Execute self-healing test suite');
  const [planApproved, setPlanApproved] = useState(false);

  const [events, setEvents] = useState<WorkflowEvent[]>([
    { id: '1', timestamp: new Date().toLocaleTimeString(), level: 'info', message: 'Initialized agent execution environment.', agent: 'System' },
    { id: '2', timestamp: new Date().toLocaleTimeString(), level: 'success', message: 'Parsed OpenAPI 3.0 specification successfully.', agent: 'ParserAgent' },
  ]);
  const [building, setBuilding] = useState(false);

  const [testResults] = useState([
    { endpoint: '/api/v1/health', method: 'GET', status: 200, latency: '12ms', passed: true },
    { endpoint: '/api/v1/projects', method: 'POST', status: 201, latency: '45ms', passed: true },
  ]);

  useEffect(() => {
    if (!id) {
      setError('A project ID is required.');
      setLoading(false);
      return;
    }

    apiFetch<Project>(`/projects/${id}`)
      .then(setProject)
      .catch(error => setError(error instanceof Error ? error.message : 'Unable to load the project.'))
      .finally(() => setLoading(false));
  }, [id]);

  const handleUploadSpec = async () => {
    if (!id) return;

    setUploading(true);
    setUploadSuccess(false);
    setError('');
    const formData = new FormData();
    formData.append('file', new File([specContent], 'openapi.yaml', { type: 'application/yaml' }));
    formData.append('format_hint', 'openapi');

    try {
      await apiFetch(`/projects/${id}/upload`, {
        method: 'POST',
        body: formData,
      });
      setUploadSuccess(true);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Unable to upload the specification.');
    } finally {
      setUploading(false);
    }
  };

  const handleStartBuild = () => {
    setBuilding(true);
    const newEvent: WorkflowEvent = {
      id: String(Date.now()),
      timestamp: new Date().toLocaleTimeString(),
      level: 'success',
      message: 'Workflow execution started via Celery cluster worker.',
      agent: 'Orchestrator',
    };
    setEvents(prev => [newEvent, ...prev]);
    setTimeout(() => {
      setBuilding(false);
      setEvents(prev => [
        {
          id: String(Date.now() + 1),
          timestamp: new Date().toLocaleTimeString(),
          level: 'success',
          message: 'All agent tasks completed successfully with 0 errors.',
          agent: 'Orchestrator',
        },
        ...prev
      ]);
    }, 2000);
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-black text-white flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 border-b-2 border-white" />
      </div>
    );
  }

  if (!project) {
    return (
      <div className="min-h-screen bg-black text-white flex flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-sm text-red-300">{error || 'Unable to load the project.'}</p>
        <Link to="/dashboard" className="rounded-xl border border-white/15 px-4 py-2 text-sm text-white hover:bg-white/10">
          Return to projects
        </Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-black text-white flex flex-col selection:bg-white selection:text-black">
      {/* Header */}
      <header className="border-b border-white/10 bg-black/60 backdrop-blur-xl sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-6 h-20 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link to="/dashboard" className="p-2 rounded-xl glass-pill hover:bg-white/10 text-neutral-400 hover:text-white transition-colors">
              <ArrowLeft className="w-4 h-4" />
            </Link>
            <div>
              <div className="text-sm font-semibold tracking-tight">{project?.name || 'Project Workspace'}</div>
              <div className="text-xs text-neutral-400">ID: {id}</div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <span className="px-3 py-1 rounded-full bg-white/10 text-xs font-medium text-neutral-200 capitalize">
              {project?.status || 'Active'}
            </span>
          </div>
        </div>
      </header>

      {/* Tabs Navigation */}
      <div className="border-b border-white/10 bg-neutral-950/40 backdrop-blur-md sticky top-20 z-30">
        <div className="max-w-7xl mx-auto px-6 flex items-center gap-2 overflow-x-auto py-3 no-scrollbar">
          {[
            { id: 'upload', label: '1. Upload Spec', icon: Upload },
            { id: 'plan', label: '2. Topological Plan', icon: GitBranch },
            { id: 'build', label: '3. Build & Agents', icon: Cpu },
            { id: 'test', label: '4. Test Suite', icon: PlayCircle },
            { id: 'export', label: '5. Export Wizard', icon: Download },
            { id: 'logs', label: '6. Event Logs', icon: TerminalIcon },
            { id: 'settings', label: '7. Settings', icon: SettingsIcon },
          ].map(tab => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as typeof activeTab)}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-full text-xs font-medium transition-all shrink-0 ${
                  isActive 
                    ? 'bg-white text-black shadow-[0_0_20px_rgba(255,255,255,0.25)]' 
                    : 'glass-pill text-neutral-300 hover:text-white hover:bg-white/10'
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Main Tab Content */}
      <main className="max-w-7xl mx-auto px-6 py-12 flex-1 w-full">
        {activeTab === 'upload' && (
          <div className="max-w-4xl mx-auto glass-card p-8 rounded-3xl border border-white/10 appear">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-2xl font-normal tracking-tight mb-1">Document & Specification Upload</h2>
                <p className="text-neutral-400 text-xs">Drop your OpenAPI, Swagger, Postman collection, or Markdown specs below.</p>
              </div>
              <button
                onClick={handleUploadSpec}
                disabled={uploading}
                className="px-6 py-3 rounded-full bg-white text-black text-sm font-medium hover:bg-neutral-200 transition-all shadow-[0_0_20px_rgba(255,255,255,0.2)] disabled:opacity-50"
              >
                {uploading ? 'Parsing Spec...' : 'Upload & Parse'}
              </button>
            </div>

            {uploadSuccess && (
              <div className="mb-6 p-4 rounded-xl bg-emerald-950/40 border border-emerald-500/30 text-emerald-300 text-xs flex items-center gap-3">
                <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
                <span>Specification parsed successfully and ingested into agent memory vector store.</span>
              </div>
            )}

            {error && (
              <div role="alert" className="mb-6 rounded-xl border border-red-500/30 bg-red-950/40 p-4 text-xs text-red-300">
                {error}
              </div>
            )}

            <div className="h-[450px] rounded-2xl overflow-hidden border border-white/15">
              <Editor
                height="100%"
                defaultLanguage="yaml"
                theme="vs-dark"
                value={specContent}
                onChange={val => setSpecContent(val || '')}
                options={{
                  minimap: { enabled: false },
                  fontSize: 13,
                }}
              />
            </div>
          </div>
        )}

        {activeTab === 'plan' && (
          <div className="max-w-4xl mx-auto glass-card p-8 rounded-3xl border border-white/10 appear">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-2xl font-normal tracking-tight mb-1">Topological DAG Execution Plan</h2>
                <p className="text-neutral-400 text-xs">Review generated dependency graph and approve execution schedule.</p>
              </div>
              <button
                onClick={() => setPlanApproved(true)}
                className={`px-6 py-3 rounded-full text-sm font-medium transition-all ${
                  planApproved 
                    ? 'bg-emerald-500 text-black shadow-[0_0_20px_rgba(16,185,129,0.3)]' 
                    : 'bg-white text-black hover:bg-neutral-200 shadow-[0_0_20px_rgba(255,255,255,0.2)]'
                }`}
              >
                {planApproved ? 'Plan Approved ✓' : 'Approve Execution Plan'}
              </button>
            </div>

            {planApproved && (
              <div className="mb-6 p-4 rounded-xl bg-emerald-950/40 border border-emerald-500/30 text-emerald-300 text-xs flex items-center gap-3">
                <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
                <span>Execution plan locked. Celery orchestrator ready to dispatch workers.</span>
              </div>
            )}

            <div className="h-[350px] rounded-2xl overflow-hidden border border-white/15 mb-6">
              <Editor
                height="100%"
                defaultLanguage="markdown"
                theme="vs-dark"
                value={dagPlan}
                onChange={val => setDagPlan(val || '')}
                options={{
                  minimap: { enabled: false },
                  fontSize: 13,
                }}
              />
            </div>
          </div>
        )}

        {activeTab === 'build' && (
          <div className="max-w-4xl mx-auto glass-card p-8 rounded-3xl border border-white/10 appear">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-2xl font-normal tracking-tight mb-1">Agent Build & Execution Stepper</h2>
                <p className="text-neutral-400 text-xs">Monitor autonomous code generation and model compilation.</p>
              </div>
              <button
                onClick={handleStartBuild}
                disabled={building}
                className="px-6 py-3 rounded-full bg-white text-black text-sm font-medium hover:bg-neutral-200 transition-all shadow-[0_0_20px_rgba(255,255,255,0.2)] disabled:opacity-50 flex items-center gap-2"
              >
                <PlayCircle className="w-4 h-4" />
                <span>{building ? 'Executing Agents...' : 'Run Build Pipeline'}</span>
              </button>
            </div>

            <div className="space-y-4">
              <div className="glass-card p-6 rounded-2xl border border-white/10 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center text-white">
                    <Cpu className="w-5 h-5" />
                  </div>
                  <div>
                    <h3 className="text-sm font-medium">FastAPI Pydantic Generator Agent</h3>
                    <p className="text-xs text-neutral-400">Generates type-safe routers, models, and validation schemas.</p>
                  </div>
                </div>
                <span className="px-3 py-1 rounded-full bg-emerald-950/60 border border-emerald-500/30 text-emerald-400 text-xs font-medium">
                  Completed
                </span>
              </div>

              <div className="glass-card p-6 rounded-2xl border border-white/10 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center text-white">
                    <TerminalIcon className="w-5 h-5" />
                  </div>
                  <div>
                    <h3 className="text-sm font-medium">Celery Worker & Storage Service Agent</h3>
                    <p className="text-xs text-neutral-400">Configures asynchronous task queues and SQLite/PostgreSQL storage.</p>
                  </div>
                </div>
                <span className="px-3 py-1 rounded-full bg-blue-950/60 border border-blue-500/30 text-blue-400 text-xs font-medium">
                  Ready
                </span>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'test' && (
          <div className="max-w-4xl mx-auto glass-card p-8 rounded-3xl border border-white/10 appear">
            <h2 className="text-2xl font-normal tracking-tight mb-1">Test Suite & Self-Healing Telemetry</h2>
            <p className="text-neutral-400 text-xs mb-6">Verify endpoint responses, status codes, and latency metrics.</p>

            <div className="space-y-4">
              {testResults.map((test, index) => (
                <div key={index} className="glass-card p-5 rounded-2xl border border-white/10 flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <span className="px-2.5 py-1 rounded-lg bg-white/10 text-xs font-mono font-bold text-neutral-200">
                      {test.method}
                    </span>
                    <span className="text-sm font-mono text-neutral-200">{test.endpoint}</span>
                  </div>
                  <div className="flex items-center gap-6">
                    <span className="text-xs text-neutral-400 font-mono">{test.latency}</span>
                    <span className="px-3 py-1 rounded-full bg-emerald-950/60 border border-emerald-500/30 text-emerald-400 text-xs font-medium">
                      {test.status} OK
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeTab === 'export' && (
          <div className="max-w-4xl mx-auto glass-card p-8 rounded-3xl border border-white/10 appear">
            <h2 className="text-2xl font-normal tracking-tight mb-1">Infrastructure Export Wizard</h2>
            <p className="text-neutral-400 text-xs mb-8">Export your generated workflows to production-ready targets.</p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="glass-card p-6 rounded-2xl border border-white/10 hover:border-white/30 transition-all cursor-pointer group">
                <h3 className="text-lg font-medium mb-2 group-hover:text-white">Docker Compose Bundle</h3>
                <p className="text-neutral-400 text-xs mb-4">Complete containerized deployment with FastAPI, Celery worker, Redis, and frontend Nginx.</p>
                <button className="px-4 py-2 rounded-xl bg-white/10 text-xs font-medium hover:bg-white text-white hover:text-black transition-colors flex items-center gap-2">
                  <Download className="w-3.5 h-3.5" />
                  <span>Download ZIP</span>
                </button>
              </div>

              <div className="glass-card p-6 rounded-2xl border border-white/10 hover:border-white/30 transition-all cursor-pointer group">
                <h3 className="text-lg font-medium mb-2 group-hover:text-white">FastAPI Python SDK</h3>
                <p className="text-neutral-400 text-xs mb-4">Standalone Python client package with full Pydantic type hints and async support.</p>
                <button className="px-4 py-2 rounded-xl bg-white/10 text-xs font-medium hover:bg-white text-white hover:text-black transition-colors flex items-center gap-2">
                  <Download className="w-3.5 h-3.5" />
                  <span>Download SDK</span>
                </button>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'logs' && (
          <div className="max-w-4xl mx-auto glass-card p-8 rounded-3xl border border-white/10 appear">
            <h2 className="text-2xl font-normal tracking-tight mb-1">Real-Time Event Stream</h2>
            <p className="text-neutral-400 text-xs mb-6">Structured audit logs and agent telemetry events.</p>

            <div className="bg-neutral-950 border border-white/15 rounded-2xl p-6 font-mono text-xs space-y-3 h-[400px] overflow-y-auto">
              {events.map(ev => (
                <div key={ev.id} className="flex items-start gap-4 pb-3 border-b border-white/5">
                  <span className="text-neutral-500 shrink-0">[{ev.timestamp}]</span>
                  <span className="px-2 py-0.5 rounded bg-white/10 text-neutral-300 uppercase text-[10px] shrink-0">
                    {ev.agent || 'Agent'}
                  </span>
                  <span className="text-neutral-200">{ev.message}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeTab === 'settings' && (
          <div className="max-w-4xl mx-auto glass-card p-8 rounded-3xl border border-white/10 appear">
            <h2 className="text-2xl font-normal tracking-tight mb-1">Project Settings & Parameters</h2>
            <p className="text-neutral-400 text-xs mb-6">Configure retry policies, rate limits, and security tokens.</p>

            <div className="space-y-6">
              <div>
                <label className="block text-xs font-medium text-neutral-300 mb-2">Project Name</label>
                <input
                  type="text"
                  defaultValue={project?.name}
                  className="w-full bg-neutral-900 border border-white/15 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:border-white transition-colors"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-neutral-300 mb-2">Agent Execution Retry Limit</label>
                <input
                  type="number"
                  defaultValue={3}
                  className="w-full bg-neutral-900 border border-white/15 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:border-white transition-colors"
                />
              </div>

              <button className="px-6 py-3 rounded-full bg-white text-black text-sm font-medium hover:bg-neutral-200 transition-all shadow-[0_0_20px_rgba(255,255,255,0.2)]">
                Save Changes
              </button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
};
