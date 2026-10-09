import { describe, expect, it } from 'vitest';
import { asUuid } from './ids';

describe('asUuid', () => {
  it('passes UUIDs and rejects anything that could reshape an API path', () => {
    expect(asUuid('3f2b8c1e-9a4d-4c5e-8f6a-1b2c3d4e5f60')).toBe('3f2b8c1e-9a4d-4c5e-8f6a-1b2c3d4e5f60');
    for (const bad of ['../org/1/api-keys?', '..%2Forg', '', undefined, null, 'abc']) {
      expect(asUuid(bad)).toBeUndefined();
    }
  });
});
