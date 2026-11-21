/**
 * API client.
 *
 * One place that knows how to talk to the backend: URL construction, error
 * normalisation and the correlation header. Components never call fetch.
 */

import type {
  Account,
  AppConfig,
  BaPackage,
  BusinessRule,
  DemoButton,
  ExceptionsOverview,
  FailureDefinition,
  FailureInjection,
  Investigation,
  MessageCatalogueItem,
  MtMxRow,
  Paged,
  PaymentCreateInput,
  PaymentDetail,
  PaymentEvent,
  PaymentMessage,
  PaymentSummary,
  ReconciliationRecord,
  Scenario,
  ScenarioExecution,
  ScenarioRunResult,
  Scheme,
  SearchHit,
  Statistics,
  StatementEntry,
  TestCase,
} from './types'

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api/v1'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail: unknown
  readonly requestId: string | null

  constructor(status: number, code: string, message: string, detail: unknown, requestId: string | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
    this.requestId = requestId
  }

  /** Field-level messages, when the backend rejected the request body. */
  get fieldErrors(): { field: string; message: string }[] {
    if (!Array.isArray(this.detail)) return []
    return (this.detail as { field?: string; message?: string }[])
      .filter((d) => d && typeof d.message === 'string')
      .map((d) => ({ field: d.field ?? '', message: d.message as string }))
  }

  get allowedTransitions(): string[] {
    const detail = this.detail as { allowedTransitions?: string[] } | null
    return detail?.allowedTransitions ?? []
  }
}

type Query = Record<string, string | number | boolean | undefined | null | (string | number)[]>

