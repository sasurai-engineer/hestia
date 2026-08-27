'use client';

import { type Command, CommandPalette, useCommandK } from '@hestia/design';
import { useRouter } from 'next/navigation';
import { useCallback, useRef, useState } from 'react';
import { api, type PropertySummary } from '../lib/api';
import { EmergencyDispatch } from './EmergencyDispatch';

/**
 * ⌘K, wired: one keystroke to any page or property. Routes are static;
 * properties load once, on first open, and never block the palette — an
 * instrument that stalls while its owner types is not an instrument.
 */
const ROUTES: readonly { label: string; path: string }[] = [
  { label: 'Portfolio', path: '/' },
  { label: 'Leases', path: '/leases' },
  { label: 'Transactions', path: '/transactions' },
  { label: 'Import a bank statement', path: '/transactions/import' },
  { label: 'Documents', path: '/documents' },
  { label: 'Maintenance', path: '/maintenance' },
  { label: 'Vendors', path: '/vendors' },
  { label: 'Reports', path: '/reports' },
  { label: 'Calendar', path: '/calendar' },
  { label: 'Coverage', path: '/coverage' },
];

export function CommandBar() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [dispatchOpen, setDispatchOpen] = useState(false);
  const [properties, setProperties] = useState<readonly PropertySummary[]>([]);
  const fetched = useRef(false);

  const openPalette = useCallback(() => {
    setOpen(true);
    if (!fetched.current) {
      fetched.current = true;
      api
        .listProperties()
        .then(setProperties)
        .catch(() => {
          // The palette stays useful without properties; try again next open.
          fetched.current = false;
        });
    }
  }, []);

  useCommandK(openPalette);

  const commands: Command[] = [
    {
      id: 'emergency',
      label: 'Emergency: burst pipe, no heat, electrical…',
      hint: 'dispatch',
      run: () => setDispatchOpen(true),
    },
    ...ROUTES.map((route) => ({
      id: `go${route.path}`,
      label: `Go: ${route.label}`,
      hint: route.path,
      run: () => router.push(route.path),
    })),
    ...properties.map((property) => ({
      id: `property-${property.id}`,
      label: `Property: ${property.label}`,
      hint: 'dossier',
      run: () => router.push(`/property/${property.id}`),
    })),
  ];

  return (
    <>
      <button
        type="button"
        className="masthead__command"
        aria-label="Open the command palette"
        onClick={openPalette}
      >
        ⌘K
      </button>
      <button type="button" className="masthead__emergency" onClick={() => setDispatchOpen(true)}>
        Emergency
      </button>
      <CommandPalette
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        commands={commands}
      />
      <EmergencyDispatch open={dispatchOpen} onClose={() => setDispatchOpen(false)} />
    </>
  );
}
