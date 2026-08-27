/**
 * Class-name composition. False and undefined vanish so callers can write
 * `cx('card', flush && 'card--flush', className)` without ternaries.
 */
export function cx(...parts: readonly (string | false | undefined)[]): string {
  return parts.filter((part): part is string => typeof part === 'string' && part !== '').join(' ');
}
