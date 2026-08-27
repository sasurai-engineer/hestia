import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DecisionCard } from './DecisionCard.js';

const GROUNDED = {
  title: 'Hold vs. redeploy',
  figureLabel: 'Forward ROE',
  figure: '11.2%',
  verdict: { label: 'hold', tone: 'ok' as const },
  authority: [
    { cite: 'engines/holdsell', detail: 'forward year return on current equity' },
    { cite: 'KRS 383.580', detail: 'deposit itemization', kind: 'statute' as const },
  ] as const,
  counterfactual: 'Redeploying forfeits 3.2 points of forward return.',
  scan: 'Equity keeps earning above the hurdle.',
};

describe('DecisionCard', () => {
  it('shows the glance — title, figure, verdict — before any depth opens', () => {
    render(<DecisionCard {...GROUNDED} />);
    expect(screen.getByRole('heading', { name: 'Hold vs. redeploy' })).toBeDefined();
    expect(screen.getByText('11.2%').className).toBe('stat__value');
    expect(screen.getByText('hold').className).toBe('pill pill--ok');
    expect(screen.getByRole('button', { name: /the working/ })).toBeDefined();
  });

  it('cannot be rendered ungrounded — the type system refuses', () => {
    // @ts-expect-error: an empty authority list must not compile.
    const ungrounded = <DecisionCard {...GROUNDED} authority={[]} />;
    expect(ungrounded).toBeDefined();
  });

  it('stamps statutes in survey-blue and signs engines in graphite', () => {
    const { container } = render(<DecisionCard {...GROUNDED} />);
    fireEvent.click(screen.getByRole('button', { name: /the working/ }));
    expect(container.querySelector('.citation-chip')?.textContent).toBe('KRS 383.580');
    const engine = container.querySelector('.engine-chip');
    expect(engine?.textContent).toBe('engines/holdsell');
    expect(engine?.getAttribute('title')).toBe('forward year return on current equity');
  });

  it('falls back to the cite as the engine tooltip', () => {
    const { container } = render(
      <DecisionCard {...GROUNDED} authority={[{ cite: 'engines/insurance' }]} />,
    );
    expect(container.querySelector('.engine-chip')?.getAttribute('title')).toBe(
      'engines/insurance',
    );
  });

  it('unfolds scan, then study, then audit, each inside the last', () => {
    render(
      <DecisionCard
        {...GROUNDED}
        study={<p>sliders live here</p>}
        audit={<p>provenance lives here</p>}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /the working/ }));
    expect(screen.getByText(GROUNDED.scan).className).toBe('decision__scan');
    expect(screen.getByText(GROUNDED.counterfactual).className).toBe('decision__counterfactual');
    fireEvent.click(screen.getByRole('button', { name: /adjust the inputs/ }));
    expect(screen.getByText('sliders live here')).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: /audit every figure/ }));
    expect(screen.getByText('provenance lives here')).toBeDefined();
  });

  it('nests the audit directly under the working when there is no study', () => {
    render(<DecisionCard {...GROUNDED} audit={<p>provenance</p>} />);
    fireEvent.click(screen.getByRole('button', { name: /the working/ }));
    expect(screen.queryByRole('button', { name: /adjust the inputs/ })).toBeNull();
    expect(screen.getByRole('button', { name: /audit every figure/ })).toBeDefined();
  });

  it('offers no deeper depths when the card has none', () => {
    render(<DecisionCard {...GROUNDED} />);
    fireEvent.click(screen.getByRole('button', { name: /the working/ }));
    expect(screen.queryByRole('button', { name: /adjust the inputs/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /audit every figure/ })).toBeNull();
  });

  it('carries at most one action, and it acts', () => {
    const act = vi.fn();
    const { rerender } = render(<DecisionCard {...GROUNDED} />);
    expect(screen.queryByRole('button', { name: 'Offer renewal' })).toBeNull();
    rerender(<DecisionCard {...GROUNDED} action={{ label: 'Offer renewal', act }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Offer renewal' }));
    expect(act).toHaveBeenCalledTimes(1);
  });

  it('shows a caveat only when the caller confesses one', () => {
    const { rerender } = render(<DecisionCard {...GROUNDED} />);
    expect(document.querySelector('.decision__caveat')).toBeNull();
    rerender(<DecisionCard {...GROUNDED} caveat="Assumes straight-line appreciation." />);
    expect(screen.getByText('Assumes straight-line appreciation.').className).toContain(
      'decision__caveat',
    );
  });
});
