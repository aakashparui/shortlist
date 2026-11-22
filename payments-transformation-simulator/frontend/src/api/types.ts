/** Response shapes from the simulator API. Mirrors app/api/serializers.py. */

export type PaymentStatus =
  | 'DRAFT'
  | 'INITIATED'
  | 'VALIDATING'
  | 'VALIDATED'
  | 'REJECTED'
  | 'COMPLIANCE_CHECK'
  | 'BLOCKED'
  | 'MESSAGE_GENERATED'
  | 'SENT_TO_CLEARING'
  | 'CLEARING_ACCEPTED'
  | 'CLEARING_REJECTED'
  | 'TIMED_OUT'
  | 'INVESTIGATION_REQUIRED'
  | 'REPROCESSING'
  | 'SETTLEMENT_PENDING'
  | 'SETTLED'
  | 'SETTLEMENT_FAILED'
  | 'ACCOUNTED'
  | 'ACCOUNTING_BREAK'
  | 'RECONCILED'
  | 'RECONCILIATION_BREAK'
  | 'COMPLETED'
  | 'CANCELLED'
  | 'RETURNED'
  | 'REVERSED'

export type StageState =
  | 'PENDING'
  | 'IN_PROGRESS'
  | 'COMPLETED'
  | 'REJECTED'
  | 'FAILED'
  | 'TIMED_OUT'
  | 'CANCELLED'
  | 'REVERSED'
  | 'INVESTIGATION_REQUIRED'
  | 'REPROCESSING'
  | 'SKIPPED'

export type Severity = 'INFO' | 'WARNING' | 'ERROR' | 'FATAL'
export type ValidationStatusValue = 'PASSED' | 'FAILED' | 'SKIPPED' | 'NOT_APPLICABLE'
export type ViewMode = 'business' | 'technical'

export interface Party {
  role: string
  name: string
  accountIdentifier: string
  iban: string | null
  bic: string | null
  bankName: string
  country: string
  town: string
  addressLines: string[]
}

export interface Account {
  id: number
  accountNumber: string
  iban: string | null
  name: string
  accountType: string
  currency: string
  balance: string
  balanceFormatted: string
  openingBalance: string
  overdraftLimit: string
  isActive: boolean
  description: string
  bank: { bic: string; name: string } | null
  correspondentBank: { bic: string; name: string } | null
}

export interface Stage {
  stageKey: string
  sequence: number
  state: StageState
  businessLabel: string
  technicalLabel: string
  ownerSystem: string
  startedAt: string | null
  completedAt: string | null
  durationMs: number | null
  summary: string
  failureReason: string | null
  isoReasonCode: string | null
  detail: Record<string, unknown>
}

export interface ValidationResult {
  id: number
  runId: number
  ruleId: string
  ruleName: string
  category: string
  severity: Severity
  status: ValidationStatusValue
  stage: string
  message: string
  field: string | null
  actualValue: string | null
  expectedValue: string | null
  isoReasonCode: string | null
  remediation: string
  executedAt: string
  durationMs: number
  injected: boolean
}

export interface FieldMapping {
  sourceLabel: string
  sourceField: string
  isoPath: string
  value: string | null
  mappingType: 'DIRECT' | 'TRANSFORMED' | 'DERIVED' | 'NO_EQUIVALENT'
  note: string
  present: boolean
}

export interface MessageCheck {
  ruleId: string
  ruleName: string
  status: string
  severity: string
  message: string
  field: string | null
}

export interface BusinessSummary {
  messageName?: string
  isoIdentifier?: string
  purpose?: string
  plainEnglish?: string
  keyFacts?: { label: string; value: string }[]
  statusMeaning?: string
  simulationNote?: string
}

export interface PaymentMessage {
  id: number
  messageType: string
  messageName: string
  isoIdentifier: string
  messageId: string
  direction: 'INBOUND' | 'OUTBOUND'
  state: string
  relatedMessageId: string | null
  reasonCode: string | null
  isMalformed: boolean
  createdAt: string
  sentAt: string | null
  receivedAt: string | null
  notes: string
  businessSummary: BusinessSummary
  fieldMappings: FieldMapping[]
  validationSummary: MessageCheck[]
  payload: string | null
  payloadFormat: 'XML' | 'FIN'
  correlationId: string
  paymentReference?: string | null
}

export interface PaymentEvent {
  id: number
  paymentId: number | null
  sequence: number
  eventType: string
  sourceSystem: string
  severity: Severity
  stageKey: string | null
  summary: string
  detail: Record<string, unknown>
  occurredAt: string
  durationMs: number | null
  correlationId: string | null
  paymentReference?: string | null
}

