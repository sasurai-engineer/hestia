/**
 * The 11pm arithmetic: symptom → trade → a ranked call list. Pure, so the
 * overlay stays a dumb surface. The ranking never hides a vendor for an
 * expired certificate — at 11pm the owner may still choose them, knowingly —
 * it demotes and says why. 'Unknown' is not 'covered', and the copy says
 * that too.
 */
import type { VendorOut } from './api';
import { formatDate } from './format';

export type VendorTrade = VendorOut['trade'];

export interface Symptom {
  id: string;
  label: string;
  trade: VendorTrade;
  /** Safety guidance that outranks any phone call. */
  note?: string;
}

export const SYMPTOMS: readonly Symptom[] = [
  { id: 'water', label: 'Water — burst pipe, leak, no water', trade: 'plumbing' },
  { id: 'heat', label: 'No heat or cooling', trade: 'hvac' },
  {
    id: 'electrical',
    label: 'Electrical — outage, sparks, burning smell',
    trade: 'electrical',
    note: 'If anything is arcing or smoking, cut the breaker before you dial.',
  },
  { id: 'roof', label: 'Roof leak or storm damage', trade: 'roofing' },
  {
    id: 'gas',
    label: 'Gas smell',
    trade: 'plumbing',
    note: 'Leave the building and call the gas utility’s emergency line FIRST. A plumber is the second call, not the first.',
  },
];

const FALLBACK_TRADES: readonly VendorTrade[] = ['general_contractor', 'handyman'];

const COVERAGE_ORDER: Record<VendorOut['coverage_state'], number> = {
  current: 0,
  expiring: 1,
  unknown: 2,
  expired: 3,
};

export interface RankedVendor {
  vendor: VendorOut;
  /** A general trade standing in because no exact match exists to call. */
  fallback: boolean;
  proof: string;
  proofTone: 'ok' | 'warn' | 'bad';
}

function proofOf(vendor: VendorOut): { proof: string; proofTone: 'ok' | 'warn' | 'bad' } {
  switch (vendor.coverage_state) {
    case 'current':
      return {
        proof:
          vendor.liability_expires_on === null
            ? 'insured — certificate on file'
            : `insured through ${formatDate(vendor.liability_expires_on)}`,
        proofTone: 'ok',
      };
    case 'expiring':
      return {
        proof:
          vendor.liability_expires_on === null
            ? 'insurance expiring soon — renew the certificate'
            : `insurance expires ${formatDate(vendor.liability_expires_on)} — renew the certificate`,
        proofTone: 'warn',
      };
    case 'unknown':
      return { proof: 'insurance unverified — no certificate on record', proofTone: 'warn' };
    case 'expired':
      return {
        proof:
          vendor.liability_expires_on === null
            ? 'liability coverage lapsed — their mistakes bill to your policy'
            : `liability lapsed ${formatDate(vendor.liability_expires_on)} — their mistakes bill to your policy`,
        proofTone: 'bad',
      };
  }
}

const rankWithin = (a: VendorOut, b: VendorOut): number => {
  const phone = Number(a.phone === null) - Number(b.phone === null);
  if (phone !== 0) {
    return phone;
  }
  const coverage = COVERAGE_ORDER[a.coverage_state] - COVERAGE_ORDER[b.coverage_state];
  if (coverage !== 0) {
    return coverage;
  }
  return a.name.localeCompare(b.name);
};

/** Exact-trade vendors first, general trades after, each group ranked by
 * reachability (a number to dial), then coverage, then name. */
export function rankVendors(vendors: readonly VendorOut[], trade: VendorTrade): RankedVendor[] {
  const active = vendors.filter((vendor) => vendor.retired_on === null);
  const primary = active.filter((vendor) => vendor.trade === trade).sort(rankWithin);
  const fallback = FALLBACK_TRADES.includes(trade)
    ? []
    : active.filter((vendor) => FALLBACK_TRADES.includes(vendor.trade)).sort(rankWithin);
  return [
    ...primary.map((vendor) => ({ vendor, fallback: false, ...proofOf(vendor) })),
    ...fallback.map((vendor) => ({ vendor, fallback: true, ...proofOf(vendor) })),
  ];
}
