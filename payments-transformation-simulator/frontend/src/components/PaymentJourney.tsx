/**
 * The payment journey: a process graph, not a row of cards.
 *
 * Each node is a real stage with a real persisted state. Opening a node shows
 * what that stage actually did — the rules it ran, the message it produced, the
 * references it created — and, when it failed, what happened, where, why, what
 * state the payment entered and what can be done next.
 */

import { useState } from 'react'

import type { PaymentDetail, Stage, ValidationResult } from '../api/types'
import { formatDuration, formatTime, toneFor } from '../lib/format'
import { JsonBlock, KeyValue, StatusChip } from './ui'
import { useViewMode } from './ViewModeContext'

const FAILED_STATES = new Set(['REJECTED', 'FAILED', 'TIMED_OUT', 'INVESTIGATION_REQUIRED', 'REVERSED'])

export function PaymentJourney({
  payment,
  onOpenMessage,
}: {
  payment: PaymentDetail
  onOpenMessage?: (messageId: string) => void
}) {
  const { mode, isTechnical } = useViewMode()
  const failedStage = payment.stages.find((stage) => FAILED_STATES.has(stage.state))
  const [open, setOpen] = useState<string | null>(failedStage?.stageKey ?? null)

  const stages = [...payment.stages].sort((a, b) => a.sequence - b.sequence)
  const completed = stages.filter((s) => s.state === 'COMPLETED').length

  return (
    <div className="col">
      <div className="row-wrap" style={{ padding: '0 var(--s-5)' }}>
        <span className="label">Journey</span>
        <span className="dim mono" style={{ fontSize: 'var(--fs-micro)' }}>
          {completed} of {stages.length} stages completed
        </span>
        <span className="spacer" />
        <span className="dim" style={{ fontSize: 'var(--fs-xs)' }}>
          Select a stage to see what it did
        </span>
      </div>

      <ol className="journey" style={{ listStyle: 'none', margin: 0, padding: 'var(--s-4) var(--s-5)' }}>
        {stages.map((stage) => {
          const expanded = open === stage.stageKey
          const label = isTechnical ? stage.technicalLabel : stage.businessLabel
          return (
            <li className="journey-node" data-state={stage.state} key={stage.stageKey}>
              <div className="journey-rail" aria-hidden="true">
                <span className="journey-dot" />
                <span className="journey-line" />
              </div>
              <div className="journey-body">
                <button
                  type="button"
                  className="journey-head"
                  aria-expanded={expanded}
                  onClick={() => setOpen(expanded ? null : stage.stageKey)}
                >
                  <span className="journey-stage">{label}</span>
                  <StatusChip value={stage.state} mode="raw" tone={toneFor(stage.state)} />
                  {isTechnical && <span className="journey-owner">{stage.ownerSystem}</span>}
                  <span className="spacer" />
                  {stage.durationMs !== null && (
                    <span className="journey-duration">{formatDuration(stage.durationMs)}</span>
                  )}
                  {stage.startedAt && isTechnical && (
                    <span className="journey-duration">{formatTime(stage.startedAt)}</span>
                  )}
                </button>
                {stage.summary && !expanded && <div className="journey-summary">{stage.summary}</div>}
                {expanded && (
                  <div className="journey-detail">
                    <StageDetail
                      stage={stage}
                      payment={payment}
                      technical={mode === 'technical'}
                      onOpenMessage={onOpenMessage}
                    />
                  </div>
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function StageDetail({
  stage,
  payment,
  technical,
  onOpenMessage,
}: {
  stage: Stage
  payment: PaymentDetail
  technical: boolean
  onOpenMessage?: (messageId: string) => void
}) {
  const detail = stage.detail ?? {}
  const results = (detail.results as ValidationResult[] | undefined) ?? []
  const failed = FAILED_STATES.has(stage.state)

  return (
    <div className="col" style={{ padding: 'var(--s-5)' }}>
      {stage.summary && <div>{stage.summary}</div>}

      {failed && <FailureReport stage={stage} payment={payment} />}

      {results.length > 0 && <ValidationList results={results} />}

      {Array.isArray(detail.checks) && (detail.checks as unknown[]).length > 0 && (
        <MessageChecks checks={detail.checks as { ruleId: string; ruleName: string; status: string; message: string }[]} />
      )}

      {Array.isArray(detail.hits) && (detail.hits as unknown[]).length > 0 && (
        <ComplianceHits hits={detail.hits as ComplianceHit[]} />
      )}

      {Array.isArray(detail.entries) && (detail.entries as unknown[]).length > 0 && (
        <JournalPreview entries={detail.entries as JournalEntry[]} />
      )}

      {Array.isArray(detail.legs) && (detail.legs as unknown[]).length > 0 && (
        <LegsPreview legs={detail.legs as Leg[]} />
      )}

      {Boolean(detail.messageId) && (
        <div className="row-wrap">
          <span className="label">Message</span>
          <span className="mono">{String(detail.messageId)}</span>
          {onOpenMessage && (
            <button
              type="button"
              className="btn"
              data-size="sm"
              onClick={() => onOpenMessage(String(detail.messageId))}
            >
              Inspect
            </button>
          )}
        </div>
      )}

      <StageFacts stage={stage} />

      {technical && Object.keys(detail).length > 0 && (
        <details>
          <summary className="label" style={{ cursor: 'pointer' }}>
            Raw stage detail
          </summary>
          <div style={{ marginTop: 'var(--s-4)' }}>
            <JsonBlock value={detail} />
          </div>
        </details>
      )}
    </div>
  )
}

function StageFacts({ stage }: { stage: Stage }) {
  const detail = stage.detail ?? {}
  const interesting: [string, string][] = []
  const push = (label: string, key: string) => {
    const value = detail[key]
    if (value === undefined || value === null || typeof value === 'object') return
    interesting.push([label, String(value)])
  }
  push('Clearing reference', 'clearingReference')
  push('Clearing system', 'clearingSystem')
  push('Settlement reference', 'settlementReference')
  push('Settlement status', 'status')
  push('Accounting reference', 'accountingReference')
  push('Reconciliation reference', 'reference')
  push('Value date', 'valueDate')
  push('Response latency (ms)', 'latencyMs')
  push('Timeout threshold (s)', 'timeoutSeconds')
  push('Scheme threshold (s)', 'realisticTimeoutSeconds')
  push('Correlation id', 'correlationId')
  push('End-to-end id', 'endToEndId')
  push('UETR', 'uetr')
  push('Difference amount', 'differenceAmount')
  if (interesting.length === 0) return null
  return (
    <KeyValue
      items={interesting.map(([label, value]) => ({ label, value, mono: true }))}
    />
  )
}

function FailureReport({ stage, payment }: { stage: Stage; payment: PaymentDetail }) {
  const detail = stage.detail ?? {}
  const investigation = payment.investigations[0]
  const message =
    payment.messages.find((m) => m.messageId === detail.messageId) ??
    payment.messages[payment.messages.length - 1]

  return (
    <div className="failure-report">
      <div className="failure-report-header">
        {stage.state === 'TIMED_OUT' ? 'CLEARING TIMEOUT' : `${stage.stageKey} FAILURE`}
      </div>
      <div style={{ padding: 'var(--s-5)' }}>
        <KeyValue
          items={[
            { label: 'What happened', value: stage.summary || '—' },
            { label: 'Where', value: stage.stageKey, mono: true },
            { label: 'Why', value: stage.failureReason || investigation?.probableCause || '—' },
            {
              label: 'Expected',
              value: (detail.expected as string) ?? investigation?.expectedBehaviour ?? '—',
            },
            { label: 'Actual', value: (detail.actual as string) ?? investigation?.actualBehaviour ?? '—' },
            {
              label: 'ISO reason code',
              value: stage.isoReasonCode ?? (detail.reasonCode as string) ?? '—',
              mono: true,
            },
            {
              label: 'Message generated',
              value: message ? `${message.messageType} ${message.messageId}` : 'none',
              mono: true,
            },
            { label: 'Payment state', value: <StatusChip value={payment.status} />, mono: false },
            {
              label: 'Next possible action',
              value: investigation?.recommendedAction ?? nextActionFor(payment.status),
            },
          ]}
        />
      </div>
    </div>
  )
}

function nextActionFor(status: string): string {
  switch (status) {
    case 'REJECTED':
      return 'Correct the instruction data and reprocess the payment.'
    case 'BLOCKED':
      return 'Financial-crime analyst to disposition the screening alert.'
    case 'CLEARING_REJECTED':
      return 'Inform the customer, confirm the reversal, and re-instruct if appropriate.'
    case 'TIMED_OUT':
    case 'INVESTIGATION_REQUIRED':
      return 'Work the investigation. Do not re-send the instruction until the real status is known.'
    case 'ACCOUNTING_BREAK':
      return 'Correct the journal before the payment is closed.'
    case 'RECONCILIATION_BREAK':
      return 'Resolve the reconciliation break, then re-run reconciliation.'
    default:
      return 'Review the event log for the full sequence.'
  }
}

function ValidationList({ results }: { results: ValidationResult[] }) {
  const failures = results.filter((r) => r.status === 'FAILED')
  const [showAll, setShowAll] = useState(failures.length === 0)
  const visible = showAll ? results : failures.length > 0 ? failures : results.slice(0, 5)

  return (
    <div className="col-tight">
      <div className="row-tight">
        <span className="label">Rules executed</span>
        <span className="dim mono" style={{ fontSize: 'var(--fs-micro)' }}>
          {results.length} total · {failures.length} failed
        </span>
        <span className="spacer" />
        <button
          type="button"
          className="btn"
          data-variant="quiet"
          data-size="sm"
          onClick={() => setShowAll(!showAll)}
        >
          {showAll ? 'Show failures only' : 'Show all'}
        </button>
      </div>
      <div className="table-wrap" style={{ border: '1px solid var(--line)', borderRadius: 'var(--radius)' }}>
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Rule</th>
              <th scope="col">Outcome</th>
              <th scope="col">Detail</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((result) => (
              <tr key={`${result.ruleId}-${result.id}`}>
                <td>
                  <div className="cell-primary">{result.ruleId}</div>
                  <div className="cell-secondary">{result.ruleName}</div>
                </td>
                <td>
                  <StatusChip value={result.status} mode="raw" />
                  {result.isoReasonCode && (
                    <div className="cell-secondary mono">{result.isoReasonCode}</div>
                  )}
                </td>
                <td>
                  <div>{result.message}</div>
                  {(result.actualValue || result.expectedValue) && (
                    <div className="cell-secondary mono">
                      actual: {result.actualValue ?? '—'} · expected: {result.expectedValue ?? '—'}
                    </div>
                  )}
                  {result.status === 'FAILED' && result.remediation && (
                    <div className="cell-secondary">→ {result.remediation}</div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function MessageChecks({
  checks,
}: {
  checks: { ruleId: string; ruleName: string; status: string; message: string }[]
}) {
  const failures = checks.filter((c) => c.status === 'FAILED')
  return (
    <div className="col-tight">
      <span className="label">Message validation</span>
      <div className="row-tight">
        <StatusChip value={failures.length === 0 ? 'PASSED' : 'FAILED'} mode="raw" />
        <span className="dim" style={{ fontSize: 'var(--fs-xs)' }}>
          {checks.length} field checks, {failures.length} failed
        </span>
      </div>
      {failures.length > 0 && (
        <ul className="muted" style={{ fontSize: 'var(--fs-xs)' }}>
          {failures.map((check) => (
            <li key={check.ruleId}>
              <span className="mono">{check.ruleId}</span> — {check.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

interface ComplianceHit {
  ruleId: string
  matchValue: string
  listReference: string
  detail: string
  blocking: boolean
}

function ComplianceHits({ hits }: { hits: ComplianceHit[] }) {
  return (
    <div className="col-tight">
      <span className="label">Screening hits</span>
      <div className="table-wrap" style={{ border: '1px solid var(--line)', borderRadius: 'var(--radius)' }}>
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Rule</th>
              <th scope="col">Matched value</th>
              <th scope="col">List reference</th>
              <th scope="col">Effect</th>
            </tr>
          </thead>
          <tbody>
            {hits.map((hit, index) => (
              <tr key={index}>
                <td className="mono">{hit.ruleId}</td>
                <td className="mono">{hit.matchValue}</td>
                <td className="mono cell-secondary">{hit.listReference}</td>
                <td>
                  <StatusChip
                    value={hit.blocking ? 'BLOCKED' : 'WARNING'}
                    mode="raw"
                    tone={hit.blocking ? 'error' : 'warn'}
                  />
                  <div className="cell-secondary">{hit.detail}</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

interface JournalEntry {
  entryId: string
  side: 'DEBIT' | 'CREDIT'
  accountNumber: string
  accountName: string
  accountType: string
  amount: string
  currency: string
  status: string
  narrative: string
}

function JournalPreview({ entries }: { entries: JournalEntry[] }) {
  return (
    <div className="col-tight">
      <span className="label">Journal</span>
      <div className="table-wrap" style={{ border: '1px solid var(--line)', borderRadius: 'var(--radius)' }}>
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Entry</th>
              <th scope="col">Side</th>
              <th scope="col">Account</th>
              <th scope="col" className="num">
                Amount
              </th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr key={entry.entryId}>
                <td className="mono">{entry.entryId}</td>
                <td>
                  <span className="ledger-side" data-side={entry.side}>
                    {entry.side}
                  </span>
                </td>
                <td>
                  <div className="cell-primary">{entry.accountNumber}</div>
                  <div className="cell-secondary">
                    {entry.accountName} · {entry.accountType}
                  </div>
                </td>
                <td className="num">
                  {entry.amount} {entry.currency}
                </td>
                <td>
                  <StatusChip value={entry.status} mode="raw" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

interface Leg {
  name: string
  source: string
  reference: string | null
  amount: string | null
  currency: string | null
  present: boolean
  note: string
}

function LegsPreview({ legs }: { legs: Leg[] }) {
  return (
    <div className="col-tight">
      <span className="label">Reconciliation legs</span>
      <div className="legs">
        {legs.map((leg) => (
          <div className="leg" key={leg.source} data-present={leg.present ? 'true' : 'false'}>
            <div className="leg-name">{leg.name}</div>
            <div className="leg-amount">
              {leg.present ? `${leg.amount ?? '—'} ${leg.currency ?? ''}` : 'absent'}
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
    </div>
  )
}
