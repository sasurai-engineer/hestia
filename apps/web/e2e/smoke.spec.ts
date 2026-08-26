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
