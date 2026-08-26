/**
 * The typed API client. Every shape comes from the generated OpenAPI schema
 * (`gen:api` regenerates `api-schema.d.ts` from the committed contract), so
 * a served field the client dereferences is a compile error the moment the
 * contract changes — typed end to end, no hand-copied interfaces.
 */
import type { components } from './api-schema';

export type EntityOut = components['schemas']['EntityOut'];
export type PropertyOut = components['schemas']['PropertyOut'];
export type PropertySummary = components['schemas']['PropertySummary'];
export type DossierView = components['schemas']['DossierView'];
export type DossierOut = components['schemas']['DossierOut'];
export type DossierStep = components['schemas']['DossierStepOut'];
export type DeadlineOut = components['schemas']['DeadlineOut'];
export type CoverageReport = components['schemas']['CoverageReport'];
export type PropertyIn = components['schemas']['PropertyIn'];
export type EntityIn = components['schemas']['EntityIn'];
export type ComponentOut = components['schemas']['ComponentOut'];
export type DefectOut = components['schemas']['DefectOut'];
export type HazardOut = components['schemas']['HazardOut'];
export type ChainLink = components['schemas']['ChainLink'];
export type LedgerEventOut = components['schemas']['LedgerEventOut'];
export type LedgerRegister = components['schemas']['LedgerRegister'];
export type LedgerEntryIn = components['schemas']['LedgerEntryIn'];
export type BankAccountOut = components['schemas']['BankAccountOut'];
export type BankAccountIn = components['schemas']['BankAccountIn'];
export type ImportSummary = components['schemas']['ImportSummary'];
export type StagedTransaction = components['schemas']['StagedTransaction'];
export type AcceptIn = components['schemas']['AcceptIn'];

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

export const apiBase = (): string =>
  // biome-ignore lint/complexity/useLiteralKeys: tsconfig's noPropertyAccessFromIndexSignature requires bracket access on process.env
  process.env['NEXT_PUBLIC_HESTIA_API_URL'] ?? 'http://localhost:8000';

const request = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(`${apiBase()}${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    let detail = `HTTP ${String(response.status)}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      // a non-JSON error body keeps the status-line message
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) {
    return undefined as T; // a 204 has no body to parse
  }
  return (await response.json()) as T;
};

export const api = {
  listEntities: () => request<EntityOut[]>('/entities'),
  createEntity: (body: EntityIn) =>
    request<EntityOut>('/entities', { method: 'POST', body: JSON.stringify(body) }),
  listProperties: () => request<PropertySummary[]>('/properties'),
  createProperty: (body: PropertyIn) =>
    request<PropertyOut>('/properties', { method: 'POST', body: JSON.stringify(body) }),
  readDossier: (propertyId: string) => request<DossierView>(`/properties/${propertyId}/dossier`),
  assembleDossier: (propertyId: string) =>
    request<DossierOut>(`/properties/${propertyId}/dossier`, { method: 'POST' }),
  listDeadlines: (params?: { dueBefore?: string }) => {
    const query = params?.dueBefore ? `?due_before=${params.dueBefore}` : '';
    return request<DeadlineOut[]>(`/deadlines${query}`);
  },
  coverage: () => request<CoverageReport>('/coverage/jurisdictions'),
  ledgerRegister: (params?: { propertyId?: string; category?: string }) => {
    const query = new URLSearchParams();
    if (params?.propertyId) query.set('property_id', params.propertyId);
    if (params?.category) query.set('category', params.category);
    const suffix = query.size > 0 ? `?${query.toString()}` : '';
    return request<LedgerRegister>(`/ledger${suffix}`);
  },
  appendLedger: (body: LedgerEntryIn) =>
    request<LedgerEventOut>('/ledger', { method: 'POST', body: JSON.stringify(body) }),
  reverseLedger: (eventUuid: string) =>
    request<{ reversal: LedgerEventOut }>(`/ledger/${eventUuid}/reverse`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  listBankAccounts: () => request<BankAccountOut[]>('/bank/accounts'),
  createBankAccount: (body: BankAccountIn) =>
    request<BankAccountOut>('/bank/accounts', { method: 'POST', body: JSON.stringify(body) }),
  importStatement: async (accountId: string, file: File): Promise<ImportSummary> => {
    const form = new FormData();
    form.append('file', file);
    const response = await fetch(`${apiBase()}/bank/accounts/${accountId}/imports`, {
      method: 'POST',
      body: form, // multipart: the browser sets the boundary header itself
    });
    if (!response.ok) {
      let detail = `HTTP ${String(response.status)}`;
      try {
        const body = (await response.json()) as { detail?: unknown };
        if (typeof body.detail === 'string') detail = body.detail;
      } catch {
        // keep the status line
      }
      throw new ApiError(response.status, detail);
    }
    return (await response.json()) as ImportSummary;
  },
  reviewQueue: (batchId: string, disposition?: string) => {
    const query = disposition ? `?disposition=${disposition}` : '';
    return request<StagedTransaction[]>(`/bank/imports/${batchId}/transactions${query}`);
  },
  acceptBankTransaction: (txnId: string, body: AcceptIn) =>
    request<LedgerEventOut[]>(`/bank/transactions/${txnId}/accept`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  excludeBankTransaction: (txnId: string) =>
    request<void>(`/bank/transactions/${txnId}/exclude`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
};
