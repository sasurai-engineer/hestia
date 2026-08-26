import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

// Explicit because vitest globals are off, and without globals Testing
// Library cannot register its own between-test cleanup.
afterEach(cleanup);

import { ComponentsTable } from '../src/components/ComponentsTable';
import { DeadlineList } from '../src/components/DeadlineList';
import { DefectRegister } from '../src/components/DefectRegister';
import { HazardCard } from '../src/components/HazardCard';
import { JurisdictionChain } from '../src/components/JurisdictionChain';
import { StatusPill } from '../src/components/StatusPill';
import type { ComponentOut, DeadlineOut, DefectOut, HazardOut } from '../src/lib/api';

describe('StatusPill', () => {
  it('renders the known statuses as their own variants and flags the rest', () => {
    const { container, rerender } = render(<StatusPill status="ok" />);
    expect(container.querySelector('.pill--ok')).not.toBeNull();
    rerender(<StatusPill status="failed" />);
    expect(container.querySelector('.pill--failed')).not.toBeNull();
    rerender(<StatusPill status="suspected" />);
    expect(container.querySelector('.pill--flag')).not.toBeNull();
  });
});

describe('JurisdictionChain', () => {
  it('walks the chain most specific first', () => {
    render(
      <JurisdictionChain
        chain={[
          { name: 'Newport', level: 'municipality' },
          { name: 'Campbell County', level: 'county' },
        ]}
      />,
    );
    expect(screen.getByText('Newport')).toBeDefined();
    expect(screen.getByText('(county)')).toBeDefined();
  });
  it('says exactly what an empty chain means', () => {
    render(<JurisdictionChain chain={[]} />);
    expect(screen.getByText(/No jurisdiction pack covers/)).toBeDefined();
  });
});

describe('HazardCard', () => {
  const flood = (overrides: Partial<HazardOut>): HazardOut => ({
    kind: 'flood',
    zone: 'X',
    in_special_flood_hazard_area: false,
    base_flood_elevation_ft: null,
    observed_at: '2026-08-26T00:00:00Z',
    ...overrides,
  });
  it('shows the zone and SFHA posture', () => {
    render(<HazardCard hazard={flood({})} />);
    expect(screen.getByText(/Zone X/)).toBeDefined();
    expect(screen.getByText('outside the SFHA')).toBeDefined();
  });
  it('shows an in-SFHA fact with its elevation', () => {
    render(
      <HazardCard
        hazard={flood({
          zone: 'AE',
          in_special_flood_hazard_area: true,
          base_flood_elevation_ft: 512.3,
        })}
      />,
    );
    expect(screen.getByText('in the special flood hazard area')).toBeDefined();
    expect(screen.getByText(/512.3 ft/)).toBeDefined();
  });
  it('renders an unmapped hazard without a posture pill', () => {
    const { container } = render(
      <HazardCard hazard={flood({ zone: null, in_special_flood_hazard_area: null })} />,
    );
    expect(screen.getByText(/Zone unmapped/)).toBeDefined();
    expect(container.querySelector('.pill')).toBeNull();
  });
});

describe('ComponentsTable', () => {
  const component = (overrides: Partial<ComponentOut>): ComponentOut => ({
    code: 'water_heater.tank',
    display_name: 'Tank water heater',
    system: 'water_heater',
    installed_year_low: 2014,
    installed_year_high: 2026,
    life_years_low: 8,
    life_years_high: 12,
    condition: 'unknown',
    provenance_kind: 'inferred',
    confidence: 0.5,
    derived_from: 'built 1962, no permit on file',
    ...overrides,
  });
  it('renders the band, the life bar, and the basis', () => {
    render(<ComponentsTable components={[component({})]} nowYear={2026} />);
    expect(screen.getByText('2014–2026')).toBeDefined();
    expect(screen.getByText(/inferred · 50%/)).toBeDefined();
    expect(screen.getByRole('meter').getAttribute('aria-valuenow')).toBe('50');
  });
  it('marks an exhausted life and a single-year band', () => {
    const { container } = render(
      <ComponentsTable
        components={[component({ code: 'a', installed_year_low: 2000, installed_year_high: 2000 })]}
        nowYear={2026}
      />,
    );
    expect(screen.getByText('2000')).toBeDefined();
    expect(container.querySelector('.lifebar__fill--spent')).not.toBeNull();
  });
  it('shows unknown bands and missing lives without a bar', () => {
    const { container } = render(
      <ComponentsTable
        components={[component({ code: 'b', installed_year_low: null, derived_from: null })]}
        nowYear={2026}
      />,
    );
    expect(screen.getByText('unknown')).toBeDefined();
    expect(container.querySelector('.lifebar')).toBeNull();
  });
  it('invites assembly when empty', () => {
    render(<ComponentsTable components={[]} nowYear={2026} />);
    expect(screen.getByText(/assemble the dossier/i)).toBeDefined();
  });
});

describe('DefectRegister', () => {
  const defect = (overrides: Partial<DefectOut>): DefectOut => ({
    kind: 'lead_paint',
    status: 'suspected',
    affects_safety: true,
    affects_insurance: false,
    affects_financing: false,
    triggers_disclosure: true,
    citation: '42 U.S.C. s.4852d',
    derived_from: 'built 1962',
    ...overrides,
  });
  it('renders the flag with its consequences and citation', () => {
    render(<DefectRegister defects={[defect({})]} />);
    expect(screen.getByText('Lead Paint')).toBeDefined();
    expect(screen.getByText('safety · disclosure')).toBeDefined();
    expect(screen.getByText('42 U.S.C. s.4852d')).toBeDefined();
  });
  it('says so when a defect models no consequence and cites nothing', () => {
    render(
      <DefectRegister
        defects={[
          defect({
            kind: 'cast_iron_drain',
            affects_safety: false,
            triggers_disclosure: false,
            citation: null,
            derived_from: null,
          }),
        ]}
      />,
    );
    expect(screen.getByText('no modeled consequence')).toBeDefined();
  });
  it('reports a clean vintage', () => {
    render(<DefectRegister defects={[]} />);
    expect(screen.getByText(/No latent-defect flags/)).toBeDefined();
  });
});

describe('DeadlineList', () => {
  const deadline = (overrides: Partial<DeadlineOut>): DeadlineOut => ({
    id: 'd1',
    kind: 'assessment_appeal_window',
    status: 'upcoming',
    due_on: '2027-05-17',
    window_opens_on: '2027-05-03',
    citation: 'KRS 133.045',
    note: 'PVA conference (Form 62A307) must occur within the window',
    property_label: '998 Monmouth',
    ...overrides,
  });
  it('renders the runway, the note, and the authority', () => {
    render(<DeadlineList deadlines={[deadline({})]} />);
    expect(screen.getByText('May 17, 2027')).toBeDefined();
    expect(screen.getByText('opens May 3, 2027')).toBeDefined();
    expect(screen.getByText('KRS 133.045')).toBeDefined();
    expect(screen.getByText(/62A307/)).toBeDefined();
  });
  it('labels entity-wide dates and dates without a window', () => {
    render(
      <DeadlineList
        deadlines={[
          deadline({
            id: 'd2',
            kind: 'estimated_tax',
            window_opens_on: null,
            note: null,
            property_label: null,
          }),
        ]}
      />,
    );
    expect(screen.getByText('entity-wide')).toBeDefined();
    expect(screen.queryByText(/opens/)).toBeNull();
  });
  it('points at the sweep when empty', () => {
    render(<DeadlineList deadlines={[]} />);
    expect(screen.getByText(/run a dossier sweep/i)).toBeDefined();
  });
});
