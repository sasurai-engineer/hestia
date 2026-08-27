/**
 * The instrument readout: one figure in tabular ink. Instruments snap —
 * the value is never tweened, because a meter that eases is lying about
 * the moment in between.
 */
type StatProps = {
  label: string;
  value: string;
  delta?: string;
  /** Money-in is fern; money-out is umber — an expense is not an error. */
  deltaTone?: 'in' | 'out';
};

export function Stat({ label, value, delta, deltaTone = 'out' }: StatProps) {
  return (
    <div className="stat">
      <div className="stat__label">{label}</div>
      <div className="stat__value">{value}</div>
      {delta === undefined ? null : (
        <div className={`stat__delta stat__delta--${deltaTone}`}>{delta}</div>
      )}
    </div>
  );
}
