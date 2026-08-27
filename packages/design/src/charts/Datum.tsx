/**
 * The datum: today as a fixed vertical rule with a plumb-bob diamond at its
 * head. Everything left of it is fact in solid ink; everything right is
 * projection, dashed — the one orientation mark every time surface shares.
 */
type DatumProps = {
  x: number;
  top: number;
  bottom: number;
  label?: string;
};

export function Datum({ x, top, bottom, label = 'TODAY' }: DatumProps) {
  const head = top + 5;
  return (
    <g>
      <line className="chart__datum" x1={x} x2={x} y1={top + 8} y2={bottom} />
      <path
        className="chart__plumb"
        d={`M${x} ${head + 6} L${x - 4} ${head} L${x} ${head - 6} L${x + 4} ${head} Z`}
      />
      <text className="chart__datum-label" x={x + 7} y={head + 3}>
        {label}
      </text>
    </g>
  );
}
