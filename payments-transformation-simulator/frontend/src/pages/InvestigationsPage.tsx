/** Investigation queue. */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import type { Investigation } from '../api/types'
import { useAsync } from '../hooks/useAsync'
import { formatDateTime, relativeTime } from '../lib/format'
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

const REASONS = [
  'CLEARING_TIMEOUT',
  'RECONCILIATION_BREAK',
  'ACCOUNTING_BREAK',
  'SETTLEMENT_FAILURE',
  'COMPLIANCE_BLOCK',
  'CANCELLATION_REQUEST',
  'BENEFICIARY_NOT_CREDITED',
  'CUSTOMER_QUERY',
]

export function InvestigationsPage() {
  const navigate = useNavigate()
  const [openOnly, setOpenOnly] = useState(true)
  const [reason, setReason] = useState('')
  const [page, setPage] = useState(1)

  const listing = useAsync(
    (signal) =>
      api.investigations(
        { page, pageSize: 25, openOnly: openOnly || undefined, reason: reason || undefined },
        signal,
      ),
    [page, openOnly, reason],
  )

  const columns: Column<Investigation>[] = [
    {
      key: 'reference',
      header: 'Investigation',
      render: (row) => (
        <>
          <div className="cell-primary">{row.reference}</div>
          <div className="cell-secondary">{relativeTime(row.openedAt)}</div>
        </>
      ),
    },
    {
      key: 'priority',
      header: 'Priority',
      render: (row) => (
        <StatusChip
          value={row.priority}
          mode="raw"
          tone={row.priority === 'HIGH' ? 'error' : row.priority === 'LOW' ? 'neutral' : 'warn'}
        />
      ),
    },
    {
      key: 'title',
      header: 'Issue',
      render: (row) => (
        <>
          <div>{row.title}</div>
          <div className="cell-secondary">{row.actualBehaviour}</div>
        </>
      ),
    },
    { key: 'reason', header: 'Reason', render: (row) => <span className="tag">{row.reason}</span> },
    {
      key: 'payment',
      header: 'Payment',
      render: (row) => <span className="mono">{row.paymentReference ?? '—'}</span>,
    },
    { key: 'status', header: 'Status', render: (row) => <StatusChip value={row.status} mode="raw" /> },
    {
      key: 'assigned',
      header: 'Assigned',
      render: (row) => (
        <>
          <div style={{ fontSize: 'var(--fs-xs)' }}>{row.assignedTo}</div>
          <div className="cell-secondary">{formatDateTime(row.updatedAt)}</div>
        </>
      ),
    },
    {
      key: 'actions',
      header: 'Actions',
      numeric: true,
      render: (row) => String(row.actions.length),
    },
  ]

  return (
    <div className="page">
      <PageHeader
        eyebrow="Operations"
        title="Investigations"
        lede="Every investigation records what was expected, what actually happened, the probable cause and the recommended action, so it can be picked up by anyone on the desk."
      />

      <div className="stack">
        <div className="filters">
          <Field label="Reason">
            <select
              value={reason}
              onChange={(event) => {
                setReason(event.target.value)
                setPage(1)
              }}
            >
              <option value="">Any reason</option>
              {REASONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </Field>
          <label className="checkbox" style={{ paddingBottom: 'var(--s-3)' }}>
            <input
              type="checkbox"
              checked={openOnly}
              onChange={(event) => {
                setOpenOnly(event.target.checked)
                setPage(1)
              }}
            />
            <span>Open only</span>
          </label>
          <span className="spacer" />
          {listing.data && (
            <div className="row-wrap">
              {Object.entries(listing.data.byReason).map(([key, count]) => (
                <span className="tag" key={key}>
                  {key} {count}
                </span>
              ))}
            </div>
          )}
        </div>

        <Panel
          title={listing.data ? `${listing.data.total} investigations` : 'Investigations'}
          flush
          footer={
            listing.data ? (
              <Pager
                page={listing.data.page}
                pageSize={listing.data.pageSize}
                total={listing.data.total}
                onPage={setPage}
              />
            ) : undefined
          }
        >
          {listing.loading && !listing.data ? (
            <Loading rows={6} />
          ) : listing.error ? (
            <div style={{ padding: 'var(--s-5)' }}>
              <ErrorState error={listing.error} onRetry={listing.reload} />
            </div>
          ) : (
            <DataTable
              columns={columns}
              rows={listing.data?.items ?? []}
              rowKey={(row) => row.reference}
              onRowClick={(row) => navigate(`/investigations/${row.reference}`)}
              emptyTitle="Nothing to investigate"
              emptyBody="Break a payment in the QA Lab to see how an investigation is raised."
            />
          )}
        </Panel>
      </div>
    </div>
  )
}
