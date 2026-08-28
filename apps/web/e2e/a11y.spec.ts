import AxeBuilder from '@axe-core/playwright';
import { expect, type Page, test } from '@playwright/test';

/**
 * The accessibility walk: axe-core over every reachable surface, in the same
 * real browser against the same real stack as the smoke walk. Serious and
 * critical violations fail the build — an owner reading figures at 11pm may
 * be doing it with a screen reader, high zoom, or a failing phone, and none
 * of those are edge cases in this house.
 *
 * Scope, stated so a cap is never silent: the nine statically-addressable
 * routes, the dossier (the richest surface: spine, exit, debt, analysis),
 * and the two overlays (command palette, emergency dispatch). The three
 * detail routes that need a document/lease/work-order in flight are
 * exercised by the smoke walk and inherit the shell scanned here.
 */
test.describe.configure({ mode: 'serial' });

const GATING = new Set(['critical', 'serious']);

async function expectClean(page: Page, surface: string) {
  const results = await new AxeBuilder({ page }).analyze();
  const gating = results.violations
    .filter((violation) => GATING.has(violation.impact ?? ''))
    .map(
      (violation) =>
        `${surface} — ${violation.id} (${String(violation.impact)}): ${violation.help} ` +
        `[${String(violation.nodes.length)} nodes, e.g. ${violation.nodes[0]?.target.join(' ') ?? ''}]`,
    );
  expect(gating).toEqual([]);
}

const ROUTES: readonly { path: string; heading: string | RegExp }[] = [
  { path: '/', heading: 'Portfolio' },
  { path: '/transactions', heading: 'Transactions' },
  { path: '/transactions/import', heading: 'Import a statement' },
  { path: '/leases', heading: 'Leases' },
  { path: '/documents', heading: 'Documents' },
  { path: '/maintenance', heading: 'Maintenance' },
  { path: '/vendors', heading: 'Vendors' },
  { path: '/calendar', heading: 'Calendar' },
  { path: '/coverage', heading: 'Jurisdiction coverage' },
  { path: '/reports', heading: 'Reports' },
];

for (const route of ROUTES) {
  test(`axe finds nothing serious on ${route.path}`, async ({ page }) => {
    await page.goto(route.path);
    // A terminal state before scanning: the h1 is server-rendered, then the
    // page hydrates and fetches; scan the settled surface, not the skeleton.
    await expect(page.getByRole('heading', { name: route.heading, level: 1 })).toBeVisible();
    await page.waitForLoadState('networkidle');
    await expectClean(page, route.path);
  });
}

test('axe finds nothing serious on the dossier', async ({ page }) => {
  // This walk owns its property — never assert on another test's world.
  await page.goto('/');
  const addFirst = page.getByRole('button', { name: /Add the first property/ });
  await expect(addFirst.or(page.locator('.card').first())).toBeVisible();
  if (await addFirst.isVisible().catch(() => false)) {
    await addFirst.click();
  }
  const street = `443 Accessibility Ct ${String(Date.now())}`;
  await page.getByLabel('Street').fill(street);
  await page.getByLabel('City').fill('Newport');
  await page.getByLabel('State').fill('KY');
  await page.getByLabel('Postal code').fill('41071');
  await page.getByLabel('Year built').fill('1962');
  await page.getByLabel('Owning entity').selectOption({ label: '+ new LLC…' });
  await page.getByLabel('New entity name').fill('A11y Walk LLC');
  await page.getByRole('button', { name: 'Add property' }).click();
  await page.getByText(new RegExp(street)).first().click();
  await expect(page.getByRole('application').first()).toBeVisible();
  await page.waitForLoadState('networkidle');
  await expectClean(page, '/property/[id]');
});

test('axe finds nothing serious in the command palette', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Portfolio', level: 1 })).toBeVisible();
  await page.keyboard.press('ControlOrMeta+k');
  await expect(page.getByPlaceholder('Type a command…')).toBeVisible();
  await expectClean(page, 'command palette');
});

test('axe finds nothing serious on the 11pm surface', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Portfolio', level: 1 })).toBeVisible();
  await page.getByRole('button', { name: 'Emergency', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expectClean(page, 'emergency dispatch');
});
