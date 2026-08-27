import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BalanceCurve } from './BalanceCurve.js';
import { ChartFrame } from './ChartFrame.js';
import { Datum } from './Datum.js';
import { FanChart } from './FanChart.js';
import { Sparkline } from './Sparkline.js';
import { linearScale } from './scale.js';
import { TimeAxis } from './TimeAxis.js';

describe('ChartFrame', () => {
  it('is a named image with the chart class', () => {
    const { container } = render(
      <ChartFrame viewWidth={100} viewHeight={40} label="A named figure" className="extra">
        <circle r={1} />
      </ChartFrame>,
    );
    const svg = screen.getByRole('img', { name: 'A named figure' });
    expect(svg.getAttribute('viewBox')).toBe('0 0 100 40');
    expect(svg.getAttribute('class')).toBe('chart extra');
    expect(container.querySelector('circle')).not.toBeNull();
  });
});

const BANDS = [
  { label: '1', low: 0, mid: 0, high: 3200 },
  { label: '2', low: 0, mid: 850, high: 4100 },
  { label: '3', low: 0, mid: 1500, high: 6000 },
];

describe('FanChart', () => {
  it('draws the band, the traced median, and a label per band', () => {
    const { container } = render(<FanChart bands={BANDS} label="Capital spend fan" />);
    const band = container.querySelector('.chart__band');
    const line = container.querySelector('.chart__line');
    // Upper edge first: high=3200 of peak 6000 → y = 126 − (3200/6000)·110.
    expect(band?.getAttribute('d')).toMatch(/^M30 67\.33 .*Z$/);
    expect(line?.getAttribute('d')).toMatch(/^M30 126/);
    expect(line?.getAttribute('class')).toBe('chart__line trace');
    expect(line?.getAttribute('pathLength')).toBe('1');
    expect(screen.getAllByText(/^[123]$/)).toHaveLength(3);
  });

  it('renders an honest empty frame when there are no bands', () => {
    const { container } = render(<FanChart bands={[]} label="Nothing simulated" />);
    expect(screen.getByRole('img', { name: 'Nothing simulated' })).toBeDefined();
    expect(container.querySelector('.chart__line')).toBeNull();
  });
});

describe('Sparkline', () => {
  it('renders nothing for an empty history', () => {
    const { container } = render(<Sparkline values={[]} />);
    expect(container.firstElementChild).toBeNull();
  });

  it('is decoration without a label and a named image with one', () => {
    const { container, rerender } = render(<Sparkline values={[1, 2, 3]} />);
    expect(container.firstElementChild?.getAttribute('aria-hidden')).toBe('true');
    rerender(<Sparkline values={[1, 2, 3]} label="Rent collected, last three months" />);
    expect(screen.getByRole('img', { name: 'Rent collected, last three months' })).toBeDefined();
  });

  it('draws a flat history on the midline', () => {
    const { container } = render(<Sparkline values={[5, 5, 5]} />);
    expect(container.querySelector('.chart__spark')?.getAttribute('d')).toBe(
      'M2 14 L60 14 L118 14',
    );
  });
});

const CURVE = [
  { x: 0, y: 1000 },
  { x: 12, y: 800 },
  { x: 24, y: 550 },
  { x: 36, y: 0 },
];

describe('BalanceCurve', () => {
  it('renders nothing without points', () => {
    const { container } = render(<BalanceCurve points={[]} label="Empty" />);
    expect(container.firstElementChild).toBeNull();
  });

  it('draws a grid from nice ticks and one solid traced line', () => {
    const { container } = render(
      <BalanceCurve
        points={CURVE}
        label="Note balance"
        formatY={(y) => `$${y}`}
        formatX={(x) => `m${x}`}
      />,
    );
    expect(container.querySelectorAll('.chart__grid').length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText('$1000')).toBeDefined();
    expect(screen.getByText('m20')).toBeDefined();
    expect(container.querySelector('.chart__line.trace')).not.toBeNull();
    expect(container.querySelector('.chart__line--projected')).toBeNull();
  });

  it('splits fact from projection at the boundary — dashed, never solid', () => {
    const { container } = render(
      <BalanceCurve points={CURVE} label="Note balance" projectedFrom={12} />,
    );
    const solid = container.querySelector('.chart__line.trace');
    const dashed = container.querySelector('.chart__line--projected');
    expect(solid?.getAttribute('d')).toMatch(/^M52 /);
    expect(dashed).not.toBeNull();
  });

  it('draws pure projection when everything lies beyond the boundary', () => {
    const { container } = render(
      <BalanceCurve points={CURVE} label="All projection" projectedFrom={-1} />,
    );
    expect(container.querySelector('.chart__line.trace')).toBeNull();
    expect(container.querySelector('.chart__line--projected')).not.toBeNull();
  });

  it('tolerates a single all-zero point', () => {
    const { container } = render(
      <BalanceCurve points={[{ x: 5, y: 0 }]} label="One settled point" />,
    );
    expect(screen.getByText('5')).toBeDefined();
    expect(container.querySelector('.chart__line.trace')).not.toBeNull();
  });
});

describe('TimeAxis', () => {
  it('draws the baseline and one tick per boundary, years heavier', () => {
    const ticks = [
      { day: 100, label: 'Feb', major: false },
      { day: 130, label: '1971', major: true },
    ];
    const { container } = render(
      <svg role="img" aria-label="axis under test">
        <TimeAxis ticks={ticks} x={linearScale(90, 140, 0, 500)} y={80} from={0} to={500} />
      </svg>,
    );
    expect(container.querySelector('.chart__axis-line')?.getAttribute('x2')).toBe('500');
    expect(container.querySelectorAll('.chart__tick')).toHaveLength(2);
    expect(screen.getByText('Feb').getAttribute('class')).toBe('chart__axis');
    expect(screen.getByText('1971').getAttribute('class')).toBe('chart__axis chart__axis--major');
    expect(screen.getByText('Feb').getAttribute('x')).toBe('100');
  });
});

describe('Datum', () => {
  it('drops the plumb line with its diamond and default label', () => {
    const { container } = render(
      <svg role="img" aria-label="datum under test">
        <Datum x={250} top={10} bottom={120} />
      </svg>,
    );
    const rule = container.querySelector('.chart__datum');
    expect(rule?.getAttribute('x1')).toBe('250');
    expect(rule?.getAttribute('y2')).toBe('120');
    expect(container.querySelector('.chart__plumb')).not.toBeNull();
    expect(screen.getByText('TODAY').getAttribute('class')).toBe('chart__datum-label');
  });

  it('takes a caller label', () => {
    render(
      <svg role="img" aria-label="datum labeled">
        <Datum x={10} top={0} bottom={50} label="AS OF" />
      </svg>,
    );
    expect(screen.getByText('AS OF')).toBeDefined();
  });
});
