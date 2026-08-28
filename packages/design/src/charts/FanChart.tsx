import { ChartFrame } from './ChartFrame.js';
import { areaPath, linePath } from './path.js';
import { linearScale } from './scale.js';

/**
 * A confidence fan: the band is the honest spread, the traced line is the
 * median. The draftsman draws it once, at mount.
 */
export type FanBand = { label: string; low: number; mid: number; high: number };

type FanChartProps = {
  bands: readonly FanBand[];
  label: string;
  /** Band labels to wash in the failure tint — an underfunded year is a
   * failure state, and madder is its ink. */
  shaded?: readonly string[];
  width?: number;
  height?: number;
};

export function FanChart({ bands, label, shaded = [], width = 560, height = 150 }: FanChartProps) {
  const peak = Math.max(...bands.map((band) => band.high), 1);
  const x = linearScale(0, Math.max(bands.length - 1, 1), 30, width - 20);
  const y = linearScale(0, peak, height - 24, 16);
  const upper = bands.map((band, index) => ({ x: x(index), y: y(band.high) }));
  const lower = bands.map((band, index) => ({ x: x(index), y: y(band.low) }));
  const mid = bands.map((band, index) => ({ x: x(index), y: y(band.mid) }));
  const edge = (index: number): [number, number] => [
    index === 0 ? x(0) - 12 : (x(index - 1) + x(index)) / 2,
    index === bands.length - 1 ? x(index) + 12 : (x(index) + x(index + 1)) / 2,
  ];
  return (
    <ChartFrame viewWidth={width} viewHeight={height} label={label}>
      {bands.map((band, index) => {
        if (!shaded.includes(band.label)) {
          return null;
        }
        const [from, to] = edge(index);
        return (
          <rect
            key={`shade-${band.label}`}
            className="chart__shade"
            x={from}
            width={to - from}
            y={10}
            height={height - 30}
          />
        );
      })}
      <path className="chart__band" d={areaPath(upper, lower)} />
      {mid.length === 0 ? null : (
        <path className="chart__line trace" pathLength={1} d={linePath(mid)} />
      )}
      {bands.map((band, index) => (
        <text
          key={band.label}
          className="chart__axis"
          x={x(index)}
          y={height - 8}
          textAnchor="middle"
        >
          {band.label}
        </text>
      ))}
    </ChartFrame>
  );
}
