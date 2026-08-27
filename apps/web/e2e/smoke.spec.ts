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
  const addFirst = page.getByRole('button', { name: /Add the first property/ });
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

test('the calendar and coverage pages answer', async ({ page }) => {
  await page.goto('/calendar');
  await expect(
    page.getByText(/authority that creates it|Nothing on the calendar/).first(),
  ).toBeVisible();
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

  // The review page: the machine read the statement; the figures are there.
  await expect(page.getByRole('heading', { name: 'monmouth-closing.pdf' })).toBeVisible();
  await expect(page.getByText('Sale Price of Property   $187,500.00')).toBeVisible();
  await expect(page.getByText('$189,283.00')).toBeVisible(); // server-computed basis

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
  await expect(page.getByText('Confirmed')).toBeVisible();
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
