import { describe, expect, it } from 'vitest';
import { DomainError, MoneyError, RateError } from './errors.js';

describe('domain errors', () => {
  it('carry their own names so logs and reports identify the failure kind', () => {
    expect(new DomainError('x').name).toBe('DomainError');
    expect(new MoneyError('x').name).toBe('MoneyError');
    expect(new RateError('x').name).toBe('RateError');
  });

  it('preserve the message', () => {
    expect(new MoneyError('currency mismatch').message).toBe('currency mismatch');
  });

  it('are catchable as DomainError and as Error', () => {
    for (const error of [new MoneyError('x'), new RateError('x')]) {
      expect(error).toBeInstanceOf(DomainError);
      expect(error).toBeInstanceOf(Error);
    }
    expect(new DomainError('x')).not.toBeInstanceOf(MoneyError);
  });
});
