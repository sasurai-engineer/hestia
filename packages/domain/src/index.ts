// The package's public surface. Internals — the configured Decimal clone, the
// numeric screening helpers — are deliberately not re-exported: handing out
// FinancialDecimal would let a consumer forge a Rate that never met its guard.
export * from './errors.js';
export * from './money.js';
export * from './rate.js';
