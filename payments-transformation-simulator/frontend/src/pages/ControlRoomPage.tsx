/**
 * Control room: the operational posture of the simulated book plus the demo
 * launchers. Deliberately not a KPI wall — every number here is a queue an
 * operator would actually work.
 */

import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import type { DemoButton, PaymentSummary } from '../api/types'
import { useAction, useAsync, usePolling } from '../hooks/useAsync'
import { formatAmount, relativeTime, schemeLabel } from '../lib/format'
import {
  Bar,
  DataTable,
  ErrorState,
  Loading,
  Metric,
  Notice,
  PageHeader,
  Panel,
  SimulationNote,
  StatusChip,
  type Column,
} from '../components/ui'

export function ControlRoomPage() {
  const navigate = useNavigate()
  const [running, setRunning] = useState<string | null>(null)
  const [lastRun, setLastRun] = useState<{ label: string; reference: string; passed: boolean } | null>(
    null,
  )

  const stats = useAsync((signal) => api.statistics(signal), [])
  const demo = useAsync((signal) => api.demo(signal), [])
  const recent = useAsync(
    (signal) => api.listPayments({ pageSize: 12, sort: 'updatedAt' }, signal),
    [],
  )
  const exceptions = useAsync((signal) => api.exceptions(signal), [])
  usePolling(() => {
    stats.reload()
    recent.reload()
  }, 12000, true)

  const runDemo = useAction(
    (button: DemoButton) => api.runScenario(button.scenarioCode, { processingMode: 'IMMEDIATE' }),
    {
      onSuccess: (result) => {
        setLastRun({
          label: result.scenario.title,
          reference: result.payment.reference,
          passed: result.passed,
        })
        setRunning(null)
        stats.reload()
        recent.reload()
        exceptions.reload()
      },
      onError: () => setRunning(null),
    },
  )

  const columns: Column<PaymentSummary>[] = [
    {
      key: 'reference',
      header: 'Reference',
      render: (row) => (
        <>
          <div className="cell-primary">{row.reference}</div>
          <div className="cell-secondary">{relativeTime(row.updatedAt)}</div>
        </>
      ),
    },
    {
      key: 'scheme',
      header: 'Rail',
      render: (row) => <span className="tag">{schemeLabel(row.scheme)}</span>,
    },
    {
      key: 'parties',
      header: 'Debtor → Creditor',
      render: (row) => (
        <>
          <div className="truncate">{row.debtorName}</div>
          <div className="cell-secondary truncate">→ {row.creditorName}</div>
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
      key: 'status',
      header: 'Status',
      render: (row) => (
        <>
          <StatusChip value={row.status} />
          {row.failureSummary && (
            <div className="cell-secondary truncate" style={{ maxWidth: 320 }}>
              {row.failureSummary}
            </div>
          )}
        </>
      ),
    },
  ]

  return (
    <div className="page">
      <PageHeader
        eyebrow="Payments operations"
        title="Control room"
        lede="Observe. Execute. Break. Investigate. Reconcile. Everything on this screen is produced by the simulator's own engines against fictional data."
        actions={
          <>
            <Link className="btn" data-variant="primary" to="/payments/new">
              New payment
            </Link>
            <Link className="btn" to="/qa/scenarios">
              Scenario library
            </Link>
          </>
        }
      />

      <div className="stack">
        {stats.error && <ErrorState error={stats.error} onRetry={stats.reload} />}

        {stats.data && (
          <div className="metrics">
            <Metric
              label="Payments in book"
              value={stats.data.totalPayments}
              note={`${stats.data.createdLast24h} created in the last 24 hours`}
            />
            <Metric
              label="Straight through"
              value={`${stats.data.successRate}%`}
              tone={stats.data.successRate > 60 ? 'ok' : 'warn'}
              note={
                <Bar
                  value={stats.data.totalPayments - stats.data.failureCount}
                  max={Math.max(1, stats.data.totalPayments)}
                  tone="ok"
                />
              }
            />
            <Metric
              label="In a failure state"
              value={stats.data.failureCount}
              tone={stats.data.failureCount > 0 ? 'error' : undefined}
              note="Payments that need a decision"
            />
            <Metric
              label="Open investigations"
              value={stats.data.openInvestigations}
              tone={stats.data.openInvestigations > 0 ? 'investigate' : undefined}
              note="Assigned to payment operations"
            />
            <Metric
              label="Reconciliation breaks"
              value={stats.data.reconciliationBreaks}
              tone={stats.data.reconciliationBreaks > 0 ? 'error' : undefined}
              note={`${stats.data.unmatchedStatementEntries} unmatched statement entries`}
            />
            <Metric
              label="Clearing latency"
              value={
                stats.data.averageClearingLatencyMs !== null
                  ? `${stats.data.averageClearingLatencyMs} ms`
                  : '—'
              }
              note="Mean pacs.002 response time"
            />
          </div>
        )}

        <div className="grid grid-main-aside">
          <Panel
            title="Recent activity"
            subtitle="Most recently updated payments"
            flush
            actions={
              <Link className="btn" data-size="sm" to="/payments">
                Open payment search
              </Link>
            }
          >
            {recent.loading && !recent.data ? (
              <Loading rows={6} />
            ) : recent.error ? (
              <div style={{ padding: 'var(--s-5)' }}>
                <ErrorState error={recent.error} onRetry={recent.reload} />
              </div>
            ) : (
              <DataTable
                columns={columns}
                rows={recent.data?.items ?? []}
                rowKey={(row) => row.reference}
                onRowClick={(row) => navigate(`/payments/${row.reference}`)}
                emptyTitle="No payments yet"
                emptyBody="Create a payment or run a scenario to populate the book."
              />
            )}
          </Panel>

          <div className="stack">
            <Panel
              title="Demo mode"
              subtitle="Each button runs the real lifecycle, not an animation"
            >
              <div className="col">
                {lastRun && (
                  <Notice tone={lastRun.passed ? 'ok' : 'warn'} title={lastRun.label}>
                    Produced{' '}
                    <Link to={`/payments/${lastRun.reference}`} className="mono">
                      {lastRun.reference}
                    </Link>
                    {lastRun.passed
                      ? ' and every expectation in the scenario was met.'
                      : ' but at least one expectation was not met — open the scenario to see which.'}
                  </Notice>
                )}
                {runDemo.error && <ErrorState error={runDemo.error} />}
                {demo.loading && !demo.data && <Loading rows={4} />}
                <div className="col-tight">
                  {(demo.data?.buttons ?? []).map((button) => (
                    <button
                      key={button.id}
                      type="button"
                      className="btn"
                      style={{ justifyContent: 'flex-start', textAlign: 'left', height: 'auto', padding: 'var(--s-4) var(--s-5)' }}
                      disabled={runDemo.pending}
                      onClick={() => {
                        setRunning(button.id)
                        void runDemo.run(button)
                      }}
                    >
                      <span style={{ minWidth: 0 }}>
                        <span style={{ display: 'block' }}>
                          {running === button.id && runDemo.pending ? 'Running…' : button.label}
                        </span>
                        <span
                          className="dim"
                          style={{ display: 'block', fontSize: 'var(--fs-xs)', fontWeight: 400 }}
                        >
                          {button.description}
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            </Panel>

            <Panel title="Queues" subtitle="What needs a person">
              <div className="col-tight">
                <QueueRow
                  to="/investigations"
                  label="Investigations to work"
                  value={exceptions.data?.summary.openInvestigations ?? 0}
                />
                <QueueRow
                  to="/reconciliation"
                  label="Reconciliation breaks"
                  value={exceptions.data?.summary.reconciliationBreaks ?? 0}
                />
                <QueueRow
                  to="/exceptions"
                  label="Payments in exception"
                  value={exceptions.data?.summary.failedPayments ?? 0}
                />
                <QueueRow
                  to="/reconciliation"
                  label="Unmatched statement entries"
                  value={exceptions.data?.summary.unmatchedStatementEntries ?? 0}
                />
              </div>
            </Panel>

            {stats.data && (
              <Panel title="Book composition">
                <div className="col">
                  <div>
                    <div className="label" style={{ marginBottom: 'var(--s-3)' }}>
                      By rail
                    </div>
                    <div className="col-tight">
                      {Object.entries(stats.data.byScheme).map(([scheme, count]) => (
                        <div className="row-tight" key={scheme}>
                          <span style={{ flex: '0 0 110px', fontSize: 'var(--fs-xs)' }}>
                            {schemeLabel(scheme)}
                          </span>
                          <span style={{ flex: 1 }}>
                            <Bar value={count} max={stats.data!.totalPayments} />
                          </span>
                          <span className="num dim" style={{ flex: '0 0 28px', textAlign: 'right' }}>
                            {count}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="label" style={{ marginBottom: 'var(--s-3)' }}>
                      By currency
                    </div>
                    <div className="col-tight">
                      {stats.data.byCurrency.map((row) => (
                        <div className="row-tight" key={row.currency}>
                          <span className="mono" style={{ flex: '0 0 46px', fontSize: 'var(--fs-xs)' }}>
                            {row.currency}
                          </span>
                          <span className="num dim" style={{ flex: 1, fontSize: 'var(--fs-xs)' }}>
                            {formatAmount(row.total, row.currency)}
                          </span>
                          <span className="num dim" style={{ flex: '0 0 28px', textAlign: 'right' }}>
                            {row.count}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </Panel>
            )}
          </div>
        </div>

        <SimulationNote>
          This application simulates payment processing. Banks, BICs, IBANs, accounts, references and
          screening lists are fictional. It is standards-inspired but is not an implementation of any
          bank, SWIFT, SIC, SEPA or clearing system.
        </SimulationNote>
      </div>
    </div>
  )
}

function QueueRow({ to, label, value }: { to: string; label: string; value: number }) {
  return (
    <Link
      to={to}
      className="row"
      style={{
        padding: 'var(--s-3) var(--s-4)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius)',
        background: value > 0 ? 'var(--surface-2)' : 'transparent',
        color: 'var(--text-primary)',
        textDecoration: 'none',
      }}
    >
      <span style={{ fontSize: 'var(--fs-sm)' }}>{label}</span>
      <span className="spacer" />
      <span
        className="num"
        style={{
          fontSize: 'var(--fs-md)',
          color: value > 0 ? 'var(--warn)' : 'var(--text-tertiary)',
        }}
      >
        {value}
      </span>
    </Link>
  )
}
