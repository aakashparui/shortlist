/** Effective configuration and the payment state machine. */

import { useState } from 'react'

import { api } from '../api/client'
import { useAsync } from '../hooks/useAsync'
import { toneFor } from '../lib/format'
import {
  DataTable,
  ErrorState,
  KeyValue,
  Loading,
  Notice,
  PageHeader,
  Panel,
  SimulationNote,
  StatusChip,
  Tabs,
} from '../components/ui'

export function ConfigurationPage() {
  const [tab, setTab] = useState<'configuration' | 'states' | 'stages'>('configuration')
  const config = useAsync((signal) => api.config(signal), [])
  const stateMachine = useAsync((signal) => api.stateMachine(signal), [])

  if (config.loading && !config.data) {
    return (
      <div className="page">
        <Loading rows={8} label="Loading configuration" />
      </div>
    )
  }
  if (config.error) {
    return (
      <div className="page">
        <PageHeader eyebrow="System" title="Configuration" />
        <ErrorState error={config.error} onRetry={config.reload} />
      </div>
    )
  }
  const data = config.data
  if (!data) return null

  return (
    <div className="page">
      <PageHeader
        eyebrow="System"
        title="Configuration"
        lede="The effective runtime configuration, the per-scheme timings, and the state machine the backend enforces. No secrets are exposed by this endpoint."
      />

      <div className="stack">
        <Notice tone="warn" title="This is a simulator">
          {data.simulationDisclaimer}
        </Notice>

        <Panel flush>
          <Tabs
            tabs={[
              { id: 'configuration', label: 'Runtime configuration' },
              { id: 'states', label: 'State machine', count: stateMachine.data?.transitions.length },
              { id: 'stages', label: 'Lifecycle stages', count: stateMachine.data?.stages.length },
            ]}
            active={tab}
            onChange={(id) => setTab(id as typeof tab)}
          />

          {tab === 'configuration' && (
            <div className="col" style={{ padding: 'var(--s-5)' }}>
              <div className="grid grid-2">
                <div className="panel">
                  <div className="panel-header">
                    <span className="panel-title">Application</span>
                  </div>
                  <div className="panel-body">
                    <KeyValue
                      items={[
                        { label: 'Name', value: data.appName },
                        { label: 'Version', value: data.appVersion, mono: true },
                        { label: 'Environment', value: data.environment, mono: true },
                        { label: 'Database', value: data.database, mono: true },
                        { label: 'Demo mode', value: data.demoMode ? 'On' : 'Off' },
                        {
                          label: 'Simulation speed factor',
                          value: `×${data.simulationSpeedFactor}`,
                          mono: true,
                        },
                        { label: 'Scheduler', value: data.schedulerEnabled ? 'Running' : 'Disabled' },
                        {
                          label: 'Scheduler poll interval',
                          value: `${data.schedulerPollIntervalSeconds}s`,
                          mono: true,
                        },
                        { label: 'Maximum page size', value: String(data.maxPageSize), mono: true },
                        { label: 'Rate limiting', value: data.rateLimitEnabled ? 'Enabled' : 'Disabled' },
                        {
                          label: 'AI assist',
                          value: data.aiEnabled
                            ? `${data.aiProvider} / ${data.aiModel}`
                            : 'Disabled — the payment engine never depends on it',
                        },
                      ]}
                    />
                  </div>
                </div>

                <div className="panel">
                  <div className="panel-header">
                    <span className="panel-title">Currencies configured</span>
                  </div>
                  <div className="panel-body">
                    <div className="col-tight">
                      {data.currencies.map((currency) => (
                        <div className="row-tight" key={currency.code}>
                          <span className="mono" style={{ flex: '0 0 46px' }}>
                            {currency.code}
                          </span>
                          <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
                            {currency.name}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              <div className="panel">
                <div className="panel-header">
                  <span className="panel-title">Clearing timeouts by scheme</span>
                  <span className="panel-subtitle">
                    Realistic values come from each scheme profile, not from a global constant
                  </span>
                </div>
                <DataTable
                  columns={[
                    { key: 'scheme', header: 'Scheme', render: (row) => <span className="mono">{row.scheme}</span> },
                    {
                      key: 'realistic',
                      header: 'Realistic threshold',
                      numeric: true,
                      render: (row) => `${row.realisticSeconds}s`,
                    },
                    {
                      key: 'accelerated',
                      header: 'In demo mode',
                      numeric: true,
                      render: (row) => `${row.acceleratedSeconds}s`,
                    },
                  ]}
                  rows={data.schemeTimeouts}
                  rowKey={(row) => row.scheme}
                />
                <div style={{ padding: 'var(--s-5)' }}>
                  <SimulationNote>
                    Demo mode divides each scheme's realistic threshold by the simulation speed factor,
                    so a timeout can be demonstrated without waiting out a full scheme window. The
                    realistic value is always shown alongside it.
                  </SimulationNote>
                </div>
              </div>

              <div className="panel">
                <div className="panel-header">
                  <span className="panel-title">Environment variables</span>
                  <span className="panel-subtitle">What can be changed without touching code</span>
                </div>
                <div className="panel-body">
                  <pre className="code-block" style={{ maxHeight: 320 }}>
{`DATABASE_URL=                    # sqlite (default) or postgresql
DEMO_MODE=true                   # seed demo payments, accelerate timings
AUTO_SEED=true                   # seed reference data on startup
SIMULATION_SPEED_FACTOR=5        # divide scheme timings by this in demo mode
CLEARING_TIMEOUT_SECONDS=25      # fallback only; schemes define their own
SCHEDULER_ENABLED=true           # background worker for async behaviour
LOG_LEVEL=INFO
LOG_FORMAT=json                  # json | text
CORS_ORIGINS=http://localhost:5173
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=600
AI_ENABLED=false                 # optional; the engine never requires it
AI_PROVIDER=anthropic
AI_MODEL=claude-sonnet-5-5
AI_API_KEY=                      # never committed; read from the environment`}
                  </pre>
                </div>
              </div>
            </div>
          )}

          {tab === 'states' && (
            <>
              {stateMachine.loading && !stateMachine.data ? (
                <Loading rows={8} />
              ) : (
                <DataTable
                  columns={[
                    {
                      key: 'from',
                      header: 'From state',
                      render: (row) => <StatusChip value={row.from} mode="raw" tone={toneFor(row.from)} />,
                    },
                    {
                      key: 'to',
                      header: 'Permitted transitions',
                      render: (row) =>
                        row.to.length === 0 ? (
                          <span className="dim">terminal</span>
                        ) : (
                          <div className="row-wrap">
                            {row.to.map((state) => (
                              <span className="tag" key={state}>
                                {state}
                              </span>
                            ))}
                          </div>
                        ),
                    },
                    {
                      key: 'kind',
                      header: 'Kind',
                      render: (row) => (
                        <div className="row-tight">
                          {row.isTerminal && <span className="tag">terminal</span>}
                          {row.isFailure && (
                            <span className="tag" style={{ color: 'var(--error)' }}>
                              failure
                            </span>
                          )}
                        </div>
                      ),
                    },
                  ]}
                  rows={stateMachine.data?.transitions ?? []}
                  rowKey={(row) => row.from}
                />
              )}
            </>
          )}

          {tab === 'stages' && (
            <DataTable
              columns={[
                { key: 'sequence', header: '#', numeric: true, render: (row) => String(row.sequence + 1) },
                { key: 'stage', header: 'Stage', render: (row) => <span className="mono">{row.stageKey}</span> },
                { key: 'business', header: 'Business label', render: (row) => row.businessLabel },
                { key: 'technical', header: 'Technical label', render: (row) => row.technicalLabel },
              ]}
              rows={stateMachine.data?.stages ?? []}
              rowKey={(row) => row.stageKey}
            />
          )}
        </Panel>
      </div>
    </div>
  )
}
