/**
 * The typed API client. Every shape comes from the generated OpenAPI schema
 * (`gen:api` regenerates `api-schema.d.ts` from the committed contract), so
 * a served field the client dereferences is a compile error the moment the
 * contract changes — typed end to end, no hand-copied interfaces.
 */
import type { components, operations } from './api-schema';

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
export type ScheduleEReport = components['schemas']['ScheduleEReport'];
export type CashFlowReport = components['schemas']['CashFlowReport'];
export type RentRollRow = components['schemas']['RentRollRow'];
export type Financials = components['schemas']['Financials'];
export type CapexForecastOut = components['schemas']['CapexForecastOut'];
export type LeaseSummary = components['schemas']['LeaseSummary'];
export type LeaseDetail = components['schemas']['LeaseDetail'];
export type ChargeOut = components['schemas']['ChargeOut'];
export type LeaseIn = components['schemas']['LeaseIn'];
export type ReceiptIn = components['schemas']['ReceiptIn'];
export type ReceiptOut = components['schemas']['ReceiptOut'];
export type RenewalContextOut = components['schemas']['RenewalContextOut'];
export type CollectOut = components['schemas']['CollectOut'];
export type ScreeningOut = components['schemas']['ScreeningOut'];
export type ScreeningIn = components['schemas']['ScreeningIn'];
export type DecisionIn = components['schemas']['DecisionIn'];
export type NoticeIn = components['schemas']['NoticeIn'];
export type DocumentSummary = components['schemas']['DocumentSummary'];
export type DocumentDetail = components['schemas']['DocumentDetail'];
export type DocumentField = components['schemas']['FieldOut'];
export type ApplySuggestion = components['schemas']['ApplySuggestion'];
export type DocumentReviewIn = components['schemas']['ReviewIn'];
export type DocumentApplyIn = components['schemas']['ApplyIn'];
export type DocumentApplyResult = components['schemas']['ApplyResult'];
// The vocabularies themselves come from the contract, so a hand-kept option
// list in a form can never drift from what the server accepts.
export type DocumentKind = components['schemas']['Body_upload_document_documents_post']['kind'];
export type VendorOut = components['schemas']['VendorOut'];
export type VendorIn = components['schemas']['VendorIn'];
export type WorkOrderOut = components['schemas']['WorkOrderOut'];
export type WorkOrderIn = components['schemas']['WorkOrderIn'];
export type WorkOrderCost = components['schemas']['CostOut'];
export type TransitionIn = components['schemas']['TransitionIn'];
export type CompletionIn = components['schemas']['CompletionIn'];
export type CompletionOut = components['schemas']['CompletionOut'];
export type CostLinkIn = components['schemas']['CostLinkIn'];
export type WorkOrderStatus = WorkOrderOut['status'];
export type WorkOrderPriority = WorkOrderIn['priority'];
export type VendorTrade = VendorIn['trade'];

export type DocumentStatus = NonNullable<
  NonNullable<operations['list_documents_documents_get']['parameters']['query']>['status']
