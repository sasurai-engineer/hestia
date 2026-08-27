import { linePath } from './path.js';
import { linearScale } from './scale.js';

/**
 * A figure's recent history in one stroke. With a label it is a named
 * image; without one it is decoration beside a figure that already says
 * the number.
 */
type SparklineProps = {
  values: readonly number[];
  width?: number;
  height?: number;
  label?: string;
};

export function Sparkline({ values, width = 120, height = 28, label }: SparklineProps) {
  if (values.length === 0) {
    return null;
  }
  const x = linearScale(0, Math.max(values.length - 1, 1), 2, width - 2);
  const y = linearScale(Math.min(...values), Math.max(...values), height - 3, 3);
  const d = linePath(values.map((value, index) => ({ x: x(index), y: y(value) })));
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="chart chart--spark"
      role={label === undefined ? undefined : 'img'}
      aria-label={label}
      aria-hidden={label === undefined ? true : undefined}
    >
      <path className="chart__spark" d={d} />
    </svg>
  );
}
