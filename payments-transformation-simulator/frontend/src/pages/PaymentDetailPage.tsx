/**
 * The investigation workbench for one payment: journey, messages, validations,
 * clearing, settlement, accounting, reconciliation, events, tracking, audit and
 * the operator actions the state machine currently permits.
 */

import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { api } from '../api/client'
import type { PaymentDetail } from '../api/types'
import { useAction, useAsync, usePolling } from '../hooks/useAsync'
import {
  formatAmount,
  formatDate,
  formatDateTime,
  formatDuration,
  formatTime,
  schemeLabel,
  severityTone,
  toneFor,
} from '../lib/format'
import { MessageViewer } from '../components/MessageViewer'
import { PaymentJourney } from '../components/PaymentJourney'
import { useViewMode } from '../components/ViewModeContext'
import {
  DataTable,
  Drawer,
  Empty,
  ErrorState,
  Field,
  JsonBlock,
  KeyValue,
  Loading,
  Notice,
  PageHeader,
  Panel,
  SimulationNote,
  StatusChip,
  Tabs,
  type Column,
} from '../components/ui'

type Tab =
  | 'journey'
  | 'messages'
  | 'validations'
  | 'clearing'
  | 'accounting'
  | 'reconciliation'
  | 'events'
  | 'tracking'
  | 'mtmx'
  | 'raw'

