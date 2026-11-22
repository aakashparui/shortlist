/**
 * Message trace: enter any reference and see the whole message exchange for that
 * payment, in order, with the full payload of whichever message is selected.
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import { useAsync } from '../hooks/useAsync'
import { formatTime, severityTone } from '../lib/format'
import { MessageViewer } from '../components/MessageViewer'
import {
  Empty,
  ErrorState,
  Loading,
  PageHeader,
  Panel,
  StatusChip,
} from '../components/ui'

export function MessageTracePage() {
  const [input, setInput] = useState('')
  const [reference, setReference] = useState('')

  const recent = useAsync((signal) => api.listPayments({ pageSize: 8, sort: 'updatedAt' }, signal), [])
  const payment = useAsync((signal) => api.getPayment(reference, signal), [reference], {
    enabled: reference.length > 0,
  })

  return (
    <div className="page">
      <PageHeader
        eyebrow="Messages"
        title="Message trace"
        lede="Follow one payment's message exchange end to end: what was sent, what came back, in what order, and what each message said."
      />

      <div className="stack">
        <form
          className="filters"
          onSubmit={(event) => {
            event.preventDefault()
            setReference(input.trim())
          }}
        >
          <div className="field wide">
            <span className="field-label">Payment reference or identifier</span>
            <input
              type="search"
              placeholder="TXN-10001, end-to-end id, UETR, correlation id"
              value={input}
              onChange={(event) => setInput(event.target.value)}
            />
          </div>
          <button type="submit" className="btn" data-variant="primary" style={{ marginBottom: 1 }}>
            Trace
          </button>
        </form>

        {!reference && (
          <Panel title="Recently updated payments" subtitle="Pick one to trace">
            <div className="col-tight">
              {recent.loading && !recent.data && <Loading rows={4} />}
              {(recent.data?.items ?? []).map((item) => (
                <button
                  key={item.reference}
                  type="button"
                  className="row"
                  style={{
                    border: '1px solid var(--line)',
                    borderRadius: 'var(--radius)',
                    background: 'transparent',
                    padding: 'var(--s-3) var(--s-4)',
                    cursor: 'pointer',
                    textAlign: 'left',
                  }}
                  onClick={() => {
                    setInput(item.reference)
                    setReference(item.reference)
                  }}
                >
                  <span className="mono">{item.reference}</span>
                  <StatusChip value={item.status} />
                  <span className="dim truncate">
                    {item.debtorName} → {item.creditorName}
                  </span>
                  <span className="spacer" />
                  <span className="num dim">{item.amountFormatted}</span>
                </button>
              ))}
            </div>
          </Panel>
        )}

        {reference && payment.loading && !payment.data && <Loading rows={6} />}
        {reference && payment.error && <ErrorState error={payment.error} onRetry={payment.reload} />}

        {payment.data && (
          <div className="grid grid-main-aside">
            <Panel flush title={`Messages for ${payment.data.reference}`}>
              <MessageViewer messages={payment.data.messages} />
            </Panel>

            <div className="stack">
              <Panel title="Exchange sequence">
                {payment.data.messages.length === 0 ? (
                  <Empty title="No messages were produced" />
                ) : (
                  <ol
                    className="col-tight"
                    style={{ listStyle: 'none', margin: 0, padding: 0 }}
                  >
                    {payment.data.messages.map((message) => (
                      <li
                        key={message.id}
                        style={{
                          borderLeft: `2px solid ${
                            message.direction === 'OUTBOUND' ? 'var(--accent)' : 'var(--ok)'
                          }`,
                          paddingLeft: 'var(--s-5)',
                          paddingBottom: 'var(--s-4)',
                        }}
                      >
                        <div className="row-tight">
                          <span className="tag" data-tone="accent">
                            {message.messageType}
                          </span>
                          <span className="dim mono" style={{ fontSize: 'var(--fs-micro)' }}>
                            {message.direction === 'OUTBOUND' ? '→ out' : '← in'}
                          </span>
                          <span className="dim mono" style={{ fontSize: 'var(--fs-micro)' }}>
                            {formatTime(message.createdAt)}
                          </span>
                        </div>
                        <div className="mono truncate" style={{ fontSize: 'var(--fs-xs)' }}>
                          {message.messageId}
                        </div>
                        {message.reasonCode && (
                          <div className="cell-secondary mono">reason {message.reasonCode}</div>
                        )}
                      </li>
                    ))}
                  </ol>
                )}
              </Panel>

              <Panel title="Related events">
                <div className="events">
                  {payment.data.events
                    .filter((event) => event.eventType.includes('MESSAGE') || event.eventType.includes('CLEARING'))
                    .map((event) => (
                      <div className="event-row" key={event.id} style={{ padding: 'var(--s-2) 0' }}>
                        <span className="severity" data-tone={severityTone(event.severity)} />
                        <span className="event-time">{formatTime(event.occurredAt)}</span>
                        <span className="event-source">{event.sourceSystem}</span>
                        <span className="event-summary">{event.summary}</span>
                      </div>
                    ))}
                </div>
              </Panel>

              <Link className="btn" to={`/payments/${payment.data.reference}`}>
                Open the full payment
              </Link>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
