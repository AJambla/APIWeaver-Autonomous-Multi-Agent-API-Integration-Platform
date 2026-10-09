import { describe, expect, it } from 'vitest';
import { isWorkflowTerminal, MAX_RETAINED_EVENTS } from './use-workflow-events';

describe('use-workflow-events utilities', () => {
  it('caps retained events at 500 to prevent unbounded memory growth', () => {
    expect(MAX_RETAINED_EVENTS).toBe(500);
  });

  it('identifies terminal lifecycle events', () => {
    expect(isWorkflowTerminal('workflow.completed', { status: 'completed' })).toBe(true);
    expect(isWorkflowTerminal('workflow.failed', { status: 'failed' })).toBe(true);
    expect(isWorkflowTerminal('workflow.cancelled', { status: 'cancelled' })).toBe(true);
  });

  it('recognizes paused_for_approval hold as non-terminal', () => {
    expect(isWorkflowTerminal('workflow.completed', { status: 'paused_for_approval' })).toBe(false);
  });

  it('marks non-terminal event types as false', () => {
    expect(isWorkflowTerminal('workflow.started', {})).toBe(false);
    expect(isWorkflowTerminal('stage.completed', {})).toBe(false);
    expect(isWorkflowTerminal('heartbeat', {})).toBe(false);
  });
});
