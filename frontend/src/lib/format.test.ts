import { describe, expect, it } from 'vitest';
import {
  duration,
  formatNumber,
  formatPercent,
  formatUsd,
  initials,
  relativeTime,
  shortId,
  specFormat,
  specVersion,
  validationState,
} from './format';

describe('format utilities', () => {
  it('shortId truncates to 8 chars', () => {
    expect(shortId('1234567890abcdef')).toBe('12345678');
    expect(shortId('abc')).toBe('abc');
  });

  it('relativeTime handles null/undefined and recent times', () => {
    expect(relativeTime(null)).toBe('—');
    expect(relativeTime(undefined)).toBe('—');
    const nowIso = new Date().toISOString();
    expect(relativeTime(nowIso)).toBe('just now');
  });

  it('duration calculates time difference', () => {
    expect(duration(null, null)).toBe('—');
    const start = new Date(Date.now() - 30000).toISOString();
    expect(duration(start, new Date().toISOString())).toBe('<1 min');
  });

  it('formatNumber formats numbers in compact notation', () => {
    expect(formatNumber(1500)).toBe('1.5K');
    expect(formatNumber(20)).toBe('20');
  });

  it('formatUsd formats dollar amounts', () => {
    expect(formatUsd(42.5)).toBe('$42.5');
    expect(formatUsd(100)).toBe('$100');
  });

  it('formatPercent formats decimal ratios', () => {
    expect(formatPercent(null)).toBe('—');
    expect(formatPercent(0.856)).toBe('86%');
    expect(formatPercent(1)).toBe('100%');
  });

  it('initials derives letters from names or emails', () => {
    expect(initials('John Doe')).toBe('JD');
    expect(initials('alice@example.com')).toBe('AE');
    expect(initials(undefined)).toBe('?');
  });

  it('specFormat detects OpenAPI, Swagger, or Normalized', () => {
    expect(specFormat(null)).toBe('—');
    expect(specFormat({ openapi: '3.0.0' })).toBe('OpenAPI 3.0.0');
    expect(specFormat({ swagger: '2.0' })).toBe('Swagger 2.0');
    expect(specFormat({})).toBe('Normalized');
  });

  it('specVersion retrieves version string', () => {
    expect(specVersion(null)).toBe('—');
    expect(specVersion({ info: { version: '1.2.3' } })).toBe('1.2.3');
  });

  it('validationState maps confidence score to badges', () => {
    expect(validationState(null)).toEqual({ label: 'No spec', status: 'draft' });
    expect(validationState(0.95)).toEqual({ label: 'Valid', status: 'completed' });
    expect(validationState(0.6)).toEqual({ label: 'Warnings', status: 'paused_for_approval' });
    expect(validationState(0.3)).toEqual({ label: 'Low confidence', status: 'failed' });
  });
});
