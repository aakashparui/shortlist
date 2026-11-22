/** One reconciliation record: the four legs side by side, with the explanation. */

import { Link, useParams } from 'react-router-dom'

import { api } from '../api/client'
import { useAsync } from '../hooks/useAsync'
import { formatAmount, formatDate, formatDateTime, toneFor } from '../lib/format'
import {
  ErrorState,
  KeyValue,
  Loading,
  Notice,
  PageHeader,
  Panel,
  StatusChip,
} from '../components/ui'

export function ReconciliationDetailPage() {
  const { reference = '' } = useParams()
  const record = useAsync((signal) => api.reconciliationRecord(reference, signal), [reference])

  if (record.loading && !record.data) {
    return (
      <div className="page">
        <Loading rows={8} label="Loading reconciliation record" />
      </div>
    )
  }
  if (record.error) {
    return (
      <div className="page">
        <PageHeader eyebrow="Operations" title={reference} />
        <ErrorState error={record.error} onRetry={record.reload} />
      </div>
    )
  }
  const data = record.data
  if (!data) return null

  const isBreak = data.status !== 'MATCHED' && data.status !== 'NOT_RUN'

  return (
    <div className="page">
      <PageHeader
        eyebrow="Reconciliation investigation"
        title={data.reference}
        lede={`Run at ${formatDateTime(data.runAt)} for payment ${data.paymentReference ?? '—'}.`}
        actions={
          <>
            <StatusChip value={data.status} mode="raw" tone={toneFor(data.status)} />
            {data.paymentReference && (
              <Link className="btn" to={`/payments/${data.paymentReference}`}>
                Open payment
              </Link>
            )}
          </>
        }
      />

      <div className="stack">
        {isBreak ? (
          <Notice tone="error" title={`Break: ${data.status}`}>
            {data.probableCause}
          </Notice>
        ) : (
          <Notice tone="ok" title="Matched">
            {data.probableCause}
          </Notice>
        )}

        <Panel title="The four views" subtitle="A break is a disagreement between these records">
          <div className="legs">
            {data.legs.map((leg) => (
              <div className="leg" key={leg.source} data-present={leg.present ? 'true' : 'false'}>
                <div className="leg-name">{leg.name}</div>
                <div className="leg-amount">
                  {leg.present ? formatAmount(leg.amount, leg.currency ?? undefined) : 'absent'}
                </div>
                <div className="cell-secondary mono" style={{ marginTop: 'var(--s-3)' }}>
                  {leg.reference ?? '—'}
                </div>
                {leg.bookingDate && (
                  <div className="cell-secondary mono">{formatDate(leg.bookingDate)}</div>
                )}
                <div className="cell-secondary" style={{ marginTop: 'var(--s-3)' }}>
                  {leg.note}
                </div>
              </div>
            ))}
          </div>
        </Panel>

        <div className="grid grid-2">
          <Panel title="Assessment">
            <KeyValue
              items={[
                { label: 'Classification', value: <StatusChip value={data.status} mode="raw" /> },
                {
                  label: 'Difference',
                  value: data.differenceAmount
                    ? formatAmount(data.differenceAmount, data.internalCurrency ?? undefined)
                    : 'none',
                  mono: true,
                },
                { label: 'Probable cause', value: data.probableCause },
                { label: 'Recommended action', value: data.recommendedAction },
                { label: 'Resolved', value: data.resolved ? 'Yes' : 'No' },
              ]}
            />
          </Panel>

          <Panel title="References and context">
            <KeyValue
              items={[
                { label: 'Internal reference', value: data.internalReference ?? '—', mono: true },
                { label: 'Accounting reference', value: data.accountingReference ?? '—', mono: true },
                { label: 'Clearing reference', value: data.clearingReference ?? '—', mono: true },
                { label: 'Statement reference', value: data.statementReference ?? '—', mono: true },
                ...Object.entries(data.detail)
                  .filter(([, value]) => typeof value !== 'object' && value !== null)
                  .map(([key, value]) => ({ label: key, value: String(value), mono: true })),
              ]}
            />
          </Panel>
        </div>
      </div>
    </div>
  )
}
