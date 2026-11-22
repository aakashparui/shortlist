/** ISO 20022 explorer: the catalogue, plus every message the simulator has produced. */

import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { api } from '../api/client'
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
  SimulationNote,
  StatusChip,
  Tabs,
} from '../components/ui'

export function MessageExplorerPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [tab, setTab] = useState<'catalogue' | 'instances'>(
    params.get('type') ? 'instances' : 'catalogue',
  )
  const [messageType, setMessageType] = useState(params.get('type') ?? '')
  const [direction, setDirection] = useState('')
  const [page, setPage] = useState(1)

  const catalogue = useAsync((signal) => api.messageCatalogue(signal), [])
  const listing = useAsync(
    (signal) =>
      api.messages(
        {
          page,
          pageSize: 25,
          messageType: messageType || undefined,
          direction: direction || undefined,
        },
        signal,
      ),
    [page, messageType, direction],
  )

  const selectType = (type: string) => {
    setMessageType(type)
    setTab('instances')
    setPage(1)
    const next = new URLSearchParams(params)
    if (type) next.set('type', type)
    else next.delete('type')
    setParams(next, { replace: true })
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="Messages"
        title="ISO 20022 explorer"
        lede="The message set the simulator exchanges, and every instance it has produced. Open a payment to read a message in its business, XML, mapping and validation views."
      />

      <div className="stack">
        <Panel flush>
          <Tabs
            tabs={[
              { id: 'catalogue', label: 'Message catalogue', count: catalogue.data?.items.length },
              { id: 'instances', label: 'Generated messages', count: listing.data?.total },
            ]}
            active={tab}
            onChange={(id) => setTab(id as typeof tab)}
          />

          {tab === 'catalogue' && (
            <>
              {catalogue.loading && !catalogue.data ? (
                <Loading rows={6} />
              ) : catalogue.error ? (
                <div style={{ padding: 'var(--s-5)' }}>
                  <ErrorState error={catalogue.error} onRetry={catalogue.reload} />
                </div>
              ) : (
                <DataTable
                  columns={[
                    {
                      key: 'type',
                      header: 'Message',
                      render: (row) => (
                        <>
                          <div className="cell-primary">{row.messageType}</div>
                          <div className="cell-secondary">{row.isoIdentifier}</div>
                        </>
                      ),
                    },
                    { key: 'name', header: 'ISO name', render: (row) => row.name },
                    {
                      key: 'direction',
                      header: 'Direction',
                      render: (row) => <span className="tag">{row.direction}</span>,
                    },
                    { key: 'purpose', header: 'What it is for', render: (row) => row.purpose },
                    {
                      key: 'schemes',
                      header: 'Used by',
                      render: (row) => (
                        <div className="row-wrap">
                          {(row.usedBySchemes ?? []).map((scheme) => (
                            <span className="tag" key={scheme}>
                              {scheme}
                            </span>
                          ))}
                        </div>
                      ),
                    },
                    {
                      key: 'count',
                      header: 'Generated',
                      numeric: true,
                      render: (row) => String(row.count ?? 0),
                    },
                  ]}
                  rows={catalogue.data?.items ?? []}
                  rowKey={(row) => row.messageType}
                  onRowClick={(row) => selectType(row.messageType)}
                />
              )}
              {catalogue.data && (
                <div style={{ padding: 'var(--s-5)' }}>
                  <SimulationNote>{catalogue.data.simulationNote}</SimulationNote>
                </div>
              )}
            </>
          )}

          {tab === 'instances' && (
            <>
              <div
                className="filters"
                style={{ border: 0, borderBottom: '1px solid var(--line)', borderRadius: 0 }}
              >
                <Field label="Message type">
                  <select value={messageType} onChange={(event) => selectType(event.target.value)}>
                    <option value="">Any type</option>
                    {(catalogue.data?.items ?? []).map((item) => (
                      <option key={item.messageType} value={item.messageType}>
                        {item.messageType}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Direction">
                  <select
                    value={direction}
                    onChange={(event) => {
                      setDirection(event.target.value)
                      setPage(1)
                    }}
                  >
                    <option value="">Both</option>
                    <option value="OUTBOUND">Outbound</option>
                    <option value="INBOUND">Inbound</option>
                  </select>
                </Field>
              </div>

              {listing.loading && !listing.data ? (
                <Loading rows={6} />
              ) : (
                <>
                  <DataTable
                    columns={[
                      {
                        key: 'messageId',
                        header: 'Message identification',
                        render: (row) => (
                          <>
                            <div className="cell-primary">{row.messageId}</div>
                            <div className="cell-secondary">{row.messageName}</div>
                          </>
                        ),
                      },
                      {
                        key: 'type',
                        header: 'Type',
                        render: (row) => (
                          <>
                            <span className="tag" data-tone="accent">
                              {row.messageType}
                            </span>
                            {row.isMalformed && (
                              <div className="cell-secondary text-error">malformed</div>
                            )}
                          </>
                        ),
                      },
                      {
                        key: 'direction',
                        header: 'Direction',
                        render: (row) => <span className="tag">{row.direction}</span>,
                      },
                      {
                        key: 'state',
                        header: 'State',
                        render: (row) => <StatusChip value={row.state} mode="raw" />,
                      },
                      {
                        key: 'payment',
                        header: 'Payment',
                        render: (row) => <span className="mono">{row.paymentReference ?? '—'}</span>,
                      },
                      {
                        key: 'reason',
                        header: 'Reason code',
                        render: (row) => (row.reasonCode ? <span className="mono">{row.reasonCode}</span> : '—'),
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
                    ]}
                    rows={listing.data?.items ?? []}
                    rowKey={(row) => String(row.id)}
                    onRowClick={(row) =>
                      row.paymentReference &&
                      navigate(`/payments/${row.paymentReference}?tab=messages`)
                    }
                    emptyTitle="No messages match"
                    emptyBody="Execute a payment to generate messages."
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
        </Panel>
      </div>
    </div>
  )
}
