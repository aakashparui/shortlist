/** Global event log and audit trail. */

import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import { useAsync, useDebounced, usePolling } from '../hooks/useAsync'
import { formatDateTime, formatDuration, formatTime, severityTone } from '../lib/format'
import {
  DataTable,
  Empty,
  ErrorState,
  Field,
  JsonBlock,
  Loading,
  PageHeader,
  Pager,
  Panel,
  Tabs,
} from '../components/ui'

export function EventLogPage() {
  const [tab, setTab] = useState<'events' | 'audit'>('events')
  const [eventType, setEventType] = useState('')
  const [sourceSystem, setSourceSystem] = useState('')
  const [severity, setSeverity] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [live, setLive] = useState(false)
  const [expanded, setExpanded] = useState<number | null>(null)

  const debounced = useDebounced(search, 240)

  const events = useAsync(
    (signal) =>
      api.events(
        {
          page,
          pageSize: 50,
          eventType: eventType || undefined,
          sourceSystem: sourceSystem || undefined,
          severity: severity || undefined,
          query: debounced || undefined,
        },
        signal,
      ),
    [page, eventType, sourceSystem, severity, debounced],
  )
  const audit = useAsync((signal) => api.audit({ page, pageSize: 50 }, signal), [page, tab])
  usePolling(() => events.reload(), 4000, live && tab === 'events')

  const filters = events.data?.filters

  return (
    <div className="page">
      <PageHeader
        eyebrow="System"
        title="Event log"
        lede="Every meaningful action produces an event, carrying its source system, severity, stage and correlation id. The audit trail records who changed what, when, and why."
        actions={
          <label className="checkbox">
            <input type="checkbox" checked={live} onChange={(event) => setLive(event.target.checked)} />
            <span>Live tail</span>
          </label>
        }
      />

      <div className="stack">
        <Panel flush>
          <Tabs
            tabs={[
              { id: 'events', label: 'Events', count: events.data?.total },
              { id: 'audit', label: 'Audit trail', count: audit.data?.total },
            ]}
            active={tab}
            onChange={(id) => {
              setTab(id as typeof tab)
              setPage(1)
            }}
          />

          {tab === 'events' && (
            <>
              <div
                className="filters"
                style={{ border: 0, borderBottom: '1px solid var(--line)', borderRadius: 0 }}
              >
                <div className="field wide">
                  <span className="field-label">Search summaries</span>
                  <input
                    type="search"
                    value={search}
                    onChange={(event) => {
                      setSearch(event.target.value)
                      setPage(1)
                    }}
                    placeholder="timeout, rejected, pacs.002…"
                  />
                </div>
                <Field label="Event type">
                  <select
                    value={eventType}
                    onChange={(event) => {
                      setEventType(event.target.value)
                      setPage(1)
                    }}
                  >
                    <option value="">Any</option>
                    {(filters?.eventTypes ?? []).map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Source system">
                  <select
                    value={sourceSystem}
                    onChange={(event) => {
                      setSourceSystem(event.target.value)
                      setPage(1)
                    }}
                  >
                    <option value="">Any</option>
                    {(filters?.sourceSystems ?? []).map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Severity">
                  <select
                    value={severity}
                    onChange={(event) => {
                      setSeverity(event.target.value)
                      setPage(1)
                    }}
                  >
                    <option value="">Any</option>
                    {(filters?.severities ?? []).map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>

              {events.loading && !events.data ? (
                <Loading rows={10} />
              ) : events.error ? (
                <div style={{ padding: 'var(--s-5)' }}>
                  <ErrorState error={events.error} onRetry={events.reload} />
                </div>
              ) : (
                <>
                  <div className="events">
                    {(events.data?.items ?? []).map((event) => (
                      <div key={event.id}>
                        <button
                          type="button"
                          className="event-row"
                          style={{
                            width: '100%',
                            background: 'transparent',
                            border: 0,
                            borderBottom: '1px solid var(--line-soft)',
                            textAlign: 'left',
                            cursor: 'pointer',
                          }}
                          onClick={() => setExpanded(expanded === event.id ? null : event.id)}
                          aria-expanded={expanded === event.id}
                        >
                          <span className="severity" data-tone={severityTone(event.severity)} />
                          <span className="event-time">{formatTime(event.occurredAt)}</span>
                          <span className="event-source">{event.sourceSystem}</span>
                          <span className="event-summary">
                            {event.summary}
                            {event.paymentReference && (
                              <span className="dim mono"> · {event.paymentReference}</span>
                            )}
                            {event.stageKey && <span className="dim mono"> · {event.stageKey}</span>}
                            {event.durationMs !== null && (
                              <span className="dim mono"> · {formatDuration(event.durationMs)}</span>
                            )}
                          </span>
                        </button>
                        {expanded === event.id && (
                          <div style={{ padding: 'var(--s-5)', background: 'var(--surface-2)' }}>
                            <div className="row-wrap" style={{ marginBottom: 'var(--s-4)' }}>
                              <span className="tag">{event.eventType}</span>
                              <span className="tag">{event.severity}</span>
                              <span className="dim mono" style={{ fontSize: 'var(--fs-micro)' }}>
                                seq {event.sequence} · {formatDateTime(event.occurredAt)}
                              </span>
                              {event.paymentReference && (
                                <Link to={`/payments/${event.paymentReference}`} className="btn" data-size="sm">
                                  Open payment
                                </Link>
                              )}
                            </div>
                            {Object.keys(event.detail).length > 0 ? (
                              <JsonBlock value={event.detail} />
                            ) : (
                              <span className="dim">No additional detail recorded.</span>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                    {(events.data?.items.length ?? 0) === 0 && <Empty title="No events match these filters" />}
                  </div>
                  {events.data && (
                    <Pager
                      page={events.data.page}
                      pageSize={events.data.pageSize}
                      total={events.data.total}
                      onPage={setPage}
                    />
                  )}
                </>
              )}
            </>
          )}

          {tab === 'audit' && (
            <>
              {audit.loading && !audit.data ? (
                <Loading rows={8} />
              ) : (
                <>
                  <DataTable
                    columns={[
                      {
                        key: 'when',
                        header: 'When',
                        render: (row) => (
                          <span className="mono" style={{ fontSize: 'var(--fs-xs)' }}>
                            {formatDateTime(row.occurredAt)}
                          </span>
                        ),
                      },
                      { key: 'actor', header: 'Who', render: (row) => <span className="mono">{row.actor}</span> },
                      { key: 'action', header: 'What', render: (row) => <span className="tag">{row.action}</span> },
                      {
                        key: 'entity',
                        header: 'On',
                        render: (row) => (
                          <>
                            <div className="cell-primary">{row.entityId}</div>
                            <div className="cell-secondary">{row.entityType}</div>
                          </>
                        ),
                      },
                      { key: 'reason', header: 'Why', render: (row) => row.reason || '—' },
                      {
                        key: 'before',
                        header: 'Before',
                        render: (row) =>
                          Object.keys(row.before).length > 0 ? (
                            <span className="mono" style={{ fontSize: 'var(--fs-micro)' }}>
                              {JSON.stringify(row.before)}
                            </span>
                          ) : (
                            '—'
                          ),
                      },
                      {
                        key: 'after',
                        header: 'After',
                        render: (row) =>
                          Object.keys(row.after).length > 0 ? (
                            <span className="mono" style={{ fontSize: 'var(--fs-micro)' }}>
                              {JSON.stringify(row.after)}
                            </span>
                          ) : (
                            '—'
                          ),
                      },
                    ]}
                    rows={audit.data?.items ?? []}
                    rowKey={(row) => String(row.id)}
                    emptyTitle="No audit entries yet"
                  />
                  {audit.data && (
                    <Pager
                      page={audit.data.page}
                      pageSize={audit.data.pageSize}
                      total={audit.data.total}
                      onPage={setPage}
                    />
                  )}
                </>
              )}
            </>
          )}
        </Panel>
      </div>
    </div>
  )
}
