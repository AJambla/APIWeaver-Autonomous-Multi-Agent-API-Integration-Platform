import React, { useState, useEffect, useRef } from 'react';
import {
  Check,
  CheckCircle2,
  Copy,
  ExternalLink,
  FileCode2,
  Loader2,
  Send,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Terminal,
  X,
  Zap,
} from 'lucide-react';
import { apiFetch } from '../lib/api';

export interface WeaverWorkspaceContext {
  currentStage: string;
  selectedFile?: string | null;
  selectedEndpoint?: string | null;
  selectedTool?: string | null;
  activeCodeSnippet?: string | null;
  errorMessage?: string | null;
}

export interface WeaverChangeProposal {
  file_path: string;
  description: string;
  original_snippet?: string | null;
  replacement_snippet?: string | null;
  full_content?: string | null;
  diff?: string | null;
}

export interface WeaverMessage {
  id: string;
  sender: 'user' | 'weaver';
  text: string;
  intent?: string;
  safetyReasoning?: string[] | null;
  proposal?: WeaverChangeProposal | null;
  timestamp: string;
}

interface WeaverAgentDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  projectId: string;
  projectName: string;
  context: WeaverWorkspaceContext;
  initialQuery?: string | null;
  onApplyCode?: (filePath: string, newContent: string) => void;
}

