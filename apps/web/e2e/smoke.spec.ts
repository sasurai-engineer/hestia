import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

/**
 * The owner's first walk through the app: create the world through the UI,
 * record money, read the report. Everything here exercises the real API and
 * a real database — nothing is stubbed.
 */
test.describe.configure({ mode: 'serial' });

test('the portfolio starts honest and takes a property', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Portfolio' })).toBeVisible();
  // Empty state or an existing card — either way the shell is alive and
  // wearing its own livery (Hestia wordmark, no consultancy).
  await expect(page.locator('.masthead__wordmark')).toHaveText('Hestia');

  await page.goto('/');
  // Wait for a TERMINAL state before branching: isVisible() alone is an
  // immediate check that loses the race against the loading state on a cold
  // server with a fresh database — the button is skipped, and every later
  // step waits on a form nobody opened. Empty portfolio or existing card,
  // one of the two must render first.
  const addFirst = page.getByRole('button', { name: /Add the first property/ });
  await expect(addFirst.or(page.locator('.card').first())).toBeVisible();
  if (await addFirst.isVisible().catch(() => false)) {
    await addFirst.click();
  }
  await page.getByLabel('Street').fill('998 Monmouth St');
  await page.getByLabel('City').fill('Newport');
  await page.getByLabel('State').fill('KY');
  await page.getByLabel('Postal code').fill('41071');
  await page.getByLabel('Year built').fill('1962');
  const entitySelect = page.getByLabel('Owning entity');
  await entitySelect.selectOption({ label: '+ new LLC…' });
  await page.getByLabel('New entity name').fill('Smoke Test LLC');
  await page.getByRole('button', { name: 'Add property' }).click();
  await expect(page.getByText('998 Monmouth St, Newport, KY 41071').first()).toBeVisible();
});

test('a transaction lands in the register and reverses honestly', async ({ page }) => {
  await page.goto('/transactions');
  await page.getByLabel('Date').fill('2026-08-01');
  await page.getByLabel('Category').selectOption('rent');
  await page.getByLabel('Amount').fill('1450.00');
  await page.locator('#tx-property').selectOption({ index: 1 });
  await page.getByLabel('Memo').fill('August rent (smoke)');
  await page.getByRole('button', { name: 'Record' }).click();
  await expect(page.getByText('August rent (smoke)').first()).toBeVisible();
  await page.getByRole('button', { name: 'Reverse' }).first().click();
  await expect(page.getByText('reversal').first()).toBeVisible();
});

test('the reports page rolls the ledger up with authorities', async ({ page }) => {
  await page.goto('/reports');
  await expect(page.getByRole('heading', { name: 'Reports' })).toBeVisible();
  await page.getByLabel('Tax year').fill('2026');
  await expect(page.getByText('Rents received').first()).toBeVisible();
  await expect(page.getByText(/not tax advice/).first()).toBeVisible();
});

test('the dossier carries the spine and the exit instrument', async ({ page }) => {
  await page.goto('/');
  await page.getByText('998 Monmouth St, Newport, KY 41071').first().click();
  // The spine: the property as one navigable time axis, datum at today.
  await expect(page.getByRole('application').first()).toBeVisible();
  // The exit: no valuation on this property yet, so the instrument refuses
  // to guess — the honest gap, not a fake IRR.
  await expect(page.getByText(/Record a valuation to unlock the exit instrument/)).toBeVisible();
});

test('the calendar and coverage pages answer', async ({ page }) => {
  await page.goto('/calendar');
  await expect(
    page.getByText(/authority that creates it|Nothing on the calendar/).first(),
  ).toBeVisible();
  // The spine: the portfolio as one navigable time axis, datum at today.
  await expect(page.getByRole('application').first()).toBeVisible();
  await expect(page.getByText('TODAY').first()).toBeVisible();
  await page.goto('/coverage');
  await expect(page.getByRole('heading', { name: 'Jurisdiction coverage' })).toBeVisible();
});

