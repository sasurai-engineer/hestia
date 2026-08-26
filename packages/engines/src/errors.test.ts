import { DomainError } from '@hestia/domain';
import { describe, expect, it } from 'vitest';
import { assertIntInRange, EngineError } from './errors.js';

describe('EngineError', () => {
  it('stays inside the domain taxonomy a boundary handler catches', () => {
    const error = new EngineError('x');
    expect(error).toBeInstanceOf(DomainError);
    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe('EngineError');
    expect(error.message).toBe('x');
  });
});

describe('assertIntInRange', () => {
  it('admits the boundaries and returns the value', () => {
    expect(assertIntInRange(1, 'n', 1, 10)).toBe(1);
    expect(assertIntInRange(10, 'n', 1, 10)).toBe(10);
  });
  it('rejects everything else by name', () => {
    expect(() => assertIntInRange(0, 'n', 1, 10)).toThrow(/n must be an integer in \[1, 10\]/);
    expect(() => assertIntInRange(11, 'n', 1, 10)).toThrow(EngineError);
    expect(() => assertIntInRange(2.5, 'n', 1, 10)).toThrow(EngineError);
    expect(() => assertIntInRange(Number.NaN, 'n', 1, 10)).toThrow(EngineError);
  });
});
