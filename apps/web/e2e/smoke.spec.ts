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

test('the command palette answers ⌘K and navigates', async ({ page }) => {
  await page.goto('/');
  await page.keyboard.press('ControlOrMeta+k');
  const paletteInput = page.getByPlaceholder('Type a command…');
  await expect(paletteInput).toBeVisible();
  await paletteInput.fill('calen');
  await paletteInput.press('Enter');
  await expect(page.getByRole('heading', { name: 'Calendar' })).toBeVisible();
});

test('the 11pm surface: property, symptom, proof, and the incident on the board', async ({
  page,
}) => {
  // This test OWNS its plumber. It previously asserted a certificate date that
  // a different test happened to create, and when the file order changed the
  // vendor no longer existed by the time the overlay opened — five passed, this
  // failed, three never ran. A fixture another test owns is a fixture that
  // moves without warning.
  await page.goto('/vendors');
  const plumber = `Dispatch Plumbing ${String(Date.now())}`;
  await page.getByLabel('Name').fill(plumber);
  await page.getByLabel('Trade').selectOption('plumbing');
  await page.getByLabel('Liability expires').fill('2028-09-30');
  await page.getByRole('button', { name: 'Add vendor' }).click();
  await expect(page.getByRole('row', { name: new RegExp(plumber) })).toBeVisible();

  await page.goto('/');
  await page.getByRole('button', { name: 'Emergency', exact: true }).click();
  await page.getByRole('button', { name: '998 Monmouth St', exact: true }).first().click();
  await page.getByRole('button', { name: /Water — burst pipe/ }).click();
  // The plumber above carries a live certificate; the proof line says so, and
  // names the date it read rather than a date somebody else wrote.
  await expect(page.getByText(/insured through Sep 30, 2028/).first()).toBeVisible();
  await page.getByRole('button', { name: 'Log with this vendor' }).first().click();
  await expect(page.getByText(/is on the maintenance board as an emergency/)).toBeVisible();
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await page.goto('/maintenance');
  await expect(page.getByRole('link', { name: /Water emergency/ }).first()).toBeVisible();
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

test('screening: the decision is recorded once and the FCRA checklist appears', async ({
  page,
}) => {
  // This walk OWNS its applicant and its screening. The resident and the
  // screening are arranged through the API because the web deliberately has
  // no "open screening" affordance yet: no read surface exposes resident ids
  // (noted to the API side). An applicant who is denied is, by definition,
  // not a resident on any lease — the panel lists by property.
  const properties = await (await page.request.get('http://localhost:8000/properties')).json();
  const propertyId = (properties as { id: string }[])[0]?.id;
  if (!propertyId) throw new Error('the portfolio walk runs first and creates a property');
  const applicant = `Avery Applicant ${String(Date.now())}`;
  const residentResponse = await page.request.post('http://localhost:8000/residents', {
    data: { full_name: applicant },
  });
  expect(residentResponse.ok()).toBe(true);
  const resident = (await residentResponse.json()) as { id: string };
  const screeningResponse = await page.request.post('http://localhost:8000/screening', {
    data: { resident_id: resident.id, property_id: propertyId },
  });
  expect(screeningResponse.ok()).toBe(true);

  // The lease is created through the UI, on the SAME property the screening
  // is on — picked by id, not by whatever order the select happens to hold.
  await page.goto('/leases');
  const unitLabel = `Screening Walk ${String(Date.now())}`;
  await page.locator('#ls-property').selectOption(propertyId);
  await page.getByLabel('Unit label').fill(unitLabel);
  await page.getByLabel('Starts').fill('2026-08-01');
  await page.getByLabel('Monthly rent').fill('1200.00');
  await page.getByRole('button', { name: 'Add lease & bill this month' }).click();
  await page
    .getByRole('row', { name: new RegExp(unitLabel) })
    .getByRole('link')
    .click();

  // The applicant's card, scoped: a long-lived database may hold others.
  const card = page.locator('.screening .card', { hasText: applicant });
  await expect(card.getByText('pending')).toBeVisible();
  await card.getByLabel('Decision').selectOption('denied');
  await card.getByLabel('Basis').fill('income below threshold');
  await card.getByLabel(/Based on a consumer report/).check();
  await card.getByRole('button', { name: 'Record the decision' }).click();

  // Honest transition proof: the form leaves, the record takes its place,
  // and the statute's checklist arrives with its stamps.
  await expect(card.getByRole('button', { name: 'Record the decision' })).toHaveCount(0);
  await expect(card.getByText(/income below threshold · based on a consumer report/)).toBeVisible();
  await expect(card.getByText('adverse-action notice owed')).toBeVisible();
  await expect(card.getByText('State the adverse action taken')).toBeVisible();
  await expect(card.getByText('15 U.S.C. 1681m(a)').first()).toBeVisible();

  // TODAY, not a literal, and computed in UTC because the database is.
  // `decided_on` defaults to the server's CURRENT_DATE the moment the
  // decision above is recorded, and `notice_follows_its_decision` (module
  // 018) refuses a notice dated before its own decision. A hard-coded date
  // therefore passes until the clock reaches it and fails forever after —
  // this walk broke at midnight UTC on 2026-08-29 having been green all day.
  const sentOn = new Date().toISOString().slice(0, 10);
  const [sentYear, sentMonth, sentDay] = sentOn.split('-');
  // Mirrors formatDate in src/lib/format.ts, which is a pure string
  // transform. Intl would be a second implementation whose output depends on
  // the runner's ICU data.
  const sentLabel = `${
    ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][
      Number(sentMonth) - 1
    ]
  } ${String(Number(sentDay))}, ${sentYear}`;
  await card.getByLabel('Sent on').fill(sentOn);
  await card.getByRole('button', { name: 'Record the notice' }).click();
  await expect(card.getByText(`notice sent ${sentLabel}`)).toBeVisible();
  await expect(card.getByText('State the adverse action taken')).toHaveCount(0);
});

test('the debt record: a mortgage, the engine split, and the counters move', async ({ page }) => {
  // This walk OWNS its note — a unique lender per run, all assertions scoped
  // to that lender's card, because a long-lived database accumulates notes.
  await page.goto('/');
  await page.getByText('998 Monmouth St, Newport, KY 41071').first().click();
  const lender = `Walk Federal ${String(Date.now())}`;
  await page.getByLabel('Lender').fill(lender);
  await page.getByLabel('Original principal').fill('190000.00');
  await page.getByLabel(/Annual rate/).fill('0.0625');
  await page.getByLabel('Term (months)').fill('360');
  await page.getByLabel('Originated').fill('2024-02-01');
  await page.getByRole('button', { name: 'Record the mortgage' }).click();

  const card = page.locator('.debt-panel .card', { hasText: lender });
  await expect(card.getByText(/0 payments — \$0\.00 principal, \$0\.00 interest/)).toBeVisible();
  await expect(card.getByText(/at 6\.250% over 360 months/)).toBeVisible();

  // The engine's split arrives as the suggestion, and the recorder is
  // pre-filled with it — the exact figures, not a rounding of them.
  await expect(card.getByText(/Next per the engine: month \d+/)).toBeVisible();
  const interest = card.getByLabel('Interest');
  await expect(interest).not.toHaveValue('');
  await card.getByRole('button', { name: 'Record the payment' }).click();
  await expect(card.getByText(/1 payments — /)).toBeVisible();

  // The schedule unfolds under its citation.
  await card.getByRole('button', { name: /The schedule/ }).click();
  await expect(card.getByText(/hestia_sim\.finance\.amortization/).first()).toBeVisible();
  await expect(card.getByText(/of interest over the remaining term/)).toBeVisible();
});

test('the mortgage split: one entry, one bank row, both land as the engine pair', async ({
  page,
}) => {
  // This walk OWNS its note, its bank account and its bank row — unique
  // names throughout, every assertion scoped to them.
  const stamp = String(Date.now());
  const lender = `Split Federal ${stamp}`;
  await page.goto('/');
  await page.getByText('998 Monmouth St, Newport, KY 41071').first().click();
  await expect(page.getByRole('heading', { name: '998 Monmouth St' })).toBeVisible();
  const propertyId = /property\/([0-9a-f-]+)/.exec(page.url())?.[1];
  if (!propertyId) throw new Error(`no property id in ${page.url()}`);
  await page.getByLabel('Lender').fill(lender);
  await page.getByLabel('Original principal').fill('200000.00');
  await page.getByLabel(/Annual rate/).fill('0.055');
  await page.getByLabel('Term (months)').fill('360');
  await page.getByLabel('Originated').fill('2025-01-01');
  await page.getByRole('button', { name: 'Record the mortgage' }).click();
  const noteCard = page.locator('.debt-panel .card', { hasText: lender });
  // The engine's scheduled payment, read off the record — the walk carries
  // the engine's own figure forward instead of hand-computing one.
  await expect(noteCard.getByText(/\/mo$/)).toBeVisible();
  const perMonth = await noteCard.getByText(/\/mo$/).textContent();
  const payment = /\$([\d,]+\.\d\d)\/mo/.exec(perMonth ?? '')?.[1]?.replaceAll(',', '');
  if (!payment) throw new Error(`no scheduled payment read from: ${perMonth ?? 'nothing'}`);

  // Entry surface: the transaction form recognizes a note payment and
  // routes it through the note — the register receives the linked pair.
  await page.goto('/transactions');
  await page.getByLabel('Date').fill('2026-08-05');
  await page.getByLabel('Category').selectOption('mortgage_interest');
  await page.locator('#tx-property').selectOption(propertyId);
  await expect(page.getByText('This is a note payment.')).toBeVisible();
  // A long-lived database holds notes from other runs: pick ours by name.
  const whichNote = page.getByLabel('Which note');
  if (await whichNote.isVisible().catch(() => false)) {
    const value = await whichNote.locator('option', { hasText: lender }).getAttribute('value');
    await whichNote.selectOption(value ?? '');
  }
  await page.getByRole('button', { name: `Record through ${lender}` }).click();
  const formPair = page.locator('tr', { hasText: `${lender} payment` }).first();
  await expect(formPair.getByText('Mortgage Payment')).toBeVisible();
  await expect(formPair.getByText(/interest −\$[\d,.]+ · principal −\$[\d,.]+/)).toBeVisible();

  // Bank surface: an account tied to the property, a statement row equal to
  // the scheduled payment, and the engine split offered at review.
  const entities = (await (await page.request.get('http://localhost:8000/entities')).json()) as {
    id: string;
  }[];
  const accountResponse = await page.request.post('http://localhost:8000/bank/accounts', {
    data: {
      entity_id: (entities[0] as { id: string }).id,
      property_id: propertyId,
      nickname: `Mortgage Ops ${stamp}`,
      kind: 'checking',
    },
  });
  expect(accountResponse.ok()).toBe(true);

  const description = `SPLIT FEDERAL MORTGAGE ${stamp}`;
  await page.goto('/transactions/import');
  await page.getByLabel('Bank account').selectOption({ label: `Mortgage Ops ${stamp}` });
  await page.getByLabel('Statement file (.csv / .ofx / .qfx)').setInputFiles({
    name: 'mortgage.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(`Date,Description,Amount\n2026-08-20,${description},-${payment}\n`),
  });
  await page.getByRole('button', { name: 'Import' }).click();
  const queueRow = page.locator('tr', { hasText: description });
  await expect(queueRow.getByText(/engine split: \$[\d,.]+ interest/)).toBeVisible();
  await queueRow.getByRole('button', { name: 'Accept as engine split' }).click();

  // The register folds the accepted row into one payment, split beneath.
  await page.goto('/transactions');
  const bankPair = page.locator('tr', { hasText: description }).first();
  await expect(bankPair.getByText('Mortgage Payment')).toBeVisible();
  await expect(bankPair.getByText(/interest −\$[\d,.]+ · principal −\$[\d,.]+/)).toBeVisible();
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
