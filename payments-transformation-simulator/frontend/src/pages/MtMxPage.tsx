/** MT103 to pacs.008 mapping reference. */

import { useState } from 'react'

import { api } from '../api/client'
import { useAsync } from '../hooks/useAsync'
import {
  DataTable,
  ErrorState,
  Field,
  Loading,
  Notice,
  PageHeader,
  Panel,
} from '../components/ui'

const TYPES = ['DIRECT', 'TRANSFORMED', 'DERIVED', 'NO_DIRECT_EQUIVALENT']

export function MtMxPage() {
  const [filter, setFilter] = useState('')
  const reference = useAsync((signal) => api.mtMxReference(signal), [])

  if (reference.loading && !reference.data) {
    return (
      <div className="page">
        <Loading rows={8} label="Loading mapping reference" />
      </div>
    )
  }
  if (reference.error) {
    return (
      <div className="page">
        <PageHeader eyebrow="Messages" title="MT → MX mapping" />
        <ErrorState error={reference.error} onRetry={reference.reload} />
      </div>
    )
  }
  const data = reference.data
  if (!data) return null

  const rows = filter ? data.rows.filter((row) => row.mappingType === filter) : data.rows
  const counts = TYPES.map((type) => ({
    type,
    count: data.rows.filter((row) => row.mappingType === type).length,
  }))

  return (
    <div className="page">
      <PageHeader
        eyebrow="Messages"
        title="MT → MX mapping"
        lede={`Field-level comparison of ${data.source} against ${data.target}. The point of this view is the mapping type: how much of the legacy message survives the move, and what does not.`}
      />

      <div className="stack">
        <Notice tone="warn" title="There is no universal one-to-one mapping">
          {data.warning}
        </Notice>

        <div className="metrics">
          {counts.map((item) => (
            <div className="metric" key={item.type}>
              <div className="metric-label">{item.type.replace(/_/g, ' ')}</div>
              <div
                className="metric-value"
                data-tone={
                  item.type === 'DIRECT'
                    ? 'ok'
                    : item.type === 'TRANSFORMED'
                      ? 'warn'
                      : item.type === 'NO_DIRECT_EQUIVALENT'
                        ? 'error'
                        : undefined
                }
              >
                {item.count}
              </div>
              <div className="metric-note">
                {data.mappingTypes.find((t) => t.type === item.type)?.meaning}
              </div>
            </div>
          ))}
        </div>

        <Panel
          title="Field mapping"
          subtitle={`${rows.length} of ${data.rows.length} rows`}
          flush
          actions={
            <Field label="">
              <select value={filter} onChange={(event) => setFilter(event.target.value)}>
                <option value="">All mapping types</option>
                {TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </Field>
          }
        >
          <DataTable
            columns={[
              {
                key: 'mt',
                header: 'MT103 field',
                render: (row) => (
                  <>
                    <div className="cell-primary">{row.mtTag}</div>
                    <div className="cell-secondary">{row.mtName}</div>
                  </>
                ),
              },
              { key: 'arrow', header: '', render: () => <span className="mapping-arrow">→</span> },
              {
                key: 'mx',
                header: 'pacs.008 element',
                render: (row) => (
                  <span className="mono" style={{ fontSize: 'var(--fs-xs)' }}>
                    {row.mxPath}
                  </span>
                ),
              },
              {
                key: 'type',
                header: 'Mapping type',
                render: (row) => (
                  <span className="mapping-type" data-kind={row.mappingType}>
                    {row.mappingType}
                  </span>
                ),
              },
              { key: 'note', header: 'What to watch for', render: (row) => row.note || '—' },
            ]}
            rows={rows}
            rowKey={(row) => row.mtTag}
          />
        </Panel>

        <Panel title="How to read the mapping types">
          <div className="col-tight">
            {data.mappingTypes.map((item) => (
              <div className="row" key={item.type} style={{ alignItems: 'flex-start' }}>
                <span className="mapping-type" data-kind={item.type} style={{ flex: '0 0 190px' }}>
                  {item.type}
                </span>
                <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
                  {item.meaning}
                </span>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  )
}
