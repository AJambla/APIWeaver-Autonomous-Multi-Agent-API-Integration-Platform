import React, { useState } from 'react';
import { ChevronDown, ChevronUp, Copy, Minus } from 'lucide-react';

export interface LiveThoughtItem {
  id: string;
  timestamp: string;
  agent: string;
  message: string;
  level: 'info' | 'success' | 'warn' | 'error';
  action?: string;
  step?: number;
  total_steps?: number;
}

interface TelemetryDockProps {
  liveThoughts: LiveThoughtItem[];
  autoScroll: boolean;
  setAutoScroll: (val: boolean) => void;
  onClear: () => void;
  terminalEndRef: React.RefObject<HTMLDivElement>;
  isLive: boolean;
}

export type DockMode = 'minimized' | 'normal' | 'expanded';

const formatEventTime = (iso: string | null): string => {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', { hour12: false });
};

const agentBadgeClass = (agent: string) => {
  const a = agent.toLowerCase();
  if (a.includes('doc')) return 'bg-purple-500/10 text-purple-300 border border-purple-500/20';
  if (a.includes('plan')) return 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/20';
  if (a.includes('gate') || a.includes('approval')) return 'bg-amber-500/10 text-amber-300 border border-amber-500/20';
  if (a.includes('code')) return 'bg-blue-500/10 text-blue-300 border border-blue-500/20';
  if (a.includes('test') || a.includes('sandbox')) return 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20';
  if (a.includes('repair')) return 'bg-rose-500/10 text-rose-300 border border-rose-500/20';
  if (a.includes('export')) return 'bg-indigo-500/10 text-indigo-300 border border-indigo-500/20';
  return 'bg-white/5 text-neutral-400 border border-white/10';
};

const thoughtColorClass = (level: string) => {
  if (level === 'success') return 'text-emerald-300';
  if (level === 'error') return 'text-rose-400';
  if (level === 'warn') return 'text-amber-300';
  return 'text-neutral-300';
};

export const TelemetryDock: React.FC<TelemetryDockProps> = ({
  liveThoughts,
  autoScroll,
  setAutoScroll,
  onClear,
  terminalEndRef,
  isLive,
}) => {
  const [dockMode, setDockMode] = useState<DockMode>(() => {
    const saved = localStorage.getItem('aw_dock_mode');
    return saved === 'minimized' || saved === 'normal' || saved === 'expanded' ? saved : 'normal';
  });
  const [copied, setCopied] = useState(false);

  const updateMode = (mode: DockMode) => {
    setDockMode(mode);
    localStorage.setItem('aw_dock_mode', mode);
  };

  const handleCopy = () => {
    const text = liveThoughts
      .map(t => `[${formatEventTime(t.timestamp)}] [${t.agent.toUpperCase()}] ${t.message}`)
      .join('\n');
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const heightClass =
    dockMode === 'minimized' ? 'h-9' : dockMode === 'expanded' ? 'h-80' : 'h-56';

  return (
    <div
      className={`border-t border-white/10 bg-[#07080b] flex flex-col shrink-0 transition-all duration-200 overflow-hidden ${heightClass}`}
    >
      {/* Dock Header Controls */}
      <div className="h-9 border-b border-white/5 bg-black/40 px-3.5 flex items-center justify-between text-xs shrink-0 font-mono">
        <div
          onClick={() => dockMode === 'minimized' && updateMode('normal')}
          className={`flex items-center gap-2 text-neutral-400 text-[11px] ${
            dockMode === 'minimized' ? 'cursor-pointer hover:text-white' : ''
          }`}
          title={dockMode === 'minimized' ? 'Click to restore stream' : undefined}
        >
          <span className="text-emerald-400 font-bold">&gt;_</span>
          <span className="font-medium text-neutral-200">LIVE LANGGRAPH & DOCKER SANDBOX STREAM</span>
          {isLive && (
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" title="Live stream connected" />
          )}
          {dockMode === 'minimized' && liveThoughts.length > 0 && (
            <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-neutral-400">
              {liveThoughts.length} event{liveThoughts.length === 1 ? '' : 's'}
            </span>
          )}
        </div>

        <div className="flex items-center gap-3 text-[11px] text-neutral-400">
          {dockMode === 'minimized' ? (
            <button
              onClick={() => updateMode('normal')}
              className="flex items-center gap-1 text-emerald-400 hover:text-emerald-300 transition-colors font-medium"
              title="Restore terminal"
            >
              <ChevronUp className="h-3 w-3" />
              <span>Restore</span>
            </button>
          ) : (
            <>
              <label className="flex items-center gap-1.5 cursor-pointer hover:text-neutral-200">
                <input
                  type="checkbox"
                  checked={autoScroll}
                  onChange={e => setAutoScroll(e.target.checked)}
                  className="h-3 w-3 rounded border-white/20 bg-white/5 text-emerald-500 focus:ring-0"
                />
                <span>Scroll</span>
              </label>
              <button
                onClick={onClear}
                className="hover:text-white transition-colors"
                title="Clear stream logs"
              >
                Clear
              </button>
              <button
                onClick={handleCopy}
                className="hover:text-white transition-colors"
                title="Copy logs to clipboard"
              >
                {copied ? 'Copied!' : 'Copy'}
              </button>
              {dockMode === 'expanded' ? (
                <button
                  onClick={() => updateMode('normal')}
                  className="flex items-center gap-0.5 hover:text-white transition-colors"
                  title="Collapse terminal to standard height"
                >
                  <span>Collapse</span>
                  <ChevronDown className="h-3 w-3" />
                </button>
              ) : (
                <button
                  onClick={() => updateMode('expanded')}
                  className="flex items-center gap-0.5 hover:text-white transition-colors"
                  title="Expand terminal height"
                >
                  <span>Expand</span>
                  <ChevronUp className="h-3 w-3" />
                </button>
              )}
              <button
                onClick={() => updateMode('minimized')}
                className="flex items-center gap-0.5 hover:text-white transition-colors ml-1 pl-1 border-l border-white/10"
                title="Minimize stream dock"
              >
                <Minus className="h-3 w-3" />
                <span>Minimize</span>
              </button>
            </>
          )}
        </div>
      </div>

      {/* Terminal Stream Output */}
      {dockMode !== 'minimized' && (
        <div className="flex-1 p-3 overflow-y-auto font-mono text-[11px] text-neutral-300 space-y-1.5 select-text">
          {liveThoughts.length === 0 ? (
            <div className="text-neutral-600 italic py-4 text-center">
              Waiting for pipeline execution or telemetry events...
            </div>
          ) : (
            liveThoughts.map(t => (
              <div key={t.id} className="flex items-start gap-2 leading-relaxed">
                <span className="text-neutral-600 shrink-0">[{formatEventTime(t.timestamp)}]</span>
                <span
                  className={`px-1.5 py-0.2 rounded text-[10px] uppercase tracking-wider shrink-0 font-bold ${agentBadgeClass(
                    t.agent
                  )}`}
                >
                  {t.agent}
                </span>
                <span className={`min-w-0 break-words flex-1 ${thoughtColorClass(t.level)}`}>
                  {t.message}
                </span>
              </div>
            ))
          )}
          <div ref={terminalEndRef} />
        </div>
      )}
    </div>
  );
};