export interface ClearingTransaction {
  id: number
  clearingReference: string
  clearingSystem: string
  scheme: string
  status: string
  decision: string | null
  requestedDecision: string | null
  amount: string
  currency: string
  sentAt: string | null
  responseDueAt: string | null
  timeoutAt: string | null
  respondedAt: string | null
  responseLatencyMs: number | null
  statusReasonCode: string | null
  statusReason: string | null
  attempt: number
  responseCount: number
  requestMessageId: string | null
  responseMessageId: string | null
  detail: Record<string, unknown>
}

export interface SettlementTransaction {
  id: number
  settlementReference: string
  status: string
  paymentAmount: string
  paymentCurrency: string
  settlementAmount: string
  settlementCurrency: string
  settlementAmountFormatted: string
  settlementMethod: string
  valueDate: string | null
  submittedAt: string | null
  settledAt: string | null
  failureReason: string | null
  isoReasonCode: string | null
  account: Account | null
  detail: Record<string, unknown>
}

export interface AccountingEntry {
  id: number
  entryId: string
  accountingReference: string
  journalSequence: number
  side: 'DEBIT' | 'CREDIT'
  accountNumber: string
  accountName: string
  accountType: string
  amount: string
  currency: string
  amountFormatted: string
  postingDate: string | null
  valueDate: string | null
  postedAt: string
  status: string
  narrative: string
  isDuplicate: boolean
  isInjectedAnomaly: boolean
  anomalyNote: string | null
  balanceAfter: string | null
}

export interface StatementEntry {
  id: number
  paymentId: number | null
  statementReference: string
  accountNumber: string
  side: 'DEBIT' | 'CREDIT'
  amount: string
  currency: string
  amountFormatted: string
  bookingDate: string | null
  valueDate: string | null
  endToEndId: string | null
  bankTransactionCode: string
  narrative: string
  sourceMessageType: string
  sourceMessageId: string | null
  isOrphan: boolean
  createdAt: string
}

export interface ReconciliationLeg {
  name: string
  source: string
  reference: string | null
  amount: string | null
  currency: string | null
  bookingDate: string | null
  present: boolean
  note: string
}

export interface ReconciliationRecord {
  id: number
  paymentId: number | null
  paymentReference: string | null
  reference: string
  status: string
  runAt: string
  internalReference: string | null
  internalAmount: string | null
  internalCurrency: string | null
  accountingReference: string | null
  accountingAmount: string | null
  clearingReference: string | null
  clearingAmount: string | null
  statementReference: string | null
  statementAmount: string | null
  statementCurrency: string | null
  differenceAmount: string | null
  probableCause: string
  recommendedAction: string
  legs: ReconciliationLeg[]
  detail: Record<string, unknown>
  resolved: boolean
  payment?: PaymentDetail
}

export interface InvestigationAction {
  at: string
  actor: string
  action: string
  note: string
}

export interface Investigation {
  id: number
  reference: string
  paymentId: number | null
  paymentReference: string | null
  status: string
  reason: string
  priority: string
  title: string
  summary: string
  expectedBehaviour: string
  actualBehaviour: string
  probableCause: string
  recommendedAction: string
  assignedTo: string
  openedAt: string
  updatedAt: string
  resolvedAt: string | null
  resolution: string | null
  actions: InvestigationAction[]
  detail: Record<string, unknown>
  payment?: PaymentDetail
  reconciliationRecord?: ReconciliationRecord
}

export interface FailureInjection {
  id: number
  paymentId: number | null
  code: string
  category: string
  label: string
  stageKey: string
  parameters: Record<string, unknown>
  active: boolean
  consumed: boolean
  createdAt: string
  createdBy: string
  effectSummary: string | null
}

export interface FailureDefinition {
  code: string
  label: string
  category: string
  stage: string
  description: string
  mechanism: string
  expectedOutcome: string
  expectedStatus: string
  affectedRuleIds: string[]
  parameters: Record<string, unknown>
  schemes: string[]
}

export interface BusinessRule {
  ruleId: string
  name: string
  description: string
  category: string
  severity: Severity
  stage: string
  schemes: string[]
  appliesTo: string[]
  field: string | null
  failureBehaviour: string
  isoReasonCode: string | null
  rationale: string
  standardBasis: string
  enabled: boolean
  parameters: Record<string, unknown>
  relatedFailureInjections?: FailureDefinition[]
}

export interface AmountLimit {
  currency: string
  minimum: string
  maximum: string
}

