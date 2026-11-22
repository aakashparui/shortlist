/** Everything currently in an exception state, in one place. */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import { useAsync, usePolling } from '../hooks/useAsync'
import { formatAmount, formatDate, relativeTime, schemeLabel } from '../lib/format'
import {
  DataTable,
  ErrorState,
  Loading,
  Metric,
  PageHeader,
  Panel,
  StatusChip,
  Tabs,
} from '../components/ui'

export function ExceptionsPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<'payments' | 'breaks' | 'investigations' | 'statements'>('payments')
  const data = useAsync((signal) => api.exceptions(signal), [])
  usePolling(() => data.reload(), 15000, true)

  if (data.loading && !data.data) {
    return (
      <div className="page">
        <Loading rows={8} label="Loading exceptions" />
      </div>
    )
  }
  if (data.error) {
    return (
      <div className="page">
        <PageHeader eyebrow="Operations" title="Exceptions" />
        <ErrorState error={data.error} onRetry={data.reload} />
      </div>
    )
  }
  const overview = data.data
  if (!overview) return null

  return (
    <div className="page">
      <PageHeader
        eyebrow="Operations"
        title="Exceptions"
        lede="The work queue. Every item here is a payment, a break or a case that the lifecycle could not resolve on its own."
      />

      <div className="stack">
        <div className="metrics">
          <Metric
            label="Payments in exception"
            value={overview.summary.failedPayments}
            tone={overview.summary.failedPayments > 0 ? 'error' : undefined}
          />
          <Metric
            label="Reconciliation breaks"
            value={overview.summary.reconciliationBreaks}
            tone={overview.summary.reconciliationBreaks > 0 ? 'error' : undefined}
          />
          <Metric
            label="Open investigations"
            value={overview.summary.openInvestigations}
            tone={overview.summary.openInvestigations > 0 ? 'investigate' : undefined}
          />
          <Metric
            label="Unmatched statement entries"
            value={overview.summary.unmatchedStatementEntries}
            tone={overview.summary.unmatchedStatementEntries > 0 ? 'warn' : undefined}
          />
        </div>

        {Object.keys(overview.summary.byStatus).length > 0 && (
          <div className="row-wrap">
            {Object.entries(overview.summary.byStatus)
              .sort((a, b) => b[1] - a[1])
              .map(([status, count]) => (
                <span className="row-tight" key={status}>
                  <StatusChip value={status} mode="raw" />
                  <span className="num dim">{count}</span>
                </span>
              ))}
          </div>
        )}

        <Panel flush>
          <Tabs
            tabs={[
              { id: 'payments', label: 'Payments', count: overview.payments.length },
              { id: 'breaks', label: 'Reconciliation breaks', count: overview.reconciliationBreaks.length },
              { id: 'investigations', label: 'Investigations', count: overview.investigations.length },
              {
                id: 'statements',
                label: 'Unmatched statement entries',
                count: overview.unmatchedStatementEntries.length,
              },
            ]}
            active={tab}
            onChange={(id) => setTab(id as typeof tab)}
          />

          {tab === 'payments' && (
            <DataTable
              columns={[
                {
                  key: 'reference',
                  header: 'Payment',
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
                  key: 'amount',
                  header: 'Amount',
                  numeric: true,
                  render: (row) => formatAmount(row.amount, row.currency),
                },
                { key: 'status', header: 'Status', render: (row) => <StatusChip value={row.status} /> },
                {
                  key: 'why',
                  header: 'Why it stopped',
                  render: (row) => row.failureSummary ?? '—',
                },
              ]}
              rows={overview.payments}
              rowKey={(row) => row.reference}
              onRowClick={(row) => navigate(`/payments/${row.reference}`)}
              emptyTitle="No payments in an exception state"
            />
          )}

          {tab === 'breaks' && (
            <DataTable
              columns={[
                {
                  key: 'reference',
                  header: 'Record',
                  render: (row) => <span className="mono">{row.reference}</span>,
                },
                {
                  key: 'payment',
                  header: 'Payment',
                  render: (row) => <span className="mono">{row.paymentReference ?? '—'}</span>,
                },
                { key: 'status', header: 'Classification', render: (row) => <StatusChip value={row.status} mode="raw" /> },
                {
                  key: 'internal',
                  header: 'Internal',
                  numeric: true,
                  render: (row) => formatAmount(row.internalAmount, row.internalCurrency ?? undefined),
                },
                {
                  key: 'statement',
                  header: 'Statement',
                  numeric: true,
                  render: (row) =>
                    row.statementAmount
                      ? formatAmount(row.statementAmount, row.statementCurrency ?? undefined)
                      : 'absent',
                },
                {
                  key: 'difference',
                  header: 'Difference',
                  numeric: true,
                  render: (row) =>
                    row.differenceAmount
                      ? formatAmount(row.differenceAmount, row.internalCurrency ?? undefined)
                      : '—',
                },
                { key: 'cause', header: 'Probable cause', render: (row) => row.probableCause },
              ]}
              rows={overview.reconciliationBreaks}
              rowKey={(row) => row.reference}
              onRowClick={(row) => navigate(`/reconciliation/${row.reference}`)}
              emptyTitle="No open reconciliation breaks"
            />
          )}

          {tab === 'investigations' && (
            <DataTable
              columns={[
                {
                  key: 'reference',
                  header: 'Investigation',
                  render: (row) => <span className="mono">{row.reference}</span>,
                },
                {
                  key: 'priority',
                  header: 'Priority',
                  render: (row) => (
                    <StatusChip
                      value={row.priority}
                      mode="raw"
                      tone={row.priority === 'HIGH' ? 'error' : 'warn'}
                    />
                  ),
                },
                { key: 'title', header: 'Issue', render: (row) => row.title },
                { key: 'reason', header: 'Reason', render: (row) => <span className="tag">{row.reason}</span> },
                {
                  key: 'payment',
                  header: 'Payment',
                  render: (row) => <span className="mono">{row.paymentReference ?? '—'}</span>,
                },
                { key: 'age', header: 'Open for', render: (row) => relativeTime(row.openedAt) },
              ]}
              rows={overview.investigations}
              rowKey={(row) => row.reference}
              onRowClick={(row) => navigate(`/investigations/${row.reference}`)}
              emptyTitle="No open investigations"
            />
          )}

          {tab === 'statements' && (
            <DataTable
              columns={[
                {
                  key: 'reference',
                  header: 'Entry',
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
                  header: 'Reference on the statement',
                  render: (row) => <span className="mono">{row.endToEndId ?? '—'}</span>,
                },
                { key: 'narrative', header: 'Narrative', render: (row) => row.narrative },
              ]}
              rows={overview.unmatchedStatementEntries}
              rowKey={(row) => row.statementReference}
              emptyTitle="Every statement entry is matched"
              emptyBody="An unmatched entry is a movement on the account with no internal payment record."
            />
          )}
        </Panel>
      </div>
    </div>
  )
}