export const WeaverAgentDrawer: React.FC<WeaverAgentDrawerProps> = ({
  isOpen,
  onClose,
  projectId,
  projectName,
  context,
  initialQuery,
  onApplyCode,
}) => {
  const [messages, setMessages] = useState<WeaverMessage[]>([
    {
      id: 'welcome',
      sender: 'weaver',
      text: `Hello! I am **Weaver**, your AI Project Engineering Agent.\n\nI am scoped directly to **${projectName}**. I can explain code, investigate verification errors, trace API dependencies, and propose safe code modifications with full AST verification.`,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [appliedProposalId, setAppliedProposalId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const initialTriggeredRef = useRef<string | null>(null);

  // Auto-scroll on new messages
  useEffect(() => {
    if (isOpen) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isOpen]);

  // Handle initial auto-query (e.g. from "Ask Agent About This")
  useEffect(() => {
    if (isOpen && initialQuery && initialTriggeredRef.current !== initialQuery) {
      initialTriggeredRef.current = initialQuery;
      handleSendMessage(initialQuery);
    }
  }, [isOpen, initialQuery]);

  const handleSendMessage = async (queryText?: string) => {
    const textToSend = queryText || input.trim();
    if (!textToSend || loading) return;

    if (!queryText) setInput('');

    const userMsg: WeaverMessage = {
      id: `user-${Date.now()}`,
      sender: 'user',
      text: textToSend,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages(prev => [...prev, userMsg]);
    setLoading(true);

    try {
      const res = await apiFetch<{
        reply: string;
        intent: string;
        context_used: Record<string, unknown>;
        safety_reasoning?: string[] | null;
        proposal?: WeaverChangeProposal | null;
      }>(`/projects/${projectId}/weaver/chat`, {
        method: 'POST',
        body: JSON.stringify({
          message: textToSend,
          workspace_context: {
            current_stage: context.currentStage,
            selected_file: context.selectedFile,
            selected_endpoint: context.selectedEndpoint,
            selected_tool: context.selectedTool,
            active_code_snippet: context.activeCodeSnippet,
            error_message: context.errorMessage,
          },
          conversation_history: messages.slice(-6).map(m => ({
            role: m.sender === 'user' ? 'user' : 'assistant',
            content: m.text,
          })),
        }),
      });

      const weaverMsg: WeaverMessage = {
        id: `weaver-${Date.now()}`,
        sender: 'weaver',
        text: res.reply,
        intent: res.intent,
        safetyReasoning: res.safety_reasoning,
        proposal: res.proposal,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };

      setMessages(prev => [...prev, weaverMsg]);
    } catch (err: any) {
      setMessages(prev => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          sender: 'weaver',
          text: `⚠️ **Agent Communication Issue**: ${err?.message || 'Could not reach Weaver Agent'}. Please verify backend status.`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleApplyProposal = async (msgId: string, proposal: WeaverChangeProposal) => {
    try {
      const targetContent = proposal.replacement_snippet || proposal.full_content || '';
      const res = await apiFetch<{
        success: boolean;
        file_path: string;
        verification_status: string;
        details: string;
      }>(`/projects/${projectId}/weaver/apply`, {
        method: 'POST',
        body: JSON.stringify({
          file_path: proposal.file_path,
          content: targetContent,
        }),
      });

      if (res.success) {
        setAppliedProposalId(msgId);
        if (onApplyCode) {
          onApplyCode(proposal.file_path, targetContent);
        }
      }
    } catch (err: any) {
      console.error('Failed to apply proposal', err);
    }
  };

  if (!isOpen) return null;

  // Breadcrumbs text for context
  const contextBreadcrumbs = [
    projectName,
    context.currentStage,
    context.selectedFile,
    context.selectedTool || context.selectedEndpoint,
  ]
    .filter(Boolean)
    .join(' → ');

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 transition-opacity"
      />

      {/* Slide-over Drawer */}
      <div className="fixed inset-y-0 right-0 w-full sm:w-[480px] bg-[#0c0d12] border-l border-white/10 shadow-2xl z-50 flex flex-col animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="p-4 border-b border-white/10 flex items-center justify-between shrink-0 bg-[#0c0d12]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-purple-500/10 border border-purple-500/30 flex items-center justify-center text-purple-400">
              <Sparkles className="h-4 w-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold text-white tracking-tight">Weaver Agent</h2>
                <span className="rounded-full bg-purple-500/20 px-2 py-0.2 text-[9px] font-mono text-purple-300 border border-purple-500/30">
                  ENGINEER
                </span>
              </div>
              <p className="text-[11px] text-neutral-400">Project-aware development assistant</p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-neutral-400 hover:text-white hover:bg-white/10 transition-colors"
            aria-label="Close Weaver"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Current Context Banner */}
        <div className="p-3 border-b border-white/5 bg-[#090a0f] shrink-0">
          <div className="rounded-xl border border-purple-500/20 bg-purple-950/10 p-2.5 space-y-1">
            <span className="text-[9px] font-mono tracking-wider uppercase text-purple-300 font-semibold block">
              CURRENT CONTEXT
            </span>
            <div className="font-mono text-xs text-neutral-200 truncate" title={contextBreadcrumbs}>
              {contextBreadcrumbs}
            </div>
          </div>
        </div>

        {/* Chat Transcript Area */}
        <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
          {messages.map(msg => (
            <div key={msg.id} className="space-y-1.5">
              <div className="flex items-center justify-between text-[10px] font-mono text-neutral-500">
                <span className={msg.sender === 'weaver' ? 'text-purple-400 font-semibold' : 'text-neutral-400 font-semibold'}>
                  {msg.sender === 'weaver' ? 'WEAVER' : 'YOU'}
                </span>
                <span>{msg.timestamp}</span>
              </div>

              {msg.sender === 'user' ? (
                <div className="text-sm text-neutral-200 font-medium pl-1">
                  {msg.text}
                </div>
              ) : (
                <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4 text-xs text-neutral-200 space-y-3">
                  {/* Markdown Reply */}
                  <div className="leading-relaxed whitespace-pre-wrap font-sans text-neutral-300 space-y-2">
                    {msg.text}
                  </div>

                  {/* Safety Reasoning Card (if present) */}
                  {msg.safetyReasoning && msg.safetyReasoning.length > 0 && (
                    <div className="rounded-xl border border-emerald-500/30 bg-[#07130f] p-3 space-y-2">
                      <div className="text-xs font-semibold text-emerald-400 flex items-center gap-1.5">
                        <ShieldCheck className="h-3.5 w-3.5" />
                        <span>Safety reasoning</span>
                      </div>
                      <div className="space-y-1 text-[11px] text-emerald-300 font-mono">
                        {msg.safetyReasoning.map((item, idx) => (
                          <div key={idx} className="flex items-center gap-1.5">
                            <span className="text-emerald-400">✓</span>
                            <span>{item.replace(/^[✓\s]+/, '')}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Proposed Change Card (if present) */}
                  {msg.proposal && (
                    <div className="rounded-xl border border-purple-500/30 bg-[#120d18] p-3.5 space-y-2.5">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-xs font-semibold text-white flex items-center gap-1.5">
                          <FileCode2 className="h-3.5 w-3.5 text-purple-400" />
                          <span>{msg.proposal.file_path}</span>
                        </span>
                        <span className="rounded bg-purple-500/20 text-purple-300 border border-purple-500/30 text-[9px] font-mono px-1.5 py-0.2">
                          CHANGE PROPOSAL
                        </span>
                      </div>

                      <p className="text-[11px] text-neutral-300">{msg.proposal.description}</p>

                      {/* Diff block */}
                      {msg.proposal.diff && (
                        <div className="rounded-lg bg-black/60 p-2.5 font-mono text-[10px] overflow-x-auto max-h-40 border border-white/5 space-y-0.5">
                          {msg.proposal.diff.split('\n').map((line, lidx) => (
                            <div
                              key={lidx}
                              className={
                                line.startsWith('+')
                                  ? 'text-emerald-400 bg-emerald-950/20'
                                  : line.startsWith('-')
                                  ? 'text-rose-400 bg-rose-950/20'
                                  : line.startsWith('@')
                                  ? 'text-sky-400'
                                  : 'text-neutral-400'
                              }
                            >
                              {line}
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Apply actions */}
                      <div className="flex items-center gap-2 pt-1">
                        {appliedProposalId === msg.id ? (
                          <div className="flex items-center gap-1.5 text-xs text-emerald-400 font-medium">
                            <Check className="h-4 w-4" />
                            <span>Applied & AST Verified</span>
                          </div>
                        ) : (
                          <button
                            type="button"
                            onClick={() => handleApplyProposal(msg.id, msg.proposal!)}
                            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-xs font-medium transition-colors"
                          >
                            <Zap className="h-3.5 w-3.5" />
                            <span>Apply Change</span>
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4 flex items-center gap-2 text-xs text-neutral-400 animate-pulse">
              <Loader2 className="h-4 w-4 animate-spin text-purple-400" />
              <span>Weaver is analyzing project code & workspace context…</span>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Quick Prompts Suggestions (shown when few messages) */}
        {messages.length <= 2 && (
          <div className="px-4 py-2 border-t border-white/5 bg-[#090a0f] flex flex-wrap gap-1.5">
            {[
              'Why is post_pet classified as state-changing?',
              'Add retry handling to tools.py',
              'What depends on this endpoint?',
              'Explain the project architecture',
            ].map(prompt => (
              <button
                key={prompt}
                type="button"
                onClick={() => handleSendMessage(prompt)}
                className="rounded-full border border-white/10 bg-white/[0.03] hover:bg-white/[0.07] px-2.5 py-1 text-[11px] text-neutral-300 transition-colors text-left truncate max-w-full"
              >
                {prompt}
              </button>
            ))}
          </div>
        )}

        {/* Input Area */}
        <div className="p-4 border-t border-white/10 bg-[#090a0f] space-y-2 shrink-0">
          <form
            onSubmit={e => {
              e.preventDefault();
              handleSendMessage();
            }}
            className="space-y-2"
          >
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSendMessage();
                }
              }}
              placeholder="Tell Weaver what you want to change..."
              rows={3}
              className="w-full rounded-xl border border-white/10 bg-white/[0.02] p-3 text-xs text-white placeholder-neutral-500 focus:outline-none focus:border-purple-500/50 resize-none font-sans"
            />

            <div className="flex items-center justify-between">
              <span className="text-[10px] text-neutral-500">
                Context-aware · Can inspect files · Can propose changes
              </span>

              <button
                type="submit"
                disabled={!input.trim() || loading}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-xs font-medium transition-colors disabled:opacity-40 disabled:pointer-events-none"
              >
                <span>Send</span>
                <Send className="h-3 w-3" />
              </button>
            </div>
          </form>
        </div>
      </div>
    </>
  );
};
