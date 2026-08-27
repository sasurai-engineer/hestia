/**
 * A component's remaining life as a bar of ink. With a label it is a real
 * meter to assistive tech; without one it is decoration beside a figure
 * that already says the number.
 */
type LifeBarProps = {
  /** 0 (spent) to 1 (full); values outside are clamped, never trusted. */
  fraction: number;
  spent?: boolean;
  label?: string;
};

export function LifeBar({ fraction, spent = false, label }: LifeBarProps) {
  const clamped = Math.min(1, Math.max(0, fraction));
  const fill = (
    <span
      className={spent ? 'lifebar__fill lifebar__fill--spent' : 'lifebar__fill'}
      style={{ width: `${(clamped * 100).toFixed(0)}%` }}
    />
  );
  return label === undefined ? (
    <div className="lifebar" aria-hidden="true">
      {fill}
    </div>
  ) : (
    // A native <meter> cannot be styled as the livery's ink bar; the ARIA
    // meter contract is honored in full (rule off for this file alone in
    // the package biome.json).
    <div
      className="lifebar"
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={1}
      aria-valuenow={clamped}
    >
      {fill}
    </div>
  );
}