export interface Scheme {
  code: string
  name: string
  shortName: string
  operator: string
  jurisdiction: string
  description: string
  simulationNotes: string
  isInstant: boolean
  settlementCurrency: string
  allowedCurrencies: string[]
  amountLimits: AmountLimit[]
  countryScope: string[] | null
  maxRemittanceLength: number
  requiresPurposeCode: boolean
  allowedServiceLevels: string[]
  allowedLocalInstruments: string[]
  allowsFutureDated: boolean
  maxFutureDays: number
  duplicateWindowMinutes: number
  usesUetr: boolean
  supportsCancellation: boolean
  supportsReturn: boolean
  messages: string[]
  legacyMessage: string | null
  clearing: {
    system: string
    operator: string
    responseSeconds: number
    timeoutSeconds: number
    investigationThresholdSeconds: number
    settlementFinality: string
    operatingHours: string
    rejectionReasonCodes: string[]
  }
  settlement: {
    method: string
    accountType: string
    settlesInSchemeCurrency: boolean
    valueDateOffsetDays: number
    description: string
  }
  validationRuleIds: string[]
  acceleratedTimeoutSeconds?: number
  rules?: BusinessRule[]
  paymentCounts?: Record<string, number>
  messageCatalogue?: MessageCatalogueItem[]
}

export interface MessageCatalogueItem {
  messageType: string
  name: string
  isoIdentifier: string
  direction: string
  purpose: string
  count?: number
  usedBySchemes?: string[]
}

export interface PaymentSummary {
  id: number
  reference: string
  correlationId: string
  scheme: string
  status: PaymentStatus
  isFailure: boolean
  isTerminal: boolean
  amount: string
  currency: string
  amountFormatted: string
  debtorName: string
  creditorName: string
  creditorCountry: string
  endToEndId: string
  uetr: string | null
  createdAt: string
  updatedAt: string
  completedAt: string | null
  failureSummary: string | null
  scenarioCode: string | null
  retryCount: number
  isDemoData: boolean
  tags: string[]
}

export interface MtMxRow {
  mtTag: string
  mtName: string
  mxPath: string
  mappingType: string
  note: string
  mtValue?: string | null
  mxValue?: string | null
}

export interface PaymentDetail extends PaymentSummary {
  previousStatus: string | null
  processingMode: string
  direction: string
  requestedExecutionDate: string | null
  instructionId: string
  transactionId: string
  remittanceInformation: string
  remittanceStructured: Record<string, unknown>
  purposeCode: string | null
  categoryPurpose: string | null
  serviceLevel: string | null
  localInstrument: string | null
  clearingChannel: string | null
  chargeBearer: string
  priority: string
  createdBy: string
  source: string
  notes: string
  executedAt: string | null
  debtor: Party | null
  creditor: Party | null
  debtorAccount: Account | null
  stages: Stage[]
  failureInjections: FailureInjection[]
  schemeDetail: Scheme
  events: PaymentEvent[]
  validations: ValidationResult[]
  messages: PaymentMessage[]
  clearing: ClearingTransaction[]
  settlements: SettlementTransaction[]
  accountingEntries: AccountingEntry[]
  statementEntries: StatementEntry[]
  reconciliationRecords: ReconciliationRecord[]
  investigations: Investigation[]
  mtMxMapping: MtMxRow[]
  pendingJobs: { jobType: string; dueAt: string; status: string }[]
  allowedTransitions: string[]
  execution?: {
    status: string
    stagesCompleted: string[]
    failureStage: string | null
    failureReason: string | null
    awaitingAsync: boolean
    notes: string[]
  }
  cancellation?: {
    requestMessage: PaymentMessage
    resolutionMessage: PaymentMessage | null
  }
  returnMessage?: PaymentMessage
}

export interface Paged<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
  pages?: number
}

export interface Statistics {
  totalPayments: number
  byStatus: Record<string, number>
  byScheme: Record<string, number>
  byCurrency: { currency: string; count: number; total: string }[]
  failureCount: number
  successRate: number
  openInvestigations: number
  reconciliationBreaks: number
  unmatchedStatementEntries: number
  averageClearingLatencyMs: number | null
  createdLast24h: number
}

export interface Scenario {
  code: string
  title: string
  category: string
  scheme: string
  description: string
  businessContext: string
  preconditions: string[]
  inputData: Record<string, unknown>
  failureCodes: string[]
  executionSteps: string[]
  expectedStatus: string
  expectedResult: string[]
  expectedMessages: string[]
  expectedAccounting: string[]
  expectedReconciliation: string
  failureConditions: string[]
  isDemoHighlight: boolean
  sortOrder: number
}

export interface ScenarioAssertion {
  name: string
  expected: string
  actual: string
  passed: boolean
  note: string
}