function buildUrl(path: string, query?: Query): string {
  const url = `${BASE}${path}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      for (const item of value) params.append(key, String(item))
    } else {
      params.append(key, String(value))
    }
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

async function request<T>(
  method: string,
  path: string,
  options: { query?: Query; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const headers: Record<string, string> = { accept: 'application/json' }
  if (options.body !== undefined) headers['content-type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(buildUrl(path, options.query), {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    })
  } catch (cause) {
    if ((cause as Error)?.name === 'AbortError') throw cause
    throw new ApiError(
      0,
      'NETWORK_ERROR',
      'The simulator API could not be reached. Is the backend running on port 8000?',
      null,
      null,
    )
  }

  const requestId = response.headers.get('x-request-id')
  if (response.status === 204) return undefined as T

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = text
    }
  }

  if (!response.ok) {
    const envelope = payload as { error?: { code?: string; message?: string; detail?: unknown } } | null
    const error = envelope?.error
    throw new ApiError(
      response.status,
      error?.code ?? `HTTP_${response.status}`,
      error?.message ?? `Request failed with status ${response.status}`,
      error?.detail ?? null,
      requestId,
    )
  }
  return payload as T
}

const get = <T>(path: string, query?: Query, signal?: AbortSignal) =>
  request<T>('GET', path, { query, signal })
const post = <T>(path: string, body?: unknown, query?: Query) =>
  request<T>('POST', path, { body, query })
const patch = <T>(path: string, body?: unknown) => request<T>('PATCH', path, { body })
const del = <T>(path: string) => request<T>('DELETE', path)

export interface PaymentListQuery {
  page?: number
  pageSize?: number
  status?: string[]
  scheme?: string[]
  currency?: string[]
  query?: string
  failuresOnly?: boolean
  amountMin?: string
  amountMax?: string
  sort?: string
  direction?: string
}

export const api = {
  // --- meta ---
  health: () => request<{ status: string; database: string }>('GET', '', {}).catch(() => null),
  config: (signal?: AbortSignal) => get<AppConfig>('/config', undefined, signal),
  enums: () => get<Record<string, string[]>>('/enums'),

  // --- payments ---
  listPayments: (query: PaymentListQuery = {}, signal?: AbortSignal) =>
    get<Paged<PaymentSummary>>('/payments', query as Query, signal),
  statistics: (signal?: AbortSignal) => get<Statistics>('/payments/statistics', undefined, signal),
  getPayment: (reference: string, signal?: AbortSignal) =>
    get<PaymentDetail>(`/payments/${encodeURIComponent(reference)}`, undefined, signal),
  createPayment: (body: PaymentCreateInput) => post<PaymentDetail>('/payments', body),
  executePayment: (
    reference: string,
    body: { processingMode?: 'IMMEDIATE' | 'SIMULATED'; waitForCompletion?: boolean; waitTimeoutSeconds?: number } = {},
  ) => post<PaymentDetail>(`/payments/${encodeURIComponent(reference)}/execute`, body),
  timeline: (reference: string, signal?: AbortSignal) =>
    get<{
      reference: string
      status: string
      previousStatus: string | null
      allowedTransitions: string[]
      scheme: Scheme
      stages: PaymentDetail['stages']
      failureSummary: string | null
      pendingJobs: { jobType: string; dueAt: string; status: string }[]
    }>(`/payments/${encodeURIComponent(reference)}/timeline`, undefined, signal),
  paymentMessages: (reference: string, signal?: AbortSignal) =>
    get<{ reference: string; items: PaymentMessage[] }>(
      `/payments/${encodeURIComponent(reference)}/messages`,
      undefined,
      signal,
    ),
  paymentEvents: (reference: string, query: Query = {}, signal?: AbortSignal) =>
    get<{ reference: string; items: PaymentEvent[] }>(
      `/payments/${encodeURIComponent(reference)}/events`,
      query,
      signal,
    ),
  paymentAccounting: (reference: string, signal?: AbortSignal) =>
    get<{
      reference: string
      entries: PaymentDetail['accountingEntries']
      statementEntries: StatementEntry[]
      totals: { debits: string; credits: string; balanced: boolean; currency: string }
    }>(`/payments/${encodeURIComponent(reference)}/accounting`, undefined, signal),
  paymentMtMx: (reference: string, signal?: AbortSignal) =>
    get<{ reference: string; scheme: string; rows: MtMxRow[]; note: string }>(
      `/payments/${encodeURIComponent(reference)}/mt-mx`,
      undefined,
      signal,
    ),
  paymentTracking: (reference: string, signal?: AbortSignal) =>
    get<{
      reference: string
      supported: boolean
      uetr?: string | null
      status?: string
      note?: string
      simulationNote?: string
      events: { at: string; agent: string; event: string; description: string; severity: string }[]
    }>(`/payments/${encodeURIComponent(reference)}/tracking`, undefined, signal),
  reconcilePayment: (reference: string) =>
    post<ReconciliationRecord>(`/payments/${encodeURIComponent(reference)}/reconcile`, {}),
  retryPayment: (reference: string, body: { reason: string; processingMode?: 'IMMEDIATE' | 'SIMULATED' }) =>
    post<PaymentDetail>(`/payments/${encodeURIComponent(reference)}/retry`, body),
  resolveTimeout: (reference: string, body: { accepted: boolean; reasonCode?: string | null }) =>
    post<PaymentDetail>(`/payments/${encodeURIComponent(reference)}/resolve-timeout`, body),
  cancelPayment: (reference: string, body: { reasonCode: string; narrative?: string }) =>
    post<PaymentDetail>(`/payments/${encodeURIComponent(reference)}/cancel`, body),
  returnPayment: (reference: string, body: { reasonCode: string; narrative?: string }) =>
    post<PaymentDetail>(`/payments/${encodeURIComponent(reference)}/return`, body),

  // --- failure injection ---
  failureCatalogue: (signal?: AbortSignal) =>
    get<{ items: FailureDefinition[]; byCategory: Record<string, FailureDefinition[]>; note: string }>(
      '/failure-injections',
      undefined,
      signal,
    ),
  paymentFailures: (reference: string) =>
    get<{ reference: string; items: FailureInjection[] }>(
      `/payments/${encodeURIComponent(reference)}/failures`,
    ),
  injectFailure: (reference: string, body: { code: string; parameters?: Record<string, unknown> }) =>
    post<FailureInjection>(`/payments/${encodeURIComponent(reference)}/failures`, body),
  removeFailure: (reference: string, id: number) =>
    del<FailureInjection>(`/payments/${encodeURIComponent(reference)}/failures/${id}`),

  // --- operations ---
  investigations: (query: Query = {}, signal?: AbortSignal) =>
    get<Paged<Investigation> & { byReason: Record<string, number> }>(
      '/investigations',
      query,
      signal,
    ),
  investigation: (reference: string, signal?: AbortSignal) =>
    get<Investigation>(`/investigations/${encodeURIComponent(reference)}`, undefined, signal),
  addInvestigationAction: (
    reference: string,
    body: { action: string; note: string; status?: string | null },
  ) => post<Investigation>(`/investigations/${encodeURIComponent(reference)}/actions`, body),
  resolveInvestigation: (reference: string, body: { resolution: string; status?: string }) =>
    post<Investigation>(`/investigations/${encodeURIComponent(reference)}/resolve`, body),
  exceptions: (signal?: AbortSignal) => get<ExceptionsOverview>('/exceptions', undefined, signal),
  reconciliation: (query: Query = {}, signal?: AbortSignal) =>
    get<
      Paged<ReconciliationRecord> & {
        byStatus: Record<string, number>
        classifications: {
          status: string
          isBreak: boolean
          probableCause: string
          recommendedAction: string
        }[]
      }
    >('/reconciliation', query, signal),
  reconciliationRecord: (reference: string, signal?: AbortSignal) =>
    get<ReconciliationRecord>(`/reconciliation/${encodeURIComponent(reference)}`, undefined, signal),
  unmatchedStatements: (signal?: AbortSignal) =>
    get<{ items: StatementEntry[]; total: number }>('/reconciliation/unmatched', undefined, signal),
  statementEntries: (query: Query = {}, signal?: AbortSignal) =>
    get<Paged<StatementEntry>>('/reconciliation/statement-entries', query, signal),

  // --- system ---
  schemes: (signal?: AbortSignal) =>
    get<{ items: Scheme[]; default: string }>('/schemes', undefined, signal),
  scheme: (code: string, signal?: AbortSignal) =>
    get<Scheme>(`/schemes/${encodeURIComponent(code)}`, undefined, signal),
  rules: (query: Query = {}, signal?: AbortSignal) =>
    get<{
      items: BusinessRule[]
      categories: string[]
      stages: string[]
      severities: string[]
      total: number
      disabledCount: number
    }>('/rules', query, signal),
  rule: (ruleId: string, signal?: AbortSignal) =>
    get<BusinessRule>(`/rules/${encodeURIComponent(ruleId)}`, undefined, signal),
  toggleRule: (ruleId: string, body: { enabled: boolean; reason?: string }) =>
    patch<BusinessRule>(`/rules/${encodeURIComponent(ruleId)}`, body),
  stateMachine: (signal?: AbortSignal) =>
    get<{
      transitions: { from: string; to: string[]; isTerminal: boolean; isFailure: boolean }[]
      statuses: { status: string; isTerminal: boolean; isFailure: boolean }[]
      stages: { stageKey: string; sequence: number; businessLabel: string; technicalLabel: string }[]
    }>('/state-machine', undefined, signal),
  events: (query: Query = {}, signal?: AbortSignal) =>
    get<Paged<PaymentEvent> & { filters: Record<string, string[]> }>('/events', query, signal),
  audit: (query: Query = {}, signal?: AbortSignal) =>
    get<
      Paged<{
        id: number
        actor: string
        action: string
        entityType: string
        entityId: string
        occurredAt: string
        reason: string
        before: Record<string, unknown>
        after: Record<string, unknown>
        requestId: string | null
        correlationId: string | null
      }>
    >('/audit', query, signal),
  accounts: (query: Query = {}, signal?: AbortSignal) =>
    get<{
      items: Account[]
      byType: Record<string, Account[]>
      accountTypes: string[]
      explainer: Record<string, string>
    }>('/accounts', query, signal),
  account: (accountNumber: string, signal?: AbortSignal) =>
    get<
      Account & {
        accountingEntries: PaymentDetail['accountingEntries']
        statementEntries: StatementEntry[]
        movement: { openingBalance: string; currentBalance: string; netMovement: string }
      }
    >(`/accounts/${encodeURIComponent(accountNumber)}`, undefined, signal),
  banks: (signal?: AbortSignal) =>
    get<{
      items: {
        bic: string
        name: string
        country: string
        city: string
        nationalClearingCode: string | null
        isDirectParticipant: boolean
        supportedSchemes: string[]
        isInternal: boolean
        notes: string
      }[]
      note: string
    }>('/banks', undefined, signal),
  statement: (accountNumber: string, signal?: AbortSignal) =>
    get<{
      account: Account
      messageType: string
      messageId: string
      isoIdentifier: string
      businessSummary: PaymentMessage['businessSummary']
      payload: string
      payloadFormat: string
      entries: StatementEntry[]
    }>(`/statement/${encodeURIComponent(accountNumber)}`, undefined, signal),
  messages: (query: Query = {}, signal?: AbortSignal) =>
    get<Paged<PaymentMessage> & { byType: Record<string, number>; catalogue: MessageCatalogueItem[] }>(
      '/messages',
      query,
      signal,
    ),
  messageCatalogue: (signal?: AbortSignal) =>
    get<{ items: MessageCatalogueItem[]; simulationNote: string }>(
      '/messages/catalogue',
      undefined,
      signal,
    ),
  mtMxReference: (signal?: AbortSignal) =>
    get<{
      source: string
      target: string
      rows: MtMxRow[]
      mappingTypes: { type: string; meaning: string }[]
      warning: string
    }>('/messages/mt-mx', undefined, signal),
  search: (q: string, limit = 12, signal?: AbortSignal) =>
    get<{ query: string; items: SearchHit[] }>('/search', { q, limit }, signal),

  // --- QA lab ---
  scenarios: (signal?: AbortSignal) =>
    get<{ items: Scenario[]; categories: string[]; demoButtons: DemoButton[] }>(
      '/scenarios',
      undefined,
      signal,
    ),
  scenario: (code: string, signal?: AbortSignal) =>
    get<Scenario>(`/scenarios/${encodeURIComponent(code)}`, undefined, signal),
  scenarioExecutions: (limit = 50, signal?: AbortSignal) =>
    get<{ items: ScenarioExecution[] }>('/scenarios/executions', { limit }, signal),
  runScenario: (code: string, body: { processingMode?: 'IMMEDIATE' | 'SIMULATED' } = {}) =>
    post<ScenarioRunResult>(`/scenarios/${encodeURIComponent(code)}/run`, body),
  runAllScenarios: () =>
    post<{
      total: number
      passed: number
      failed: number
      results: {
        scenarioCode: string
        title: string
        expectedStatus: string
        actualStatus: string
        paymentReference: string
        passed: boolean
      }[]
    }>('/scenarios/run-all', {}),
  demo: (signal?: AbortSignal) =>
    get<{ buttons: DemoButton[]; highlightScenarios: Scenario[] }>('/demo', undefined, signal),
  testCases: (query: Query = {}, signal?: AbortSignal) =>
    get<{
      items: TestCase[]
      suites: { suite: string; ruleId: string | null; scheme: string; cases: number }[]
      generatableRules: {
        ruleId: string
        name: string
        category: string
        field: string | null
        hasBoundaryAnalysis: boolean
      }[]
    }>('/test-cases', query, signal),
  generateTestCases: (body: { ruleId: string; scheme: string; suite?: string; persist?: boolean }) =>
    post<{ suite: string; ruleId: string; scheme: string; items: TestCase[] }>(
      '/test-cases/generate',
      body,
    ),
  runTestCases: (body: { ruleId?: string; scheme?: string; caseIds?: string[] }) =>
    post<{
      total: number
      passed: number
      failed: number
      results: {
        caseId: string
        title: string
        testType: string
        outcome: string
        detail: Record<string, unknown>
      }[]
    }>('/test-cases/run', body),

  // --- BA workbench ---
  baContext: (signal?: AbortSignal) =>
    get<{
      schemes: { code: string; name: string; shortName: string }[]
      artefactChain: string[]
      note: string
    }>('/ba/context', undefined, signal),
  baPackage: (scheme: string, scenarioCode?: string | null, signal?: AbortSignal) =>
    get<BaPackage>('/ba/package', { scheme, scenarioCode }, signal),
}

export type Api = typeof api