export function PaymentDetailPage() {
  const { reference = '' } = useParams()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const { isTechnical } = useViewMode()
  const [tab, setTab] = useState<Tab>((params.get('tab') as Tab) ?? 'journey')
  const [focusMessage, setFocusMessage] = useState<string | null>(null)
  const [actionPanel, setActionPanel] = useState<'retry' | 'cancel' | 'return' | 'timeout' | null>(null)

  const payment = useAsync((signal) => api.getPayment(reference, signal), [reference])
  const data = payment.data

  // While the lifecycle is running asynchronously, follow it.
  const awaiting = Boolean(data && data.pendingJobs.length > 0)
  usePolling(() => payment.reload(), 1500, awaiting)

  useEffect(() => {
    const next = new URLSearchParams(params)
    next.set('tab', tab)
    setParams(next, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  const execute = useAction(
    () =>
      api.executePayment(reference, {
        processingMode: 'IMMEDIATE',
        waitForCompletion: true,
      }),
    { onSuccess: () => payment.reload() },
  )
  const reconcile = useAction(() => api.reconcilePayment(reference), {
    onSuccess: () => payment.reload(),
  })

  if (payment.loading && !data) {
    return (
      <div className="page">
        <Loading rows={10} label="Loading payment" />
      </div>
    )
  }
  if (payment.error) {
    return (
      <div className="page">
        <PageHeader eyebrow="Payments" title={reference} />
        <ErrorState error={payment.error} onRetry={payment.reload} />
        <div style={{ marginTop: 'var(--s-5)' }}>
          <Link className="btn" to="/payments">
            Back to payment search
          </Link>
        </div>
      </div>
    )
  }
  if (!data) return null

  const canExecute = data.allowedTransitions.includes('VALIDATING') || data.status === 'INITIATED'
  const canRetry = data.allowedTransitions.includes('REPROCESSING')
  const timedOut = data.status === 'INVESTIGATION_REQUIRED' || data.status === 'TIMED_OUT'

  return (
    <div className="page">
      <PageHeader
        eyebrow={`${schemeLabel(data.scheme)} · ${data.processingMode}`}
        title={data.reference}
        lede={
          <>
            {formatAmount(data.amount, data.currency)} from <strong>{data.debtor?.name}</strong> to{' '}
            <strong>{data.creditor?.name}</strong>
            {data.creditor?.country ? ` (${data.creditor.country})` : ''}.
          </>
        }
        actions={
          <>
            <StatusChip value={data.status} />
            {canExecute && (
              <button
                type="button"
                className="btn"
                data-variant="primary"
                onClick={() => void execute.run()}
                disabled={execute.pending}
              >
                {execute.pending ? 'Executing…' : 'Execute'}
              </button>
            )}
            {canRetry && (
              <button type="button" className="btn" onClick={() => setActionPanel('retry')}>
                Reprocess
              </button>
            )}
            {timedOut && (
              <button type="button" className="btn" onClick={() => setActionPanel('timeout')}>
                Apply clearing answer
              </button>
            )}
            {data.schemeDetail.supportsCancellation && (
              <button type="button" className="btn" onClick={() => setActionPanel('cancel')}>
                Request cancellation
              </button>
            )}
            {data.schemeDetail.supportsReturn && data.status === 'COMPLETED' && (
              <button type="button" className="btn" onClick={() => setActionPanel('return')}>
                Apply return
              </button>
            )}
            <button
              type="button"
              className="btn"
              onClick={() => void reconcile.run()}
              disabled={reconcile.pending}
            >
              {reconcile.pending ? 'Reconciling…' : 'Reconcile'}
            </button>
          </>
        }
      />

      <div className="stack">
        {execute.error && <ErrorState error={execute.error} />}
        {reconcile.error && <ErrorState error={reconcile.error} />}

        {awaiting && (
          <Notice tone="info" title="Processing">
            The payment is waiting on the clearing system. Next scheduled work:{' '}
            {data.pendingJobs
              .map((job) => `${job.jobType} at ${formatTime(job.dueAt)}`)
              .join(', ')}
            . This view refreshes automatically.
          </Notice>
        )}

        {data.failureSummary && (
          <Notice tone="error" title="This payment is in a failure state">
            {data.failureSummary}
          </Notice>
        )}

        {data.investigations.length > 0 && (
          <Notice tone="warn" title={`${data.investigations.length} investigation(s) on this payment`}>
            {data.investigations.map((investigation) => (
              <div key={investigation.reference} style={{ marginBottom: 'var(--s-2)' }}>
                <Link to={`/investigations/${investigation.reference}`} className="mono">
                  {investigation.reference}
                </Link>{' '}
                — {investigation.title} <StatusChip value={investigation.status} mode="raw" />
              </div>
            ))}
          </Notice>
        )}

        <div className="grid grid-main-aside">
          <div className="stack">
            <Panel flush>
              <Tabs
                tabs={[
                  { id: 'journey', label: 'Journey' },
                  { id: 'messages', label: 'Messages', count: data.messages.length },
                  { id: 'validations', label: 'Validations', count: data.validations.length },
                  { id: 'clearing', label: 'Clearing & settlement', count: data.clearing.length },
                  { id: 'accounting', label: 'Accounting', count: data.accountingEntries.length },
                  {
                    id: 'reconciliation',
                    label: 'Reconciliation',
                    count: data.reconciliationRecords.length,
                  },
                  { id: 'events', label: 'Events', count: data.events.length },
                  ...(data.schemeDetail.usesUetr
                    ? ([{ id: 'tracking', label: 'UETR tracking' }, { id: 'mtmx', label: 'MT → MX' }] as const)
                    : []),
                  ...(isTechnical ? ([{ id: 'raw', label: 'Raw' }] as const) : []),
                ]}
                active={tab}
                onChange={(id) => setTab(id as Tab)}
              />
              <div>
                {tab === 'journey' && (
                  <PaymentJourney
                    payment={data}
                    onOpenMessage={(messageId) => {
                      setFocusMessage(messageId)
                      setTab('messages')
                    }}
                  />
                )}
                {tab === 'messages' && (
                  <MessageViewer
                    messages={data.messages}
                    activeMessageId={focusMessage}
                    onSelect={setFocusMessage}
                  />
                )}
                {tab === 'validations' && <ValidationsTab payment={data} />}
                {tab === 'clearing' && <ClearingTab payment={data} />}
                {tab === 'accounting' && <AccountingTab payment={data} />}
                {tab === 'reconciliation' && <ReconciliationTab payment={data} />}
                {tab === 'events' && <EventsTab payment={data} />}
                {tab === 'tracking' && <TrackingTab reference={data.reference} />}
                {tab === 'mtmx' && <MtMxTab payment={data} />}
                {tab === 'raw' && (
                  <div style={{ padding: 'var(--s-5)' }}>
                    <JsonBlock value={data} />
                  </div>
                )}
              </div>
            </Panel>
          </div>

          <div className="stack">
            <Panel title="Identifiers" subtitle="One payment, traceable from any direction">
              <KeyValue
                items={[
                  { label: 'Payment reference', value: data.reference, mono: true },
                  { label: 'Correlation id', value: data.correlationId, mono: true },
                  { label: 'Instruction id', value: data.instructionId, mono: true },
                  { label: 'End-to-end id', value: data.endToEndId, mono: true },
                  { label: 'Transaction id', value: data.transactionId, mono: true },
                  ...(data.uetr ? [{ label: 'UETR', value: data.uetr, mono: true }] : []),
                  ...(data.clearing[0]
                    ? [{ label: 'Clearing reference', value: data.clearing[0].clearingReference, mono: true }]
                    : []),
                  ...(data.settlements[0]
                    ? [
                        {
                          label: 'Settlement reference',
                          value: data.settlements[0].settlementReference,
                          mono: true,
                        },
                      ]
                    : []),
                  ...(data.accountingEntries[0]
                    ? [
                        {
                          label: 'Accounting reference',
                          value: data.accountingEntries[0].accountingReference,
                          mono: true,
                        },
                      ]
                    : []),
                  ...(data.reconciliationRecords[0]
                    ? [
                        {
                          label: 'Reconciliation reference',
                          value: data.reconciliationRecords[0].reference,
                          mono: true,
                        },
                      ]
                    : []),
                ]}
              />
            </Panel>

            <Panel title="Instruction">
              <KeyValue
                items={[
                  { label: 'Amount', value: formatAmount(data.amount, data.currency), mono: true },
                  { label: 'Rail', value: data.schemeDetail.name },
                  { label: 'Execution date', value: formatDate(data.requestedExecutionDate) },
                  { label: 'Remittance', value: data.remittanceInformation || '—' },
                  { label: 'Purpose code', value: data.purposeCode ?? '—', mono: true },
                  { label: 'Service level', value: data.serviceLevel ?? '—', mono: true },
                  { label: 'Charge bearer', value: data.chargeBearer, mono: true },
                  { label: 'Clearing channel', value: data.clearingChannel ?? '—', mono: true },
                  { label: 'Created', value: formatDateTime(data.createdAt) },
                  { label: 'Created by', value: data.createdBy, mono: true },
                  { label: 'Source', value: data.source, mono: true },
                  ...(data.notes ? [{ label: 'Notes', value: data.notes }] : []),
                ]}
              />
            </Panel>

            <Panel title="Parties">
              <div className="col">
                <PartyBlock title="Debtor" party={data.debtor} />
                <hr />
                <PartyBlock title="Creditor" party={data.creditor} />
                {data.debtorAccount && (
                  <>
                    <hr />
                    <div className="col-tight">
                      <span className="label">Debtor account on our book</span>
                      <KeyValue
                        items={[
                          { label: 'Account', value: data.debtorAccount.accountNumber, mono: true },
                          { label: 'Balance', value: data.debtorAccount.balanceFormatted, mono: true },
                          {
                            label: 'Overdraft',
                            value: formatAmount(
                              data.debtorAccount.overdraftLimit,
                              data.debtorAccount.currency,
                            ),
                            mono: true,
                          },
                        ]}
                      />
                    </div>
                  </>
                )}
              </div>
            </Panel>

            {data.failureInjections.length > 0 && (
              <Panel title="Failure injections" subtitle="What was deliberately broken">
                <div className="col-tight">
                  {data.failureInjections.map((injection) => (
                    <div
                      key={injection.id}
                      style={{
                        border: '1px solid var(--line)',
                        borderRadius: 'var(--radius)',
                        padding: 'var(--s-4)',
                      }}
                    >
                      <div className="row-tight">
                        <span className="mono" style={{ fontSize: 'var(--fs-xs)' }}>
                          {injection.code}
                        </span>
                        <StatusChip
                          value={injection.consumed ? 'APPLIED' : injection.active ? 'ARMED' : 'INACTIVE'}
                          mode="raw"
                          tone={injection.consumed ? 'error' : injection.active ? 'warn' : 'neutral'}
                        />
                      </div>
                      <div className="muted" style={{ fontSize: 'var(--fs-xs)', marginTop: 'var(--s-2)' }}>
                        {injection.effectSummary ?? injection.label}
                      </div>
                    </div>
                  ))}
                </div>
              </Panel>
            )}

            <Panel title="State machine">
              <KeyValue
                items={[
                  { label: 'Current', value: <StatusChip value={data.status} mode="raw" /> },
                  { label: 'Previous', value: data.previousStatus ?? '—', mono: true },
                  {
                    label: 'Permitted next',
                    value:
                      data.allowedTransitions.length > 0 ? (
                        <div className="row-wrap">
                          {data.allowedTransitions.map((status) => (
                            <span className="tag" key={status}>
                              {status}
                            </span>
                          ))}
                        </div>
                      ) : (
                        'terminal state'
                      ),
                  },
                  { label: 'Retries', value: String(data.retryCount), mono: true },
                ]}
              />
            </Panel>

            <SimulationNote>{data.schemeDetail.simulationNotes}</SimulationNote>
          </div>
        </div>
      </div>

      {actionPanel && (
        <ActionDrawer
          kind={actionPanel}
          reference={data.reference}
          onClose={() => setActionPanel(null)}
          onDone={() => {
            setActionPanel(null)
            payment.reload()
          }}
          navigate={navigate}
        />
      )}
    </div>
  )
}

function PartyBlock({ title, party }: { title: string; party: PaymentDetail['debtor'] }) {
  if (!party) return null
  return (
    <div className="col-tight">
      <span className="label">{title}</span>
      <KeyValue
        items={[
          { label: 'Name', value: party.name },
          { label: 'IBAN', value: party.iban ?? '—', mono: true },
          ...(party.accountIdentifier
            ? [{ label: 'Account', value: party.accountIdentifier, mono: true }]
            : []),
          { label: 'BIC', value: party.bic ?? '—', mono: true },
          { label: 'Bank', value: party.bankName || '—' },
          {
            label: 'Address',
            value: [...party.addressLines, party.town, party.country].filter(Boolean).join(', ') || '—',
          },
        ]}
      />
    </div>
  )
}

function ValidationsTab({ payment }: { payment: PaymentDetail }) {
  const [onlyFailures, setOnlyFailures] = useState(false)
  const rows = onlyFailures
    ? payment.validations.filter((item) => item.status === 'FAILED')
    : payment.validations

  const columns: Column<PaymentDetail['validations'][number]> = {
    key: '',
    header: '',
    render: () => null,
  }
  void columns

  return (
    <div className="col" style={{ padding: 'var(--s-5)' }}>
      <div className="row-wrap">
        <span className="label">Rule executions</span>
        <span className="dim mono" style={{ fontSize: 'var(--fs-micro)' }}>
          {payment.validations.length} results ·{' '}
          {payment.validations.filter((v) => v.status === 'FAILED').length} failed ·{' '}
          {payment.validations.filter((v) => v.status === 'SKIPPED').length} skipped
        </span>
        <span className="spacer" />
        <label className="checkbox">
          <input
            type="checkbox"
            checked={onlyFailures}
            onChange={(event) => setOnlyFailures(event.target.checked)}
          />
          <span>Failures only</span>
        </label>
      </div>
      <DataTable
        columns={[
          {
            key: 'rule',
            header: 'Rule',
            render: (row) => (
              <>
                <div className="cell-primary">{row.ruleId}</div>
                <div className="cell-secondary">{row.ruleName}</div>
              </>
            ),
          },
          {
            key: 'stage',
            header: 'Stage',
            render: (row) => (
              <>
                <div style={{ fontSize: 'var(--fs-xs)' }}>{row.stage}</div>
                <div className="cell-secondary">{row.category}</div>
              </>
            ),
          },
          {
            key: 'status',
            header: 'Outcome',
            render: (row) => (
              <div className="row-tight">
                <span className="severity" data-tone={severityTone(row.severity)} />
                <div>
                  <StatusChip value={row.status} mode="raw" />
                  {row.isoReasonCode && <div className="cell-secondary mono">{row.isoReasonCode}</div>}
                </div>
              </div>
            ),
          },
          {
            key: 'detail',
            header: 'Detail',
            render: (row) => (
              <>
                <div>{row.message}</div>
                {(row.actualValue || row.expectedValue) && (
                  <div className="cell-secondary mono">
                    actual: {row.actualValue ?? '—'} · expected: {row.expectedValue ?? '—'}
                  </div>
                )}
                {row.remediation && row.status === 'FAILED' && (
                  <div className="cell-secondary">→ {row.remediation}</div>
                )}
              </>
            ),
          },
          {
            key: 'duration',
            header: 'Took',
            numeric: true,
            render: (row) => formatDuration(row.durationMs),
          },
        ]}
        rows={rows}
        rowKey={(row) => String(row.id)}
        emptyTitle={onlyFailures ? 'No failed rules' : 'No validation results'}
        emptyBody="Validation runs when the payment is executed."
      />
    </div>
  )
}

function ClearingTab({ payment }: { payment: PaymentDetail }) {
  return (
    <div className="col" style={{ padding: 'var(--s-5)' }}>
      <div className="col-tight">
        <span className="label">Clearing</span>
        {payment.clearing.length === 0 ? (
          <Empty title="Never dispatched to clearing">
            The payment did not reach the clearing stage, so no clearing record exists.
          </Empty>
        ) : (
          payment.clearing.map((item) => (
            <div
              key={item.id}
              style={{ border: '1px solid var(--line)', borderRadius: 'var(--radius)', padding: 'var(--s-5)' }}
            >
              <div className="row-wrap" style={{ marginBottom: 'var(--s-4)' }}>
                <span className="mono">{item.clearingReference}</span>
                <StatusChip value={item.status} mode="raw" tone={toneFor(item.status)} />
                <span className="tag">attempt {item.attempt}</span>
                {item.requestedDecision && item.requestedDecision !== 'ACCEPT' && (
                  <span className="tag" data-tone="accent">
                    injected: {item.requestedDecision}
                  </span>
                )}
              </div>
              <KeyValue
                items={[
                  { label: 'Clearing system', value: item.clearingSystem },
                  { label: 'Amount', value: formatAmount(item.amount, item.currency), mono: true },
                  { label: 'Sent', value: formatDateTime(item.sentAt), mono: true },
                  { label: 'Response due', value: formatDateTime(item.responseDueAt), mono: true },
                  { label: 'Timeout at', value: formatDateTime(item.timeoutAt), mono: true },
                  { label: 'Responded', value: formatDateTime(item.respondedAt), mono: true },
                  { label: 'Latency', value: formatDuration(item.responseLatencyMs), mono: true },
                  { label: 'Responses received', value: String(item.responseCount), mono: true },
                  { label: 'Request message', value: item.requestMessageId ?? '—', mono: true },
                  { label: 'Response message', value: item.responseMessageId ?? '—', mono: true },
                  ...(item.statusReasonCode
                    ? [{ label: 'Reason code', value: item.statusReasonCode, mono: true }]
                    : []),
                  ...(item.statusReason ? [{ label: 'Reason', value: item.statusReason }] : []),
                ]}
              />
            </div>
          ))
        )}
      </div>

      <div className="col-tight">
        <span className="label">Settlement</span>
        {payment.settlements.length === 0 ? (
          <Empty title="No settlement record">
            Settlement only happens once the clearing system has accepted the instruction.
          </Empty>
        ) : (
          payment.settlements.map((item) => (
            <div
              key={item.id}
              style={{ border: '1px solid var(--line)', borderRadius: 'var(--radius)', padding: 'var(--s-5)' }}
            >
              <div className="row-wrap" style={{ marginBottom: 'var(--s-4)' }}>
                <span className="mono">{item.settlementReference}</span>
                <StatusChip value={item.status} mode="raw" tone={toneFor(item.status)} />
                <span className="tag">{item.settlementMethod}</span>
              </div>
              <KeyValue
                items={[
                  {
                    label: 'Payment amount',
                    value: formatAmount(item.paymentAmount, item.paymentCurrency),
                    mono: true,
                  },
                  {
                    label: 'Settlement amount',
                    value: formatAmount(item.settlementAmount, item.settlementCurrency),
                    mono: true,
                  },
                  { label: 'Value date', value: formatDate(item.valueDate) },
                  { label: 'Submitted', value: formatDateTime(item.submittedAt), mono: true },
                  { label: 'Settled', value: formatDateTime(item.settledAt), mono: true },
                  {
                    label: 'Settlement account',
                    value: item.account
                      ? `${item.account.accountNumber} (${item.account.accountType})`
                      : '—',
                    mono: true,
                  },
                  ...(item.failureReason ? [{ label: 'Failure', value: item.failureReason }] : []),
                  ...(item.detail.anomaly
                    ? [{ label: 'Anomaly', value: String(item.detail.anomaly) }]
                    : []),
                  ...(item.detail.finality ? [{ label: 'Finality', value: String(item.detail.finality) }] : []),
                ]}
              />
            </div>
          ))
        )}
      </div>
    </div>
  )
}

function AccountingTab({ payment }: { payment: PaymentDetail }) {
  const active = payment.accountingEntries.filter((entry) => entry.status !== 'REVERSED')
  const debits = active
    .filter((entry) => entry.side === 'DEBIT')
    .reduce((sum, entry) => sum + Number(entry.amount), 0)
  const credits = active
    .filter((entry) => entry.side === 'CREDIT')
    .reduce((sum, entry) => sum + Number(entry.amount), 0)
  const balanced = Math.abs(debits - credits) < 0.005

  return (
    <div className="col" style={{ padding: 'var(--s-5)' }}>
      {payment.accountingEntries.length > 0 && (
        <div className="row-wrap">
          <span className="label">Journal</span>
          <StatusChip
            value={balanced ? 'BALANCED' : 'OUT OF BALANCE'}
            mode="raw"
            tone={balanced ? 'ok' : 'error'}
          />
          <span className="num dim" style={{ fontSize: 'var(--fs-xs)' }}>
            debits {formatAmount(debits, payment.currency)} · credits{' '}
            {formatAmount(credits, payment.currency)}
          </span>
        </div>
      )}

      <DataTable
        columns={[
          { key: 'entry', header: 'Entry', render: (row) => <span className="mono">{row.entryId}</span> },
          {
            key: 'side',
            header: 'Side',
            render: (row) => (
              <span className="ledger-side" data-side={row.side}>
                {row.side}
              </span>
            ),
          },
          {
            key: 'account',
            header: 'Account',
            render: (row) => (
              <>
                <div className="cell-primary">{row.accountNumber}</div>
                <div className="cell-secondary">
                  {row.accountName} · {row.accountType}
                </div>
              </>
            ),
          },
          {
            key: 'amount',
            header: 'Amount',
            numeric: true,
            render: (row) => formatAmount(row.amount, row.currency),
          },
          {
            key: 'balance',
            header: 'Balance after',
            numeric: true,
            render: (row) => (row.balanceAfter ? formatAmount(row.balanceAfter, row.currency) : '—'),
          },
          {
            key: 'dates',
            header: 'Posting / value',
            render: (row) => (
              <>
                <div style={{ fontSize: 'var(--fs-xs)' }}>{formatDate(row.postingDate)}</div>
                <div className="cell-secondary">{formatDate(row.valueDate)}</div>
              </>
            ),
          },
          {
            key: 'status',
            header: 'Status',
            render: (row) => (
              <>
                <StatusChip value={row.status} mode="raw" />
                {row.anomalyNote && <div className="cell-secondary text-error">{row.anomalyNote}</div>}
              </>
            ),
          },
          { key: 'narrative', header: 'Narrative', render: (row) => row.narrative },
        ]}
        rows={payment.accountingEntries}
        rowKey={(row) => row.entryId}
        emptyTitle="No accounting entries"
        emptyBody="A journal is only posted once settlement has completed."
      />

      {payment.statementEntries.length > 0 && (
        <>
          <span className="label">Statement entries (camt.054 / camt.053)</span>
          <DataTable
            columns={[
              {
                key: 'reference',
                header: 'Entry reference',
                render: (row) => <span className="mono">{row.statementReference}</span>,
              },
              { key: 'account', header: 'Account', render: (row) => row.accountNumber },
              {
                key: 'side',
                header: 'Side',
                render: (row) => (
                  <span className="ledger-side" data-side={row.side}>
                    {row.side}
                  </span>
                ),
              },
              {
                key: 'amount',
                header: 'Amount',
                numeric: true,
                render: (row) => formatAmount(row.amount, row.currency),
              },
              { key: 'booking', header: 'Booked', render: (row) => formatDate(row.bookingDate) },
              {
                key: 'e2e',
                header: 'End-to-end id',
                render: (row) => <span className="mono">{row.endToEndId ?? '—'}</span>,
              },
              {
                key: 'source',
                header: 'Source',
                render: (row) => (
                  <>
                    <span className="tag">{row.sourceMessageType}</span>
                    {row.isOrphan && (
                      <div className="cell-secondary text-error">unmatched entry</div>
                    )}
                  </>
                ),
              },
            ]}
            rows={payment.statementEntries}
            rowKey={(row) => row.statementReference}
          />
        </>
      )}
    </div>
  )
}

function ReconciliationTab({ payment }: { payment: PaymentDetail }) {
  if (payment.reconciliationRecords.length === 0) {
    return (
      <Empty title="Reconciliation has not run">
        Reconciliation runs after accounting. A payment that never settled has nothing to reconcile.
      </Empty>
    )
  }
  return (
    <div className="col" style={{ padding: 'var(--s-5)' }}>
      {payment.reconciliationRecords.map((record) => (
        <div
          key={record.id}
          style={{ border: '1px solid var(--line)', borderRadius: 'var(--radius)', padding: 'var(--s-5)' }}
        >
          <div className="row-wrap" style={{ marginBottom: 'var(--s-4)' }}>
            <Link to={`/reconciliation/${record.reference}`} className="mono">
              {record.reference}
            </Link>
            <StatusChip value={record.status} mode="raw" tone={toneFor(record.status)} />
            <span className="dim mono" style={{ fontSize: 'var(--fs-micro)' }}>
              {formatDateTime(record.runAt)}
            </span>
          </div>

          <div className="legs" style={{ marginBottom: 'var(--s-5)' }}>
            {record.legs.map((leg) => (
              <div className="leg" key={leg.source} data-present={leg.present ? 'true' : 'false'}>
                <div className="leg-name">{leg.name}</div>
                <div className="leg-amount">
                  {leg.present ? formatAmount(leg.amount, leg.currency ?? undefined) : 'absent'}
                </div>
                <div className="cell-secondary mono" style={{ marginTop: 'var(--s-2)' }}>
                  {leg.reference ?? '—'}
                </div>
                <div className="cell-secondary" style={{ marginTop: 'var(--s-2)' }}>
                  {leg.note}
                </div>
              </div>
            ))}
          </div>

          <KeyValue
            items={[
              ...(record.differenceAmount
                ? [
                    {
                      label: 'Difference',
                      value: formatAmount(record.differenceAmount, record.internalCurrency ?? undefined),
                      mono: true,
                    },
                  ]
                : []),
              { label: 'Probable cause', value: record.probableCause },
              { label: 'Recommended action', value: record.recommendedAction },
            ]}
          />
        </div>
      ))}
    </div>
  )
}

function EventsTab({ payment }: { payment: PaymentDetail }) {
  const [filter, setFilter] = useState('')
  const rows = filter
    ? payment.events.filter(
        (event) =>
          event.eventType.toLowerCase().includes(filter.toLowerCase()) ||
          event.summary.toLowerCase().includes(filter.toLowerCase()) ||
          event.sourceSystem.toLowerCase().includes(filter.toLowerCase()),
      )
    : payment.events

  return (
    <div className="col" style={{ padding: 'var(--s-5) 0' }}>
      <div className="row-wrap" style={{ padding: '0 var(--s-5)' }}>
        <span className="label">Event log</span>
        <span className="dim mono" style={{ fontSize: 'var(--fs-micro)' }}>
          {payment.events.length} events
        </span>
        <span className="spacer" />
        <input
          type="search"
          placeholder="Filter events"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          style={{ maxWidth: 260 }}
        />
      </div>
      <div className="events">
        {rows.map((event) => (
          <div className="event-row" key={event.id}>
            <span className="severity" data-tone={severityTone(event.severity)} />
            <span className="event-time">{formatTime(event.occurredAt)}</span>
            <span className="event-source" title={`${event.sourceSystem} · ${event.eventType}`}>
              {event.sourceSystem}
            </span>
            <span className="event-summary">
              {event.summary}
              {event.stageKey && <span className="dim mono"> · {event.stageKey}</span>}
              {event.durationMs !== null && (
                <span className="dim mono"> · {formatDuration(event.durationMs)}</span>
              )}
            </span>
          </div>
        ))}
        {rows.length === 0 && <Empty title="No events match that filter" />}
      </div>
    </div>
  )
}

function TrackingTab({ reference }: { reference: string }) {
  const tracking = useAsync((signal) => api.paymentTracking(reference, signal), [reference])
  if (tracking.loading && !tracking.data) return <Loading rows={5} />
  if (tracking.error) return <ErrorState error={tracking.error} onRetry={tracking.reload} />
  const data = tracking.data
  if (!data) return null
  if (!data.supported) return <Empty title={data.note ?? 'Tracking is not available on this rail'} />

  return (
    <div className="col" style={{ padding: 'var(--s-5)' }}>
      <KeyValue
        items={[
          { label: 'UETR', value: data.uetr ?? '—', mono: true },
          { label: 'Current status', value: <StatusChip value={data.status ?? ''} /> },
        ]}
      />
      <div className="events" style={{ border: '1px solid var(--line)', borderRadius: 'var(--radius)' }}>
        {data.events.map((event, index) => (
          <div className="event-row" key={index}>
            <span className="severity" data-tone={severityTone(event.severity)} />
            <span className="event-time">{formatTime(event.at)}</span>
            <span className="event-source">{event.agent}</span>
            <span className="event-summary">
              {event.description}
              <span className="dim mono"> · {event.event}</span>
            </span>
          </div>
        ))}
      </div>
      {data.simulationNote && <SimulationNote>{data.simulationNote}</SimulationNote>}
    </div>
  )
}

function MtMxTab({ payment }: { payment: PaymentDetail }) {
  const rows = payment.mtMxMapping
  if (rows.length === 0) {
    return <Empty title="MT to MX mapping applies to cross-border payments only" />
  }
  return (
    <div className="col" style={{ padding: 'var(--s-5)' }}>
      <SimulationNote>
        There is no universal one-to-one MT to MX mapping. Each row states whether the mapping is
        direct, transformed, derived, or has no equivalent at all.
      </SimulationNote>
      <DataTable
        columns={[
          {
            key: 'mt',
            header: 'MT103 field',
            render: (row) => (
              <>
                <div className="cell-primary">{row.mtTag}</div>
                <div className="cell-secondary">{row.mtName}</div>
              </>
            ),
          },
          { key: 'arrow', header: '', render: () => <span className="mapping-arrow">→</span> },
          {
            key: 'mx',
            header: 'pacs.008 element',
            render: (row) => (
              <span className="mono" style={{ fontSize: 'var(--fs-xs)' }}>
                {row.mxPath}
              </span>
            ),
          },
          {
            key: 'values',
            header: 'This payment',
            render: (row) =>
              row.mtValue || row.mxValue ? (
                <div className="col-tight mono" style={{ fontSize: 'var(--fs-xs)' }}>
                  <span>MT: {row.mtValue ?? '—'}</span>
                  <span className="dim">MX: {row.mxValue ?? '—'}</span>
                </div>
              ) : (
                <span className="dim">—</span>
              ),
          },
          {
            key: 'type',
            header: 'Mapping',
            render: (row) => (
              <>
                <span className="mapping-type" data-kind={row.mappingType}>
                  {row.mappingType}
                </span>
                {row.note && <div className="cell-secondary">{row.note}</div>}
              </>
            ),
          },
        ]}
        rows={rows}
        rowKey={(row) => row.mtTag}
      />
    </div>
  )
}

function ActionDrawer({
  kind,
  reference,
  onClose,
  onDone,
}: {
  kind: 'retry' | 'cancel' | 'return' | 'timeout'
  reference: string
  onClose: () => void
  onDone: () => void
  navigate: ReturnType<typeof useNavigate>
}) {
  const [reason, setReason] = useState('')
  const [reasonCode, setReasonCode] = useState(kind === 'return' ? 'AC04' : 'CUST')
  const [accepted, setAccepted] = useState(true)

  const action = useAction(
    async () => {
      switch (kind) {
        case 'retry':
          return api.retryPayment(reference, { reason, processingMode: 'IMMEDIATE' })
        case 'cancel':
          return api.cancelPayment(reference, { reasonCode, narrative: reason })
        case 'return':
          return api.returnPayment(reference, { reasonCode, narrative: reason })
        case 'timeout':
          return api.resolveTimeout(reference, {
            accepted,
            reasonCode: accepted ? null : reasonCode,
          })
      }
    },
    { onSuccess: onDone },
  )

  const titles = {
    retry: 'Reprocess the payment',
    cancel: 'Request cancellation (camt.056)',
    return: 'Apply an inbound return (pacs.004)',
    timeout: 'Apply the clearing system’s answer',
  }
  const explanation = {
    retry:
      'Reprocessing re-runs the lifecycle for real. If the underlying data is still wrong the payment will fail again — a retry is not a way to force a success.',
    cancel:
      'A cancellation request is a request, not a guarantee. The beneficiary side decides, and the camt.029 resolution records the answer. Once value has moved the recall is normally refused.',
    return:
      'The beneficiary bank returns the funds. The journal is reversed, the settlement is marked reversed and the payment moves to RETURNED.',
    timeout:
      'The clearing system has finally answered the pacs.028 status request. Applying a positive answer continues the lifecycle from settlement; a negative answer rejects the payment and reverses any debit.',
  }

  return (
    <Drawer title={titles[kind]} subtitle={reference} onClose={onClose}>
      <form
        className="col"
        onSubmit={(event) => {
          event.preventDefault()
          void action.run()
        }}
      >
        <Notice tone="info">{explanation[kind]}</Notice>
        {action.error && <ErrorState error={action.error} />}

        {kind === 'timeout' && (
          <Field label="What did the clearing system say?">
            <select
              value={accepted ? 'accepted' : 'rejected'}
              onChange={(event) => setAccepted(event.target.value === 'accepted')}
            >
              <option value="accepted">Accepted (ACSC) — the payment was processed</option>
              <option value="rejected">Rejected (RJCT) — the payment was not processed</option>
            </select>
          </Field>
        )}

        {(kind === 'cancel' || kind === 'return' || (kind === 'timeout' && !accepted)) && (
          <Field label="Reason code" hint="ISO 20022 external code">
            <select value={reasonCode} onChange={(event) => setReasonCode(event.target.value)}>
              {(kind === 'cancel'
                ? [
                    ['CUST', 'CUST — requested by the customer'],
                    ['DUPL', 'DUPL — duplicate payment'],
                    ['TECH', 'TECH — technical problem'],
                    ['FRAD', 'FRAD — fraudulent payment'],
                    ['CUTA', 'CUTA — cancellation pending investigation'],
                    ['UPAY', 'UPAY — payment not justified'],
                  ]
                : [
                    ['AC04', 'AC04 — creditor account closed'],
                    ['AC01', 'AC01 — creditor account invalid'],
                    ['AC06', 'AC06 — creditor account blocked'],
                    ['BE01', 'BE01 — name and account do not match'],
                    ['RR04', 'RR04 — regulatory reason'],
                    ['CUST', 'CUST — requested by the customer'],
                  ]
              ).map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
        )}

        <Field
          label={kind === 'retry' ? 'Reason for reprocessing' : 'Narrative'}
          required={kind === 'retry'}
          hint="Recorded on the audit trail and on any open investigation"
        >
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={3}
            required={kind === 'retry'}
            minLength={kind === 'retry' ? 3 : undefined}
          />
        </Field>

        <div className="row-tight">
          <button type="submit" className="btn" data-variant="primary" disabled={action.pending}>
            {action.pending ? 'Working…' : 'Confirm'}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Drawer>
  )
}