export interface ScenarioExecution {
  id: number
  reference: string
  scenarioCode: string
  scenarioTitle: string | null
  paymentId: number | null
  paymentReference: string | null
  startedAt: string
  finishedAt: string | null
  outcome: string
  actualStatus: string | null
  expectedStatus: string | null
  assertions: ScenarioAssertion[]
  notes: string
}

export interface ScenarioRunResult {
  scenario: Scenario
  execution: ScenarioExecution
  assertions: ScenarioAssertion[]
  passed: boolean
  payment: PaymentDetail
}

export interface TestCase {
  id: number
  caseId: string
  suite: string
  ruleId: string | null
  scheme: string
  testType: string
  title: string
  preconditions: string[]
  steps: string[]
  inputData: Record<string, unknown>
  expectedResult: string
  expectedStatus: string | null
  expectedRuleOutcome: string | null
  priority: string
  requirementId: string | null
  createdAt: string
  lastRunAt: string | null
  lastRunOutcome: string | null
  lastRunDetail: Record<string, unknown>
}

export interface SearchHit {
  kind: string
  title: string
  subtitle: string
  route: string
  badge: string | null
}

export interface BaPackage {
  scheme: Scheme
  scenarioCode: string | null
  scenarioTitle: string | null
  businessRequirement: {
    id: string
    title: string
    statement: string
    rationale: string
    scope: string[]
    outOfScope: string[]
    assumptions: string[]
    stakeholders: string[]
  }
  functionalRequirements: {
    id: string
    title: string
    statement: string
    ruleIds: string[]
    stage: string
  }[]
  businessRules: BusinessRule[]
  processFlow: {
    step: number
    stage: string
    businessLabel: string
    technicalLabel: string
    actor: string
    output: string
  }[]
  acceptanceCriteria: {
    id: string
    given: string
    when: string
    then: string
    linkedRequirement: string
  }[]
  exceptionScenarios: {
    scenarioCode: string
    title: string
    category: string
    trigger: string
    detectedAt: string
    systemBehaviour: string
    expectedStatus: string
    operationalResponse: string
    customerImpact: string
  }[]
  testScenarios: {
    testScenarioId: string
    scenarioCode: string
    title: string
    category: string
    scheme: string
    preconditions: string[]
    steps: string[]
    expectedStatus: string
    expectedResult: string[]
    expectedMessages: string[]
    expectedReconciliation: string
  }[]
  messageCatalogue: MessageCatalogueItem[]
  traceabilityMatrix: {
    businessRequirementId: string
    functionalRequirementId: string
    functionalRequirement: string
    businessRuleIds: string[]
    stage: string
    isoMessages: string[]
    testScenarioIds: string[]
    coverage: string
  }[]
}

export interface AppConfig {
  appName: string
  appVersion: string
  environment: string
  demoMode: boolean
  simulationSpeedFactor: number
  clearingTimeoutSecondsFallback: number
  schedulerEnabled: boolean
  schedulerPollIntervalSeconds: number
  maxPageSize: number
  rateLimitEnabled: boolean
  aiEnabled: boolean
  aiProvider: string | null
  aiModel: string | null
  database: string
  currencies: { code: string; name: string }[]
  schemeTimeouts: { scheme: string; realisticSeconds: number; acceleratedSeconds: number }[]
  simulationDisclaimer: string
}

export interface ExceptionsOverview {
  summary: {
    failedPayments: number
    reconciliationBreaks: number
    openInvestigations: number
    unmatchedStatementEntries: number
    byStatus: Record<string, number>
  }
  payments: PaymentSummary[]
  reconciliationBreaks: ReconciliationRecord[]
  investigations: Investigation[]
  unmatchedStatementEntries: StatementEntry[]
}

export interface DemoButton {
  id: string
  label: string
  scenarioCode: string
  description: string
}

export interface PaymentCreateInput {
  scheme: string
  amount: string
  currency: string
  requestedExecutionDate?: string | null
  debtor: PartyInput
  creditor: PartyInput
  remittanceInformation?: string
  remittanceStructured?: Record<string, unknown>
  purposeCode?: string | null
  categoryPurpose?: string | null
  serviceLevel?: string | null
  localInstrument?: string | null
  clearingChannel?: string | null
  chargeBearer?: string | null
  priority?: string | null
  instructionId?: string | null
  endToEndId?: string | null
  transactionId?: string | null
  uetr?: string | null
  debtorAccountNumber?: string | null
  processingMode?: 'IMMEDIATE' | 'SIMULATED'
  notes?: string
  tags?: string[]
  failureInjections?: { code: string; parameters?: Record<string, unknown> }[]
}

export interface PartyInput {
  name: string
  accountIdentifier?: string
  iban?: string | null
  bic?: string | null
  bankName?: string
  country?: string
  town?: string
  addressLines?: string[]
}