test('a closing statement walks upload, ratification and apply', async ({ page }) => {
  // The committed ALTA fixture, under a fresh content hash per run: a PDF
  // comment after %%EOF changes nothing a reader touches. Dedupe-by-hash is
  // the feature; the suffix is how a persistent dev database tolerates it.
  const fixture = readFileSync(
    new URL('../../../services/api/tests/fixtures/monmouth-closing.pdf', import.meta.url),
  );
  const unique = Buffer.concat([fixture, Buffer.from(`\n% e2e ${String(Date.now())}`)]);

  await page.goto('/documents');
  await expect(page.getByRole('heading', { name: 'Documents' })).toBeVisible();
  await page.getByLabel('Kind').selectOption('settlement_statement');
  await page.getByLabel('Property', { exact: true }).selectOption({ index: 1 });
  await page.getByLabel('Document (.pdf / .txt)').setInputFiles({
    name: 'monmouth-closing.pdf',
    mimeType: 'application/pdf',
    buffer: unique,
  });
  await page.getByRole('button', { name: 'Upload' }).click();

  // The review page: the PARSER's rows, not the document echoing its own
  // text — a normalized figure in the extraction table proves the machine
  // read the statement; the raw panel would show it either way.
  await expect(page.getByRole('heading', { name: 'monmouth-closing.pdf' })).toBeVisible();
  await expect(
    page
      .getByRole('row', { name: /Sale price/ })
      .getByText(/187,?500\.00/)
      .first(),
  ).toBeVisible();

  // Ratify every required field (starred rows), then apply.
  for (const label of [
    'Closing date',
    'Sale price',
    'Capitalizable closing costs',
    'Property address',
  ]) {
    const row = page.getByRole('row', { name: new RegExp(label) });
    await row.getByRole('button', { name: 'Accept' }).click();
    await expect(row.getByText('ratified')).toBeVisible();
  }
  await expect(page.locator('.pill', { hasText: 'Confirmed' })).toBeVisible();
  await page.getByLabel('Land value').fill('35490.56');
  await page.getByLabel('Allocation method').fill('e2e: assessor-ratio placeholder');
  await page.getByRole('button', { name: 'Apply', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Applied' })).toBeVisible();
  // The basis the server computed, and the ledger event carrying the document.
  await expect(page.getByText(/Basis \$189,283\.00 = land/)).toBeVisible();
  await expect(page.getByText(/ledger event recorded/)).toBeVisible();

  // The purchase stands in the register. Scoped to this property: a closing
  // is dated when it happened (2019), so on a long-lived database it sorts
  // to the far end of a DESC-ordered window.
  await page.goto('/transactions');
  await page.locator('#tx-filter').selectOption({ index: 1 });
  await expect(page.getByRole('row', { name: /Acquisition Cost/ }).first()).toBeVisible();
});

test('a work order completes and the vendor calendar knows its certificate', async ({ page }) => {
  // A vendor with a certificate that expires: the day it lapses is a deadline.
  await page.goto('/vendors');
  await expect(page.getByRole('heading', { name: 'Vendors' })).toBeVisible();
  const vendorName = `Licking Valley Plumbing ${String(Date.now())}`;
  await page.getByLabel('Name').fill(vendorName);
  await page.getByLabel('Trade').selectOption('plumbing');
  await page.getByLabel('Liability expires').fill('2027-06-30');
  await page.getByRole('button', { name: 'Add vendor' }).click();
  await expect(page.getByRole('row', { name: new RegExp(vendorName) })).toBeVisible();
  await expect(
    page.getByRole('row', { name: new RegExp(vendorName) }).getByText('covered'),
  ).toBeVisible();

  // Report work, walk it across the board, and complete it with a cost whose
  // repair-or-improvement answer the system insists on.
  await page.goto('/maintenance');
  await expect(page.getByRole('heading', { name: 'Maintenance' })).toBeVisible();
  await page.getByLabel('Property', { exact: true }).selectOption({ index: 1 });
  const summary = `No hot water ${String(Date.now())}`;
  await page.getByLabel('What is wrong').fill(summary);
  await page.getByLabel('Priority').selectOption('urgent');
  await page.getByRole('button', { name: 'Report work' }).click();
  await expect(page.getByRole('link', { name: summary })).toBeVisible();

  await page.getByRole('link', { name: summary }).click();
  await expect(page.getByRole('heading', { name: summary })).toBeVisible();
  await page.getByRole('button', { name: 'Triaged' }).click();
  // Honest proof of the transition: the button leaves the legal set and the
  // status pill takes the word — a text match alone was satisfied by the
  // button itself, click or no click.
  await expect(page.getByRole('button', { name: 'Triaged' })).toHaveCount(0);
  await expect(page.locator('.pill', { hasText: 'Triaged' })).toBeVisible();

  await page.getByLabel('Invoice amount').fill('180.00');
  await page.getByLabel('Repair or improvement?').selectOption('expense');
  await page.getByRole('button', { name: 'Complete the job' }).click();
  await expect(page.getByRole('heading', { name: 'Completed' })).toBeVisible();
  // The money landed with its authority, and the job carries its net cost —
  // the AMOUNT, because the label renders even at zero and proves nothing.
  await expect(page.getByText(/1\.263\(a\)-1\(f\)/)).toBeVisible();
  await expect(page.getByText(/Net cost \$180\.00/)).toBeVisible();
});
