const KNOWN = new Set(['ok', 'skipped', 'failed']);

/** ok / skipped / failed as the livery's signal colors; flags stay gold. */
export function StatusPill({ status }: { status: string }) {
  const variant = KNOWN.has(status) ? status : 'flag';
  return <span className={`pill pill--${variant}`}>{status}</span>;
}
