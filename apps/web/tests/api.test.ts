import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, apiBase } from '../src/lib/api';

// A FACTORY per call: a Response body is single-read, so a mock that
// resolves one shared Response poisons every request after the first.
const jsonResponse = (status: number, body: unknown) => (): Promise<Response> =>
  Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    }),
  );

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe('the API client', () => {
  it('defaults to the local API and honors the public env override', () => {
    expect(apiBase()).toBe('http://localhost:8000');
    vi.stubEnv('NEXT_PUBLIC_HESTIA_API_URL', 'https://hestia.example');
    expect(apiBase()).toBe('https://hestia.example');
  });

  it('performs typed reads and writes against the contract paths', async () => {
    const fetchMock = vi.fn().mockImplementation(jsonResponse(200, []));
    vi.stubGlobal('fetch', fetchMock);
    await api.listProperties();
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/properties',
      expect.objectContaining({ headers: expect.anything() }),
    );
    await api.listEntities();
    await api.listDeadlines();
    await api.listDeadlines({ dueBefore: '2027-01-01' });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/deadlines?due_before=2027-01-01',
      expect.anything(),
    );
    await api.coverage();
    await api.readDossier('abc');
    await api.assembleDossier('abc');
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/properties/abc/dossier',
      expect.objectContaining({ method: 'POST' }),
    );
    await api.ledgerRegister();
    expect(fetchMock).toHaveBeenLastCalledWith('http://localhost:8000/ledger', expect.anything());
    await api.ledgerRegister({ propertyId: 'p1', category: 'repairs' });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/ledger?property_id=p1&category=repairs',
      expect.anything(),
    );
    await api.appendLedger({
      occurred_on: '2026-08-01',
      category: 'rent',
      amount: '1450.00',
      property_id: 'p1',
    });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/ledger',
      expect.objectContaining({ method: 'POST' }),
    );
    await api.reverseLedger('e1');
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/ledger/e1/reverse',
      expect.objectContaining({ method: 'POST', body: '{}' }),
    );
    await api.listBankAccounts();
    await api.createBankAccount({ entity_id: 'e', nickname: 'Op', kind: 'checking' });
    await api.reviewQueue('b1');
    await api.reviewQueue('b1', 'pending');
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/bank/imports/b1/transactions?disposition=pending',
      expect.anything(),
    );
    await api.acceptBankTransaction('t1', { category: 'utilities' });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/bank/transactions/t1/accept',
      expect.objectContaining({ method: 'POST' }),
    );
    await api.rentRoll();
    await api.scheduleE('p1', 2026);
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/properties/p1/reports/schedule-e?tax_year=2026',
      expect.anything(),
    );
    await api.cashFlow('p1', 2026);
    await api.financials('p1');
    await api.capexForecast('p1');
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/properties/p1/capex-forecast',
      expect.anything(),
    );
    await api.listLeases();
    await api.leaseDetail('l1');
    await api.createUnit({ property_id: 'p1', label: 'A' });
    await api.createResident({ full_name: 'R' });
    await api.createLease({ unit_id: 'u1', starts_on: '2026-01-01', rent: '1450.00' });
    await api.sweepRentCharges();
    await api.recordLeaseReceipt('l1', { occurred_on: '2026-08-01', amount: '1450.00' });
    await api.renewalContext('l1');
    await api.recordRenewalOffer('l1', { offered_on: '2026-09-01', offered_rent: '1500.00' });
    await api.collectRent('l1');
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/leases/l1/collect',
      expect.objectContaining({ method: 'POST' }),
    );
    await api.createEntity({ name: 'X', kind: 'llc' });
    await api.createProperty({
      entity_id: 'e',
      label: 'L',
      street_1: 'S',
      city: 'C',
      state: 'KY',
      postal_code: '41071',
      kind: 'single_family',
    });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/properties',
      expect.objectContaining({ method: 'POST', body: expect.stringContaining('"KY"') }),
    );
  });

  it('surfaces the API detail on a typed error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(jsonResponse(404, { detail: 'property not found' })),
    );
    const failure = api.readDossier('missing');
    await expect(failure).rejects.toBeInstanceOf(ApiError);
    await expect(api.readDossier('missing')).rejects.toMatchObject({
      status: 404,
      message: 'property not found',
    });
  });

  it('imports a statement as multipart and surfaces its errors', async () => {
    const fetchMock = vi.fn().mockImplementation(
      jsonResponse(201, {
        batch_id: 'b1',
        format: 'csv',
        staged: 3,
        duplicates: 0,
        suggested: 2,
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const file = new File(['Date,Description,Amount\n'], 'aug.csv', { type: 'text/csv' });
    const summary = await api.importStatement('a1', file);
    expect(summary.staged).toBe(3);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://localhost:8000/bank/accounts/a1/imports');
    expect(init.body).toBeInstanceOf(FormData);
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockImplementation(jsonResponse(409, { detail: 'this exact file was already imported' })),
    );
    await expect(api.importStatement('a1', file)).rejects.toMatchObject({
      status: 409,
      message: 'this exact file was already imported',
    });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => Promise.resolve(new Response('boom', { status: 502 }))),
    );
    await expect(api.importStatement('a1', file)).rejects.toMatchObject({ message: 'HTTP 502' });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(jsonResponse(500, { detail: { odd: true } })),
    );
    await expect(api.importStatement('a1', file)).rejects.toMatchObject({ message: 'HTTP 500' });
  });

  it('walks the maintenance paths against the contract', async () => {
    const fetchMock = vi.fn().mockImplementation(jsonResponse(200, []));
    vi.stubGlobal('fetch', fetchMock);
    await api.listVendors();
    expect(fetchMock).toHaveBeenLastCalledWith('http://localhost:8000/vendors', expect.anything());
    await api.listVendors('e1');
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/vendors?entity_id=e1',
      expect.anything(),
    );
    await api.readVendor('v1');
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/vendors/v1',
      expect.anything(),
    );
    await api.createVendor({
      entity_id: 'e1',
      name: 'Licking Valley Plumbing',
      trade: 'plumbing',
      phone: null,
      email: null,
      license_number: null,
      license_expires_on: null,
      insurer: null,
      liability_expires_on: null,
      workers_comp_expires_on: null,
      w9_on_file: false,
      is_1099_reportable: true,
      notes: null,
    });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/vendors',
      expect.objectContaining({ method: 'POST' }),
    );
    await api.listWorkOrders();
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/work-orders',
      expect.anything(),
    );
    await api.listWorkOrders({ propertyId: 'p1', openOnly: true });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/work-orders?property_id=p1&open_only=true',
      expect.anything(),
    );
    await api.readWorkOrder('w1');
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/work-orders/w1',
      expect.anything(),
    );
    await api.createWorkOrder({
      property_id: 'p1',
      summary: 'No hot water',
      priority: 'urgent',
      reported_by: 'owner',
    });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/work-orders',
      expect.objectContaining({ method: 'POST' }),
    );
    await api.transitionWorkOrder('w1', {
      status: 'triaged',
      scheduled_for: null,
      vendor_id: null,
      cancelled_reason: null,
    });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/work-orders/w1/transitions',
      expect.objectContaining({ method: 'POST' }),
    );
    await api.completeWorkOrder('w1', {
      completed_on: '2026-08-27',
      resolution: 'replaced',
      resolution_note: null,
      cost: null,
      replacement: null,
    });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/work-orders/w1/complete',
      expect.objectContaining({ method: 'POST' }),
    );
    await api.addWorkOrderCost('w1', {
      cost: null,
      ledger_event_uuid: 'e-uuid',
      relation: 'materials',
    });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/work-orders/w1/costs',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('walks the document loop against the contract paths', async () => {
    const fetchMock = vi.fn().mockImplementation(jsonResponse(200, []));
    vi.stubGlobal('fetch', fetchMock);
    await api.listDocuments();
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/documents',
      expect.anything(),
    );
    await api.listDocuments('needs_review');
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/documents?status=needs_review',
      expect.anything(),
    );
    await api.documentDetail('d1');
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/documents/d1',
      expect.anything(),
    );
    await api.reviewDocumentField('d1', {
      field_path: 'settlement.sale_price',
      action: 'accept',
      value: null,
    });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/documents/d1/review',
      expect.objectContaining({ method: 'POST' }),
    );
    await api.reExtractDocument('d1');
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/documents/d1/extract',
      expect.objectContaining({ method: 'POST' }),
    );
    await api.applyDocument('d1', {
      land_value: '35490.56',
      personal_property: '0.00',
      method: 'assessor ratio',
    });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/documents/d1/apply',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(api.documentContentUrl('d1')).toBe('http://localhost:8000/documents/d1/content');
  });

  it('walks the screening paths against the contract', async () => {
    const fetchMock = vi.fn().mockImplementation(jsonResponse(200, []));
    vi.stubGlobal('fetch', fetchMock);
    await api.listScreenings();
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/screening',
      expect.anything(),
    );
    await api.listScreenings({ propertyId: 'p1' });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/screening?property_id=p1',
      expect.anything(),
    );
    await api.listScreenings({ residentId: 'r1', noticeOwed: true });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/screening?resident_id=r1&notice_owed=true',
      expect.anything(),
    );
    await api.openScreening({ resident_id: 'r1', property_id: 'p1' });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/screening',
      expect.objectContaining({ method: 'POST' }),
    );
    await api.readScreening('s1');
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/screening/s1',
      expect.anything(),
    );
    await api.decideScreening('s1', {
      decision: 'denied',
      decided_on: '2026-08-28',
      decision_basis: 'income below threshold',
      based_on_consumer_report: true,
    });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/screening/s1/decision',
      expect.objectContaining({ method: 'POST' }),
    );
    await api.recordAdverseAction('s1', { sent_on: '2026-08-28' });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/screening/s1/adverse-action',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('walks the debt paths against the contract', async () => {
    const fetchMock = vi.fn().mockImplementation(jsonResponse(200, []));
    vi.stubGlobal('fetch', fetchMock);
    await api.listDebts();
    expect(fetchMock).toHaveBeenLastCalledWith('http://localhost:8000/debts', expect.anything());
    await api.listDebts({ propertyId: 'p1', includePaidOff: true });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/debts?property_id=p1&include_paid_off=true',
      expect.anything(),
    );
    await api.createDebt({
      property_id: 'p1',
      lender: 'First Federal',
      original_principal: '190000.00',
      interest_rate: '0.0625',
      term_months: 360,
      originated_on: '2024-02-01',
    });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/debts',
      expect.objectContaining({ method: 'POST' }),
    );
    await api.readDebt('n1');
    expect(fetchMock).toHaveBeenLastCalledWith('http://localhost:8000/debts/n1', expect.anything());
    await api.debtSchedule('n1');
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/debts/n1/schedule',
      expect.anything(),
    );
    await api.debtSchedule('n1', '2026-08-28');
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/debts/n1/schedule?as_of=2026-08-28',
      expect.anything(),
    );
    await api.recordDebtPayment('n1', {
      paid_on: '2026-08-28',
      extra_principal: '0',
      escrow: '0',
      post_to_ledger: true,
    });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/debts/n1/payments',
      expect.objectContaining({ method: 'POST' }),
    );
    await api.payoffDebt('n1', { paid_off_on: '2026-08-28' });
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/debts/n1/payoff',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('uploads documents as multipart and surfaces refusals', async () => {
    const file = new File(['%PDF fake'], 'closing.pdf', { type: 'application/pdf' });
    const fetchMock = vi
      .fn()
      .mockImplementation(jsonResponse(201, { id: 'd9', status: 'extracted' }));
    vi.stubGlobal('fetch', fetchMock);
    const detail = await api.uploadDocument('settlement_statement', 'p1', file);
    expect(detail.id).toBe('d9');
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://localhost:8000/documents');
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get('kind')).toBe('settlement_statement');
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(jsonResponse(409, { detail: 'these exact bytes exist' })),
    );
    await expect(api.uploadDocument('settlement_statement', 'p1', file)).rejects.toMatchObject({
      status: 409,
      message: 'these exact bytes exist',
    });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => Promise.resolve(new Response('boom', { status: 502 }))),
    );
    await expect(api.uploadDocument('settlement_statement', 'p1', file)).rejects.toMatchObject({
      message: 'HTTP 502',
    });
    vi.stubGlobal('fetch', vi.fn().mockImplementation(jsonResponse(500, { detail: { odd: 1 } })));
    await expect(api.uploadDocument('settlement_statement', 'p1', file)).rejects.toMatchObject({
      message: 'HTTP 500',
    });
  });

  it('treats a 204 as a bodiless success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => Promise.resolve(new Response(null, { status: 204 }))),
    );
    await expect(api.excludeBankTransaction('t1')).resolves.toBeUndefined();
  });

  it('falls back to the status line when the error body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockImplementation(() =>
          Promise.resolve(new Response('gateway exploded', { status: 502 })),
        ),
    );
    await expect(api.listProperties()).rejects.toMatchObject({ message: 'HTTP 502' });
  });

  it('keeps the status line when the error body is JSON without a detail string', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(jsonResponse(500, { detail: { odd: true } })),
    );
    await expect(api.listProperties()).rejects.toMatchObject({ message: 'HTTP 500' });
  });
});
