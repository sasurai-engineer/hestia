/**
 * Paper waiting for ink. Decorative by definition — hidden from assistive
 * tech, which should meet the loaded page, not the loading one.
 */
export function Skeleton({ lines = 1 }: { lines?: number }) {
  const count = Math.max(1, Math.trunc(lines));
  return (
    <div aria-hidden="true">
      {Array.from({ length: count }, (_, line) => `skeleton-line-${line}`).map((key) => (
        <span key={key} className="skeleton" />
      ))}
    </div>
  );
}
