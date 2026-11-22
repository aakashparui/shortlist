/** Scheme rulebooks: the configuration that makes each rail behave differently. */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import { useAsync } from '../hooks/useAsync'
import { formatAmount, toneFor } from '../lib/format'
import {
  DataTable,
  ErrorState,
  KeyValue,
  Loading,
  PageHeader,
  Panel,
  SimulationNote,
  StatusChip,
} from '../components/ui'

export function SchemesPage() {
  const navigate = useNavigate()
  const [selected, setSelected] = useState<string>('SIC_INSTANT')
  const schemes = useAsync((signal) => api.schemes(signal), [])
  const detail = useAsync((signal) => api.scheme(selected, signal), [selected])

  if (schemes.loading && !schemes.data) {
    return (
      <div className="page">
        <Loading rows={8} label="Loading schemes" />
      </div>
    )
  }
  if (schemes.error) {
    return (
      <div className="page">
        <PageHeader eyebrow="Schemes" title="Scheme rulebooks" />
        <ErrorState error={schemes.error} onRetry={schemes.reload} />
      </div>
    )
  }

  const scheme = detail.data

  return (
    <div className="page">
      <PageHeader
        eyebrow="Schemes"
        title="Scheme rulebooks"
        lede="Each rail is configuration, not code: limits, currencies, country scope, timeouts, settlement behaviour and the rule set that applies. Adding a rail means adding one module."
      />

      <div className="stack">
        <div className="btn-group" role="group" aria-label="Select a scheme">
          {(schemes.data?.items ?? []).map((item) => (
            <button
              key={item.code}
              type="button"
              className="btn"
              aria-pressed={selected === item.code}
              onClick={() => setSelected(item.code)}
            >
              {item.shortName}
            </button>
          ))}
        </div>

        {detail.loading && !scheme && <Loading rows={6} />}
        {detail.error && <ErrorState error={detail.error} onRetry={detail.reload} />}

        {scheme && (
          <>
            <div className="grid grid-main-aside">
              <div className="stack">
                <Panel title={scheme.name} subtitle={`${scheme.operator} · ${scheme.jurisdiction}`}>
                  <div className="col">
                    <p className="muted">{scheme.description}</p>
                    <SimulationNote>{scheme.simulationNotes}</SimulationNote>
                  </div>
                </Panel>

                <Panel title="Amount limits">
                  <DataTable
                    columns={[
                      { key: 'currency', header: 'Currency', render: (row) => <span className="mono">{row.currency}</span> },
                      {
                        key: 'minimum',
                        header: 'Minimum',
                        numeric: true,
                        render: (row) => formatAmount(row.minimum, row.currency),
                      },
                      {
                        key: 'maximum',
                        header: 'Maximum',
                        numeric: true,
                        render: (row) => formatAmount(row.maximum, row.currency),
                      },
                    ]}
                    rows={scheme.amountLimits}
                    rowKey={(row) => row.currency}
                  />
                </Panel>

                <Panel
                  title="Rules applied on this rail"
                  subtitle={`${scheme.rules?.length ?? 0} rules, executed in order`}
                  flush
                >
                  <DataTable
                    columns={[
                      {
                        key: 'ruleId',
                        header: 'Rule',
                        render: (row) => (
                          <>
                            <div className="cell-primary">{row.ruleId}</div>
                            <div className="cell-secondary">{row.name}</div>
                          </>
                        ),
                      },
                      { key: 'stage', header: 'Stage', render: (row) => <span className="tag">{row.stage}</span> },
                      { key: 'category', header: 'Category', render: (row) => row.category },
                      {
                        key: 'severity',
                        header: 'Severity',
                        render: (row) => <StatusChip value={row.severity} mode="raw" />,
                      },
                      {
                        key: 'reason',
                        header: 'Reason code',
                        render: (row) => (row.isoReasonCode ? <span className="mono">{row.isoReasonCode}</span> : '—'),
                      },
                      {
                        key: 'enabled',
                        header: 'Enabled',
                        render: (row) => (
                          <StatusChip
                            value={row.enabled ? 'ENABLED' : 'DISABLED'}
                            mode="raw"
                            tone={row.enabled ? 'ok' : 'neutral'}
                          />
                        ),
                      },
                    ]}
                    rows={scheme.rules ?? []}
                    rowKey={(row) => row.ruleId}
                    onRowClick={(row) => navigate(`/system/rules?ruleId=${row.ruleId}`)}
                  />
                </Panel>
              </div>

              <div className="stack">
                <Panel title="Clearing">
                  <KeyValue
                    items={[
                      { label: 'Clearing system', value: scheme.clearing.system },
                      { label: 'Operator', value: scheme.clearing.operator, mono: true },
                      {
                        label: 'Typical response',
                        value: `${scheme.clearing.responseSeconds}s`,
                        mono: true,
                      },
                      {
                        label: 'Response threshold',
                        value: `${scheme.clearing.timeoutSeconds}s`,
                        mono: true,
                      },
                      {
                        label: 'In demo mode',
                        value: `${scheme.acceleratedTimeoutSeconds ?? '—'}s`,
                        mono: true,
                      },
                      {
                        label: 'Investigation threshold',
                        value: `${scheme.clearing.investigationThresholdSeconds}s`,
                        mono: true,
                      },
                      { label: 'Operating hours', value: scheme.clearing.operatingHours },
                      { label: 'Settlement finality', value: scheme.clearing.settlementFinality },
                      {
                        label: 'Rejection reason codes',
                        value: scheme.clearing.rejectionReasonCodes.join(', '),
                        mono: true,
                      },
                    ]}
                  />
                </Panel>

                <Panel title="Settlement">
                  <KeyValue
                    items={[
                      { label: 'Method', value: scheme.settlement.method, mono: true },
                      { label: 'Account type', value: scheme.settlement.accountType, mono: true },
                      {
                        label: 'Settles in scheme currency',
                        value: scheme.settlement.settlesInSchemeCurrency ? 'Yes' : 'No',
                      },
                      {
                        label: 'Value date',
                        value: `T+${scheme.settlement.valueDateOffsetDays}`,
                        mono: true,
                      },
                      { label: 'How it works', value: scheme.settlement.description },
                    ]}
                  />
                </Panel>

                <Panel title="Rule set">
                  <KeyValue
                    items={[
                      { label: 'Instant', value: scheme.isInstant ? 'Yes' : 'No' },
                      { label: 'Settlement currency', value: scheme.settlementCurrency, mono: true },
                      {
                        label: 'Currencies cleared',
                        value: scheme.allowedCurrencies.join(', '),
                        mono: true,
                      },
                      {
                        label: 'Country scope',
                        value: scheme.countryScope
                          ? `${scheme.countryScope.length} countries (${scheme.countryScope.slice(0, 8).join(', ')}${scheme.countryScope.length > 8 ? ', …' : ''})`
                          : 'Global',
                      },
                      {
                        label: 'Remittance limit',
                        value: `${scheme.maxRemittanceLength} characters`,
                        mono: true,
                      },
                      {
                        label: 'Future dating',
                        value: scheme.allowsFutureDated
                          ? `Up to ${scheme.maxFutureDays} days`
                          : 'Not permitted',
                      },
                      {
                        label: 'Duplicate window',
                        value: `${scheme.duplicateWindowMinutes} minutes`,
                        mono: true,
                      },
                      { label: 'Service levels', value: scheme.allowedServiceLevels.join(', ') || '—', mono: true },
                      { label: 'Carries UETR', value: scheme.usesUetr ? 'Yes' : 'No' },
                      { label: 'Cancellation', value: scheme.supportsCancellation ? 'Supported' : 'Not supported' },
                      { label: 'Returns', value: scheme.supportsReturn ? 'Supported' : 'Not supported' },
                    ]}
                  />
                </Panel>

                <Panel title="Messages exchanged">
                  <div className="col-tight">
                    {(scheme.messageCatalogue ?? []).map((item) => (
                      <div key={item.messageType} className="row" style={{ alignItems: 'flex-start' }}>
                        <span className="tag" data-tone="accent" style={{ flex: '0 0 78px' }}>
                          {item.messageType}
                        </span>
                        <span style={{ minWidth: 0 }}>
                          <span style={{ display: 'block', fontSize: 'var(--fs-xs)' }}>{item.name}</span>
                          <span className="dim" style={{ display: 'block', fontSize: 'var(--fs-micro)' }}>
                            {item.direction} · {item.isoIdentifier}
                          </span>
                        </span>
                      </div>
                    ))}
                  </div>
                </Panel>

                {scheme.paymentCounts && Object.keys(scheme.paymentCounts).length > 0 && (
                  <Panel title="Payments on this rail">
                    <div className="col-tight">
                      {Object.entries(scheme.paymentCounts)
                        .sort((a, b) => b[1] - a[1])
                        .map(([status, count]) => (
                          <div className="row-tight" key={status}>
                            <StatusChip value={status} mode="raw" tone={toneFor(status)} />
                            <span className="spacer" />
                            <span className="num dim">{count}</span>
                          </div>
                        ))}
                    </div>
                  </Panel>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
