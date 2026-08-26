/** Base class for domain violations that indicate a programming error. */
export class DomainError extends Error {
  override readonly name: string = 'DomainError';
}

/** Raised when a monetary operation is not well defined. */
export class MoneyError extends DomainError {
  override readonly name = 'MoneyError';
}

/** Raised when a rate is not well defined. */
export class RateError extends DomainError {
  override readonly name = 'RateError';
}
