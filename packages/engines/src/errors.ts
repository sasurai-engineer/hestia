import { DomainError } from '@hestia/domain';

/**
 * A violation of an engine's contract: an input outside its domain, or an
 * internal invariant that did not hold.
 *
 * Extends {@link DomainError} so the package keeps the taxonomy promise the
 * domain layer makes: a caller catching DomainError at a service boundary
 * catches every failure these engines can produce.
 */
export class EngineError extends DomainError {
  override readonly name = 'EngineError';
}

/** Guard for integer inputs with an inclusive range. */
export const assertIntInRange = (value: number, name: string, lo: number, hi: number): number => {
  if (!Number.isInteger(value) || value < lo || value > hi) {
    throw new EngineError(
      `${name} must be an integer in [${lo}, ${hi}], received ${String(value)}`,
    );
  }
  return value;
};
