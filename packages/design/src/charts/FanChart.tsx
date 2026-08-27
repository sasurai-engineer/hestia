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
  width?: number;
  height?: number;
};

export function FanChart({ bands, label, width = 560, height = 150 }: FanChartProps) {
  const peak = Math.max(...bands.map((band) => band.high), 1);
  const x = linearScale(0, Math.max(bands.length - 1, 1), 30, width - 20);
  const y = linearScale(0, peak, height - 24, 16);
  const upper = bands.map((band, index) => ({ x: x(index), y: y(band.high) }));
  const lower = bands.map((band, index) => ({ x: x(index), y: y(band.low) }));
  const mid = bands.map((band, index) => ({ x: x(index), y: y(band.mid) }));
  return (
    <ChartFrame viewWidth={width} viewHeight={height} label={label}>
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
