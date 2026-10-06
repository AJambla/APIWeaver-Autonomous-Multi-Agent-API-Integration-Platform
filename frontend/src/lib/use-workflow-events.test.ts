import { describe, expect, it } from 'vitest';
import { isWorkflowTerminal } from './use-workflow-events';

describe('use-workflow-events utilities', () => {
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
