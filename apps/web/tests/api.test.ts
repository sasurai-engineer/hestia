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
