/** Payment search: the investigator's entry point into the book. */

import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { api } from '../api/client'
import type { PaymentSummary } from '../api/types'
import { useAsync, useDebounced } from '../hooks/useAsync'
import { formatAmount, formatDateTime, relativeTime, schemeLabel } from '../lib/format'
import {
  DataTable,
  ErrorState,
  Field,
  Loading,
  PageHeader,
  Pager,
  Panel,
  StatusChip,
  type Column,
} from '../components/ui'

const STATUS_OPTIONS = [
  'COMPLETED',
  'REJECTED',
  'CLEARING_REJECTED',
  'INVESTIGATION_REQUIRED',
  'TIMED_OUT',
  'RETURNED',
  'BLOCKED',
  'RECONCILIATION_BREAK',
  'ACCOUNTING_BREAK',
  'SETTLEMENT_FAILED',
  'CANCELLED',
]

export function PaymentSearchPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()

  const [query, setQuery] = useState(params.get('query') ?? '')
  const [status, setStatus] = useState(params.get('status') ?? '')
  const [scheme, setScheme] = useState(params.get('scheme') ?? '')
  const [currency, setCurrency] = useState(params.get('currency') ?? '')
  const [amountMin, setAmountMin] = useState(params.get('amountMin') ?? '')
  const [amountMax, setAmountMax] = useState(params.get('amountMax') ?? '')
  const [failuresOnly, setFailuresOnly] = useState(params.get('failuresOnly') === 'true')
  const [page, setPage] = useState(Number(params.get('page') ?? 1))
  const [sort, setSort] = useState('createdAt')

  const debouncedQuery = useDebounced(query, 240)
  const schemes = useAsync((signal) => api.schemes(signal), [])
  const config = useAsync((signal) => api.config(signal), [])

  const listing = useAsync(
    (signal) =>
      api.listPayments(
        {
          page,
          pageSize: 25,
          query: debouncedQuery || undefined,
          status: status ? [status] : undefined,
          scheme: scheme ? [scheme] : undefined,
          currency: currency ? [currency] : undefined,
          amountMin: amountMin || undefined,
          amountMax: amountMax || undefined,
          failuresOnly: failuresOnly || undefined,
          sort,
        },
        signal,
      ),
    [page, debouncedQuery, status, scheme, currency, amountMin, amountMax, failuresOnly, sort],
  )

  const syncUrl = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    setParams(next, { replace: true })
  }

  const columns: Column<PaymentSummary>[] = useMemo(
    () => [
      {
        key: 'reference',
        header: 'Reference',
        render: (row) => (
          <>
            <div className="cell-primary">{row.reference}</div>
            <div className="cell-secondary">{row.endToEndId}</div>
          </>
        ),
      },
      {
        key: 'created',
        header: 'Created',
        render: (row) => (
          <>
            <div style={{ fontSize: 'var(--fs-xs)' }}>{formatDateTime(row.createdAt)}</div>
            <div className="cell-secondary">{relativeTime(row.createdAt)}</div>
          </>
        ),
      },
      {
        key: 'scheme',
        header: 'Rail',
        render: (row) => <span className="tag">{schemeLabel(row.scheme)}</span>,
      },
      {
        key: 'debtor',
        header: 'Debtor',
        render: (row) => <span className="truncate">{row.debtorName}</span>,
      },
      {
        key: 'creditor',
        header: 'Creditor',
        render: (row) => (
          <>
            <div className="truncate">{row.creditorName}</div>
            {row.creditorCountry && <div className="cell-secondary mono">{row.creditorCountry}</div>}
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
              <div className="cell-secondary" style={{ maxWidth: 360 }}>
                {row.failureSummary}
              </div>
            )}
          </>
        ),
      },
      {
        key: 'flags',
        header: 'Flags',
        render: (row) => (
          <div className="row-tight" style={{ flexWrap: 'wrap' }}>
            {row.scenarioCode && <span className="tag">{row.scenarioCode}</span>}
            {row.retryCount > 0 && <span className="tag">retry ×{row.retryCount}</span>}
            {row.uetr && <span className="tag">UETR</span>}
          </div>
        ),
      },
    ],
    [],
  )

  return (
    <div className="page">
      <PageHeader
        eyebrow="Payments"
        title="Payment search"
        lede="Search by reference, end-to-end identification, UETR, correlation id, clearing or settlement reference, party name, IBAN, BIC or amount."
        actions={
          <button
            type="button"
            className="btn"
            data-size="sm"
            onClick={() => {
              setQuery('')
              setStatus('')
              setScheme('')
              setCurrency('')
              setAmountMin('')
              setAmountMax('')
              setFailuresOnly(false)
              setPage(1)
              setParams(new URLSearchParams(), { replace: true })
            }}
          >
            Clear filters
          </button>
        }
      />

      <div className="stack">
        <div className="filters">
          <div className="field wide">
            <span className="field-label">Search</span>
            <input
              type="search"
              placeholder="TXN-10001, E2E…, UETR…, IBAN, party name, 4850.00"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value)
                setPage(1)
                syncUrl({ query: event.target.value, page: '' })
              }}
            />
          </div>
          <Field label="Status">
            <select
              value={status}
              onChange={(event) => {
                setStatus(event.target.value)
                setPage(1)
                syncUrl({ status: event.target.value, page: '' })
              }}
            >
              <option value="">Any status</option>
              {STATUS_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Rail">
            <select
              value={scheme}
              onChange={(event) => {
                setScheme(event.target.value)
                setPage(1)
                syncUrl({ scheme: event.target.value, page: '' })
              }}
            >
              <option value="">Any rail</option>
              {(schemes.data?.items ?? []).map((item) => (
                <option key={item.code} value={item.code}>
                  {item.shortName}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Currency">
            <select
              value={currency}
              onChange={(event) => {
                setCurrency(event.target.value)
                setPage(1)
                syncUrl({ currency: event.target.value, page: '' })
              }}
            >
              <option value="">Any</option>
              {(config.data?.currencies ?? []).map((item) => (
                <option key={item.code} value={item.code}>
                  {item.code}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Amount from">
            <input
              type="text"
              inputMode="decimal"
              data-mono="true"
              value={amountMin}
              onChange={(event) => {
                setAmountMin(event.target.value)
                setPage(1)
              }}
            />
          </Field>
          <Field label="Amount to">
            <input
              type="text"
              inputMode="decimal"
              data-mono="true"
              value={amountMax}
              onChange={(event) => {
                setAmountMax(event.target.value)
                setPage(1)
              }}
            />
          </Field>
          <Field label="Sort by">
            <select value={sort} onChange={(event) => setSort(event.target.value)}>
              <option value="createdAt">Created</option>
              <option value="updatedAt">Last updated</option>
              <option value="amount">Amount</option>
              <option value="status">Status</option>
              <option value="reference">Reference</option>
            </select>
          </Field>
          <label className="checkbox" style={{ paddingBottom: 'var(--s-3)' }}>
            <input
              type="checkbox"
              checked={failuresOnly}
              onChange={(event) => {
                setFailuresOnly(event.target.checked)
                setPage(1)
                syncUrl({ failuresOnly: event.target.checked ? 'true' : '', page: '' })
              }}
            />
            <span>Failures only</span>
          </label>
        </div>

        <Panel
          title={listing.data ? `${listing.data.total} payments` : 'Payments'}
          subtitle="Select a row to open the payment journey"
          flush
          footer={
            listing.data ? (
              <Pager
                page={listing.data.page}
                pageSize={listing.data.pageSize}
                total={listing.data.total}
                onPage={(next) => {
                  setPage(next)
                  syncUrl({ page: String(next) })
                }}
              />
            ) : undefined
          }
        >
          {listing.loading && !listing.data ? (
            <Loading rows={8} />
          ) : listing.error ? (
            <div style={{ padding: 'var(--s-5)' }}>
              <ErrorState error={listing.error} onRetry={listing.reload} />
            </div>
          ) : (
            <DataTable
              columns={columns}
              rows={listing.data?.items ?? []}
              rowKey={(row) => row.reference}
              onRowClick={(row) => navigate(`/payments/${row.reference}`)}
              emptyTitle="No payments match these filters"
              emptyBody="Widen the search, or create a payment from the simulator."
            />
          )}
        </Panel>
      </div>
    </div>
  )
}
