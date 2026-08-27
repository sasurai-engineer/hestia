import { describe, expect, it } from 'vitest';
import type { VendorOut } from '../src/lib/api';
import { rankVendors, SYMPTOMS } from '../src/lib/dispatch';

const vendor = (overrides: Partial<VendorOut>): VendorOut => ({
  id: overrides.name ?? 'v',
  entity_id: 'e1',
  entity_name: 'Smoke Test LLC',
  name: 'Vendor',
  trade: 'plumbing',
  phone: '859-555-0100',
  email: null,
  license_number: null,
  license_expires_on: null,
  insurer: null,
  liability_expires_on: '2027-06-30',
  workers_comp_expires_on: null,
  w9_on_file: false,
  is_1099_reportable: false,
  notes: null,
  coverage_state: 'current',
  earliest_expiry: null,
  open_work_orders: 0,
  also_registered_under: [],
  retired_on: null,
  ...overrides,
});

describe('SYMPTOMS', () => {
  it('names a trade the schema actually holds, and safety notes where they matter', () => {
    for (const symptom of SYMPTOMS) {
      expect(symptom.trade).toBeTruthy();
    }
    expect(SYMPTOMS.find((s) => s.id === 'gas')?.note).toMatch(/utility.*FIRST/);
  });
});

describe('rankVendors', () => {
  it('ranks reachable before unreachable, covered before lapsed, then by name', () => {
    const ranked = rankVendors(
      [
        vendor({ name: 'Zeta Covered', coverage_state: 'current' }),
        vendor({ name: 'Alpha Covered', coverage_state: 'current' }),
        vendor({ name: 'Lapsed', coverage_state: 'expired', liability_expires_on: '2026-07-01' }),
        vendor({ name: 'No Phone', phone: null }),
        vendor({ name: 'Unknown Cover', coverage_state: 'unknown', liability_expires_on: null }),
      ],
      'plumbing',
    );
    expect(ranked.map((entry) => entry.vendor.name)).toEqual([
      'Alpha Covered',
      'Zeta Covered',
      'Unknown Cover',
      'Lapsed',
      'No Phone',
    ]);
  });

  it('never hides a lapsed vendor — it demotes and says why', () => {
    const [lapsed] = rankVendors(
      [vendor({ name: 'Lapsed', coverage_state: 'expired', liability_expires_on: '2026-07-01' })],
      'plumbing',
    );
    expect(lapsed?.proofTone).toBe('bad');
    expect(lapsed?.proof).toBe('liability lapsed Jul 1, 2026 — their mistakes bill to your policy');
  });

  it('speaks each coverage state honestly, with and without a date', () => {
    const proofs = (v: VendorOut) => rankVendors([v], v.trade)[0];
    expect(proofs(vendor({ coverage_state: 'current' }))?.proof).toBe(
      'insured through Jun 30, 2027',
    );
    expect(proofs(vendor({ coverage_state: 'current', liability_expires_on: null }))?.proof).toBe(
      'insured — certificate on file',
    );
    expect(proofs(vendor({ coverage_state: 'expiring' }))?.proof).toBe(
      'insurance expires Jun 30, 2027 — renew the certificate',
    );
    expect(proofs(vendor({ coverage_state: 'expiring', liability_expires_on: null }))?.proof).toBe(
      'insurance expiring soon — renew the certificate',
    );
    expect(proofs(vendor({ coverage_state: 'unknown', liability_expires_on: null }))?.proof).toBe(
      'insurance unverified — no certificate on record',
    );
    expect(proofs(vendor({ coverage_state: 'expired', liability_expires_on: null }))?.proof).toBe(
      'liability coverage lapsed — their mistakes bill to your policy',
    );
    expect(proofs(vendor({ coverage_state: 'expiring' }))?.proofTone).toBe('warn');
    expect(
      proofs(vendor({ coverage_state: 'unknown', liability_expires_on: null }))?.proofTone,
    ).toBe('warn');
  });

  it('appends general trades as a labeled fallback, never for their own call', () => {
    const ranked = rankVendors(
      [
        vendor({ name: 'GC', trade: 'general_contractor' }),
        vendor({ name: 'Handy', trade: 'handyman' }),
        vendor({ name: 'Pipes', trade: 'plumbing' }),
      ],
      'plumbing',
    );
    expect(ranked.map((entry) => `${entry.vendor.name}${entry.fallback ? '*' : ''}`)).toEqual([
      'Pipes',
      'GC*',
      'Handy*',
    ]);
    // Asking FOR a general trade must not duplicate them as their own fallback.
    const general = rankVendors(
      [vendor({ name: 'Handy', trade: 'handyman' }), vendor({ name: 'Pipes' })],
      'handyman',
    );
    expect(general.map((entry) => entry.vendor.name)).toEqual(['Handy']);
  });

  it('leaves the retired in peace', () => {
    expect(rankVendors([vendor({ retired_on: '2026-01-01' })], 'plumbing')).toEqual([]);
  });
});
