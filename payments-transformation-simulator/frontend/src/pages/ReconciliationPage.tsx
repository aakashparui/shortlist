/** Reconciliation: records, the classification reference and the statement feed. */

import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { api } from '../api/client'
import { useAsync } from '../hooks/useAsync'
import { formatAmount, formatDate, formatDateTime, toneFor } from '../lib/format'
import {
  DataTable,
  ErrorState,
  Field,
  Loading,
  PageHeader,
  Pager,
  Panel,
  SimulationNote,
  StatusChip,
  Tabs,
} from '../components/ui'

const STATUSES = [
  'MATCHED',
  'UNMATCHED',
  'AMOUNT_MISMATCH',
  'CURRENCY_MISMATCH',
  'DUPLICATE',
  'MISSING_ENTRY',
  'TIMING_DIFFERENCE',
  'REFERENCE_MISMATCH',
]

export function ReconciliationPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [tab, setTab] = useState<'records' | 'statement' | 'reference'>(
    params.get('tab') === 'statement' ? 'statement' : 'records',
  )
  const [status, setStatus] = useState('')
  const [breaksOnly, setBreaksOnly] = useState(params.get('status') === 'breaks')
  const [page, setPage] = useState(1)

  const listing = useAsync(
    (signal) =>
      api.reconciliation(
        { page, pageSize: 25, status: status || undefined, breaksOnly: breaksOnly || undefined },
        signal,
      ),
    [page, status, breaksOnly],
  )
  const statements = useAsync((signal) => api.statementEntries({ pageSize: 50 }, signal), [tab])

  return (
    <div className="page">
      <PageHeader
        eyebrow="Operations"
        title="Reconciliation"
        lede="Four views of the same payment are compared: the internal record, the accounting journal, the clearing record and the account statement. The statement is the external source of truth."
      />

      <div className="stack">
        {listing.data && (
          <div className="row-wrap">
            {Object.entries(listing.data.byStatus)
              .sort((a, b) => b[1] - a[1])
              .map(([key, count]) => (
                <button
                  key={key}
                  type="button"
                  className="row-tight"
                  style={{
                    background: 'transparent',
                    border: '1px solid var(--line)',
                    borderRadius: 'var(--radius)',
                    padding: 'var(--s-2) var(--s-4)',
                    cursor: 'pointer',
                  }}
                  onClick={() => {
                    setStatus(status === key ? '' : key)
                    setBreaksOnly(false)
                    setPage(1)
                  }}
                  aria-pressed={status === key}
                >
                  <StatusChip value={key} mode="raw" tone={toneFor(key)} />
                  <span className="num dim">{count}</span>
                </button>
              ))}
          </div>
        )}

        <Panel flush>
          <Tabs
            tabs={[
              { id: 'records', label: 'Reconciliation records', count: listing.data?.total },
              { id: 'statement', label: 'Statement feed', count: statements.data?.total },
              { id: 'reference', label: 'Classification reference' },
            ]}
            active={tab}
            onChange={(id) => setTab(id as typeof tab)}
          />

          {tab === 'records' && (
            <>
              <div className="filters" style={{ border: 0, borderBottom: '1px solid var(--line)', borderRadius: 0 }}>
                <Field label="Classification">
                  <select
                    value={status}
                    onChange={(event) => {
                      setStatus(event.target.value)
                      setPage(1)
                    }}
                  >
                    <option value="">Any</option>
                    {STATUSES.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </Field>
                <label className="checkbox" style={{ paddingBottom: 'var(--s-3)' }}>
                  <input
                    type="checkbox"
                    checked={breaksOnly}
                    onChange={(event) => {
                      setBreaksOnly(event.target.checked)
                      setStatus('')
                      setPage(1)
                    }}
                  />
                  <span>Breaks only</span>
                </label>
              </div>

              {listing.loading && !listing.data ? (
                <Loading rows={6} />
              ) : listing.error ? (
                <div style={{ padding: 'var(--s-5)' }}>
                  <ErrorState error={listing.error} onRetry={listing.reload} />
                </div>
              ) : (
                <>
                  <DataTable
                    columns={[
                      {
                        key: 'reference',
                        header: 'Record',
                        render: (row) => (
                          <>
                            <div className="cell-primary">{row.reference}</div>
                            <div className="cell-secondary">{formatDateTime(row.runAt)}</div>
                          </>
                        ),
                      },
                      {
                        key: 'payment',
                        header: 'Payment',
                        render: (row) => <span className="mono">{row.paymentReference ?? '—'}</span>,
                      },
                      {
                        key: 'status',
                        header: 'Classification',
                        render: (row) => <StatusChip value={row.status} mode="raw" tone={toneFor(row.status)} />,
                      },
                      {
                        key: 'internal',
                        header: 'Internal',
                        numeric: true,
                        render: (row) => formatAmount(row.internalAmount, row.internalCurrency ?? undefined),
                      },
                      {
                        key: 'accounting',
                        header: 'Accounting',
                        numeric: true,
                        render: (row) =>
                          row.accountingAmount
                            ? formatAmount(row.accountingAmount, row.internalCurrency ?? undefined)
                            : 'absent',
                      },
                      {
                        key: 'clearing',
                        header: 'Clearing',
                        numeric: true,
                        render: (row) =>
                          row.clearingAmount
                            ? formatAmount(row.clearingAmount, row.internalCurrency ?? undefined)
                            : 'absent',
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
                          row.differenceAmount && Number(row.differenceAmount) !== 0 ? (
                            <span className="text-error">
                              {formatAmount(row.differenceAmount, row.internalCurrency ?? undefined)}
                            </span>
                          ) : (
                            '—'
                          ),
                      },
                    ]}
                    rows={listing.data?.items ?? []}
                    rowKey={(row) => row.reference}
                    onRowClick={(row) => navigate(`/reconciliation/${row.reference}`)}
                    emptyTitle="No reconciliation records match"
                  />
                  {listing.data && (
                    <Pager
                      page={listing.data.page}
                      pageSize={listing.data.pageSize}
                      total={listing.data.total}
                      onPage={setPage}
                    />
                  )}
                </>
              )}
            </>
          )}

          {tab === 'statement' && (
            <>
              {statements.loading && !statements.data ? (
                <Loading rows={6} />
              ) : (
                <DataTable
                  columns={[
                    {
                      key: 'reference',
                      header: 'Entry',
                      render: (row) => (
                        <>
                          <div className="cell-primary">{row.statementReference}</div>
                          <div className="cell-secondary">{row.sourceMessageType}</div>
                        </>
                      ),
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
                    { key: 'value', header: 'Value date', render: (row) => formatDate(row.valueDate) },
                    {
                      key: 'e2e',
                      header: 'End-to-end id',
                      render: (row) => <span className="mono">{row.endToEndId ?? '—'}</span>,
                    },
                    {
                      key: 'match',
                      header: 'Match',
                      render: (row) =>
                        row.isOrphan ? (
                          <StatusChip value="UNMATCHED" mode="raw" tone="error" />
                        ) : (
                          <StatusChip value="MATCHED" mode="raw" tone="ok" />
                        ),
                    },
                  ]}
                  rows={statements.data?.items ?? []}
                  rowKey={(row) => row.statementReference}
                  emptyTitle="No statement entries yet"
                  emptyBody="Statement entries appear once a payment has been accounted for."
                />
              )}
            </>
          )}

          {tab === 'reference' && (
            <div className="col" style={{ padding: 'var(--s-5)' }}>
              <SimulationNote>
                A production reconciliation engine matches many-to-many across batches with tolerance
                rules and ageing. This engine reconciles one payment at a time, plus unmatched
                statement entries.
              </SimulationNote>
              <DataTable
                columns={[
                  {
                    key: 'status',
                    header: 'Classification',
                    render: (row) => <StatusChip value={row.status} mode="raw" tone={toneFor(row.status)} />,
                  },
                  {
                    key: 'break',
                    header: 'Is a break',
                    render: (row) => (row.isBreak ? 'Yes' : 'No'),
                  },
                  { key: 'cause', header: 'Probable cause', render: (row) => row.probableCause },
                  { key: 'action', header: 'Recommended action', render: (row) => row.recommendedAction },
                ]}
                rows={listing.data?.classifications ?? []}
                rowKey={(row) => row.status}
              />
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}
