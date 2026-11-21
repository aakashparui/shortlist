/** One investigation, with the full payment trail and the action log. */

import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../api/client'
import { useAction, useAsync } from '../hooks/useAsync'
import { formatAmount, formatDateTime, relativeTime } from '../lib/format'
import { PaymentJourney } from '../components/PaymentJourney'
import {
  ErrorState,
  Field,
  KeyValue,
  Loading,
  Notice,
  PageHeader,
  Panel,
  StatusChip,
  Tabs,
} from '../components/ui'

export function InvestigationDetailPage() {
  const { reference = '' } = useParams()
  const [tab, setTab] = useState<'summary' | 'journey' | 'actions' | 'reconciliation'>('summary')
  const [actionName, setActionName] = useState('CONTACTED_COUNTERPARTY')
  const [note, setNote] = useState('')
  const [resolution, setResolution] = useState('')

  const investigation = useAsync((signal) => api.investigation(reference, signal), [reference])
  const data = investigation.data

  const addAction = useAction(
    () => api.addInvestigationAction(reference, { action: actionName, note }),
    {
      onSuccess: () => {
        setNote('')
        investigation.reload()
      },
    },
  )
  const resolve = useAction(() => api.resolveInvestigation(reference, { resolution }), {
    onSuccess: () => {
      setResolution('')
      investigation.reload()
    },
  })

  if (investigation.loading && !data) {
    return (
      <div className="page">
        <Loading rows={8} label="Loading investigation" />
      </div>
    )
  }
  if (investigation.error) {
    return (
      <div className="page">
        <PageHeader eyebrow="Operations" title={reference} />
        <ErrorState error={investigation.error} onRetry={investigation.reload} />
      </div>
    )
  }
  if (!data) return null

  const isOpen = ['OPEN', 'IN_PROGRESS', 'AWAITING_RESPONSE'].includes(data.status)

  return (
    <div className="page">
      <PageHeader
        eyebrow={`Investigation · ${data.reason}`}
        title={data.reference}
        lede={data.title}
        actions={
          <>
            <StatusChip value={data.status} mode="raw" />
            <StatusChip
              value={data.priority}
              mode="raw"
              tone={data.priority === 'HIGH' ? 'error' : 'warn'}
            />
            {data.paymentReference && (
              <Link className="btn" to={`/payments/${data.paymentReference}`}>
                Open payment
              </Link>
            )}
          </>
        }
      />

      <div className="stack">
        <div className="grid grid-main-aside">
          <div className="stack">
            <Panel flush>
              <Tabs
                tabs={[
                  { id: 'summary', label: 'Assessment' },
                  ...(data.payment ? [{ id: 'journey', label: 'Payment journey' }] : []),
                  { id: 'actions', label: 'Action log', count: data.actions.length },
                  ...(data.reconciliationRecord ? [{ id: 'reconciliation', label: 'Reconciliation' }] : []),
                ]}
                active={tab}
                onChange={(id) => setTab(id as typeof tab)}
              />
              <div style={{ padding: tab === 'journey' ? 0 : 'var(--s-5)' }}>
                {tab === 'summary' && (
                  <div className="col">
                    <Notice tone="error" title="What actually happened">
                      {data.actualBehaviour}
                    </Notice>
                    <KeyValue
                      items={[
                        { label: 'Expected behaviour', value: data.expectedBehaviour },
                        { label: 'Actual behaviour', value: data.actualBehaviour },
                        { label: 'Probable cause', value: data.probableCause },
                        { label: 'Recommended action', value: data.recommendedAction },
                        { label: 'Summary', value: data.summary },
                      ]}
                    />
                    {Object.keys(data.detail).length > 0 && (
                      <div className="col-tight">
                        <span className="label">Evidence</span>
                        <KeyValue
                          items={Object.entries(data.detail)
                            .filter(([, value]) => typeof value !== 'object')
                            .map(([key, value]) => ({
                              label: key,
                              value: String(value),
                              mono: true,
                            }))}
                        />
                      </div>
                    )}
                  </div>
                )}

                {tab === 'journey' && data.payment && <PaymentJourney payment={data.payment} />}

                {tab === 'actions' && (
                  <div className="col">
                    {data.actions.length === 0 && <p className="muted">No actions recorded yet.</p>}
                    <ol className="col-tight" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                      {data.actions.map((action, index) => (
                        <li
                          key={index}
                          style={{
                            borderLeft: '2px solid var(--line-accent)',
                            paddingLeft: 'var(--s-5)',
                            paddingBottom: 'var(--s-4)',
                          }}
                        >
                          <div className="row-tight">
                            <span className="mono" style={{ fontSize: 'var(--fs-xs)' }}>
                              {action.action}
                            </span>
                            <span className="dim" style={{ fontSize: 'var(--fs-xs)' }}>
                              {action.actor}
                            </span>
                            <span className="dim mono" style={{ fontSize: 'var(--fs-micro)' }}>
                              {formatDateTime(action.at)}
                            </span>
                          </div>
                          <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
                            {action.note}
                          </div>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}

                {tab === 'reconciliation' && data.reconciliationRecord && (
                  <div className="col">
                    <div className="row-wrap">
                      <Link to={`/reconciliation/${data.reconciliationRecord.reference}`} className="mono">
                        {data.reconciliationRecord.reference}
                      </Link>
                      <StatusChip value={data.reconciliationRecord.status} mode="raw" />
                    </div>
                    <div className="legs">
                      {data.reconciliationRecord.legs.map((leg) => (
                        <div
                          className="leg"
                          key={leg.source}
                          data-present={leg.present ? 'true' : 'false'}
                        >
                          <div className="leg-name">{leg.name}</div>
                          <div className="leg-amount">
                            {leg.present ? formatAmount(leg.amount, leg.currency ?? undefined) : 'absent'}
                          </div>
                          <div className="cell-secondary">{leg.note}</div>
                        </div>
                      ))}
                    </div>
                    <KeyValue
                      items={[
                        { label: 'Probable cause', value: data.reconciliationRecord.probableCause },
                        {
                          label: 'Recommended action',
                          value: data.reconciliationRecord.recommendedAction,
                        },
                      ]}
                    />
                  </div>
                )}
              </div>
            </Panel>
          </div>

          <div className="stack">
            <Panel title="Case">
              <KeyValue
                items={[
                  { label: 'Opened', value: formatDateTime(data.openedAt) },
                  { label: 'Age', value: relativeTime(data.openedAt) },
                  { label: 'Last updated', value: formatDateTime(data.updatedAt) },
                  { label: 'Assigned to', value: data.assignedTo, mono: true },
                  { label: 'Reason', value: data.reason, mono: true },
                  {
                    label: 'Payment',
                    value: data.paymentReference ? (
                      <Link to={`/payments/${data.paymentReference}`} className="mono">
                        {data.paymentReference}
                      </Link>
                    ) : (
                      '—'
                    ),
                  },
                  ...(data.resolvedAt
                    ? [{ label: 'Resolved', value: formatDateTime(data.resolvedAt) }]
                    : []),
                  ...(data.resolution ? [{ label: 'Resolution', value: data.resolution }] : []),
                ]}
              />
            </Panel>

            {isOpen && (
              <>
                <Panel title="Record an action">
                  <form
                    className="col"
                    onSubmit={(event) => {
                      event.preventDefault()
                      void addAction.run()
                    }}
                  >
                    {addAction.error && <ErrorState error={addAction.error} />}
                    <Field label="Action">
                      <select value={actionName} onChange={(event) => setActionName(event.target.value)}>
                        <option value="CONTACTED_COUNTERPARTY">Contacted the counterparty</option>
                        <option value="CALLED_CLEARING">Called the clearing system</option>
                        <option value="STATUS_REQUEST_SENT">Status request sent</option>
                        <option value="CANCELLATION_SENT">Cancellation request sent</option>
                        <option value="STATEMENT_RESEND_REQUESTED">Statement re-send requested</option>
                        <option value="CUSTOMER_INFORMED">Customer informed</option>
                        <option value="ESCALATED">Escalated</option>
                        <option value="NOTE">Note</option>
                      </select>
                    </Field>
                    <Field label="Note" required>
                      <textarea
                        value={note}
                        onChange={(event) => setNote(event.target.value)}
                        rows={3}
                        required
                      />
                    </Field>
                    <button type="submit" className="btn" disabled={addAction.pending || !note}>
                      {addAction.pending ? 'Recording…' : 'Add to the case'}
                    </button>
                  </form>
                </Panel>

                <Panel title="Resolve">
                  <form
                    className="col"
                    onSubmit={(event) => {
                      event.preventDefault()
                      void resolve.run()
                    }}
                  >
                    {resolve.error && <ErrorState error={resolve.error} />}
                    <Field label="Resolution" required hint="Recorded on the case and the audit trail">
                      <textarea
                        value={resolution}
                        onChange={(event) => setResolution(event.target.value)}
                        rows={3}
                        required
                        minLength={3}
                      />
                    </Field>
                    <button
                      type="submit"
                      className="btn"
                      data-variant="primary"
                      disabled={resolve.pending || resolution.length < 3}
                    >
                      {resolve.pending ? 'Resolving…' : 'Resolve investigation'}
                    </button>
                  </form>
                </Panel>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