>;

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
  listVendors: (entityId?: string) =>
    request<VendorOut[]>(`/vendors${entityId ? `?entity_id=${entityId}` : ''}`),
  readVendor: (vendorId: string) => request<VendorOut>(`/vendors/${vendorId}`),
  createVendor: (body: VendorIn) =>
    request<VendorOut>('/vendors', { method: 'POST', body: JSON.stringify(body) }),
  listWorkOrders: (params?: { propertyId?: string; openOnly?: boolean }) => {
    const query = new URLSearchParams();
    if (params?.propertyId) query.set('property_id', params.propertyId);
    if (params?.openOnly) query.set('open_only', 'true');
    const suffix = query.size > 0 ? `?${query.toString()}` : '';
    return request<WorkOrderOut[]>(`/work-orders${suffix}`);
  },
  readWorkOrder: (workOrderId: string) => request<WorkOrderOut>(`/work-orders/${workOrderId}`),
  createWorkOrder: (body: WorkOrderIn) =>
    request<WorkOrderOut>('/work-orders', { method: 'POST', body: JSON.stringify(body) }),
  transitionWorkOrder: (workOrderId: string, body: TransitionIn) =>
    request<WorkOrderOut>(`/work-orders/${workOrderId}/transitions`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  completeWorkOrder: (workOrderId: string, body: CompletionIn) =>
    request<CompletionOut>(`/work-orders/${workOrderId}/complete`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  addWorkOrderCost: (workOrderId: string, body: CostLinkIn) =>
    request<WorkOrderOut>(`/work-orders/${workOrderId}/costs`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  listDocuments: (status?: DocumentStatus) =>
    request<DocumentSummary[]>(`/documents${status ? `?status=${status}` : ''}`),
  documentDetail: (documentId: string) => request<DocumentDetail>(`/documents/${documentId}`),
  documentContentUrl: (documentId: string) => `${apiBase()}/documents/${documentId}/content`,
  reviewDocumentField: (documentId: string, body: DocumentReviewIn) =>
    request<DocumentDetail>(`/documents/${documentId}/review`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  reExtractDocument: (documentId: string) =>
    request<DocumentDetail>(`/documents/${documentId}/extract`, { method: 'POST' }),
  applyDocument: (documentId: string, body: DocumentApplyIn) =>
    request<DocumentApplyResult>(`/documents/${documentId}/apply`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  uploadDocument: async (
    kind: DocumentKind,
    propertyId: string,
    file: File,
  ): Promise<DocumentDetail> => {
    const form = new FormData();
    form.append('file', file);
    form.append('kind', kind);
    form.append('property_id', propertyId);
    const response = await fetch(`${apiBase()}/documents`, {
      method: 'POST',
      body: form, // multipart: the browser sets the boundary header itself
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
    return (await response.json()) as DocumentDetail;
  },
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
  scheduleE: (propertyId: string, taxYear: number) =>
    request<ScheduleEReport>(
      `/properties/${propertyId}/reports/schedule-e?tax_year=${String(taxYear)}`,
    ),
  cashFlow: (propertyId: string, year: number) =>
    request<CashFlowReport>(`/properties/${propertyId}/reports/cash-flow?year=${String(year)}`),
  rentRoll: () => request<RentRollRow[]>('/reports/rent-roll'),
  financials: (propertyId: string) => request<Financials>(`/properties/${propertyId}/financials`),
  capexForecast: (propertyId: string) =>
    request<CapexForecastOut>(`/properties/${propertyId}/capex-forecast`),
  listLeases: () => request<LeaseSummary[]>('/leases'),
  leaseDetail: (leaseId: string) => request<LeaseDetail>(`/leases/${leaseId}`),
  createUnit: (body: { property_id: string; label: string; market_rent?: string | null }) =>
    request<{ id: string }>('/units', { method: 'POST', body: JSON.stringify(body) }),
  createResident: (body: { full_name: string; email?: string | null }) =>
    request<{ id: string }>('/residents', { method: 'POST', body: JSON.stringify(body) }),
  createLease: (body: LeaseIn) =>
    request<{ id: string }>('/leases', { method: 'POST', body: JSON.stringify(body) }),
  sweepRentCharges: () =>
    request<{ charges_created: number }>('/sweep/rent-charges', {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  recordLeaseReceipt: (leaseId: string, body: ReceiptIn) =>
    request<ReceiptOut>(`/leases/${leaseId}/receipts`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  renewalContext: (leaseId: string) =>
    request<RenewalContextOut>(`/leases/${leaseId}/renewal-context`),
  recordRenewalOffer: (leaseId: string, body: { offered_on: string; offered_rent: string }) =>
    request<{ id: string }>(`/leases/${leaseId}/renewals`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  collectRent: (leaseId: string) =>
    request<CollectOut>(`/leases/${leaseId}/collect`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  listScreenings: (params?: { propertyId?: string; residentId?: string; noticeOwed?: boolean }) => {
    const query = new URLSearchParams();
    if (params?.propertyId) query.set('property_id', params.propertyId);
    if (params?.residentId) query.set('resident_id', params.residentId);
    if (params?.noticeOwed) query.set('notice_owed', 'true');
    const suffix = query.size > 0 ? `?${query.toString()}` : '';
    return request<ScreeningOut[]>(`/screening${suffix}`);
  },
  openScreening: (body: ScreeningIn) =>
    request<ScreeningOut>('/screening', { method: 'POST', body: JSON.stringify(body) }),
  readScreening: (screeningId: string) => request<ScreeningOut>(`/screening/${screeningId}`),
  decideScreening: (screeningId: string, body: DecisionIn) =>
    request<ScreeningOut>(`/screening/${screeningId}/decision`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  recordAdverseAction: (screeningId: string, body: NoticeIn) =>
    request<ScreeningOut>(`/screening/${screeningId}/adverse-action`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
};
