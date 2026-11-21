/** Scenario library: 20 executable scenarios with expected vs actual comparison. */

import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { api } from '../api/client'
import type { Scenario, ScenarioRunResult } from '../api/types'
import { useAction, useAsync } from '../hooks/useAsync'
import { formatDateTime, toneFor } from '../lib/format'
import {
  DataTable,
  Drawer,
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

export function QaScenariosPage() {
  const [params] = useSearchParams()
  const [tab, setTab] = useState<'library' | 'runs'>('library')
  const [category, setCategory] = useState('')
  const [selected, setSelected] = useState<Scenario | null>(null)
  const [result, setResult] = useState<ScenarioRunResult | null>(null)
  const [runAll, setRunAll] = useState<{ total: number; passed: number; failed: number } | null>(null)

  const scenarios = useAsync((signal) => api.scenarios(signal), [])
  const executions = useAsync((signal) => api.scenarioExecutions(50, signal), [tab, result])

  const run = useAction((code: string) => api.runScenario(code, { processingMode: 'IMMEDIATE' }), {
    onSuccess: (data) => {
      setResult(data)
      executions.reload()
    },
  })
  const runEverything = useAction(() => api.runAllScenarios(), {
    onSuccess: (data) => {
      setRunAll({ total: data.total, passed: data.passed, failed: data.failed })
      executions.reload()
    },
  })

  const highlighted = params.get('code')
  const rows = (scenarios.data?.items ?? []).filter(
    (item) => !category || item.category === category,
  )

  return (
    <div className="page">
      <PageHeader
        eyebrow="QA Lab"
        title="Scenario library"
        lede="Each scenario is a complete, runnable payment plus the failure injections that reproduce a specific operational situation, and the assertions that say what correct looks like."
        actions={
          <button
            type="button"
            className="btn"
            data-variant="primary"
            onClick={() => void runEverything.run()}
            disabled={runEverything.pending}
          >
            {runEverything.pending ? 'Running all 20…' : 'Run the whole library'}
          </button>
        }
      />

      <div className="stack">
        {runEverything.error && <ErrorState error={runEverything.error} />}
        {run.error && <ErrorState error={run.error} />}

        {runAll && (
          <Notice
            tone={runAll.failed === 0 ? 'ok' : 'error'}
            title={`${runAll.passed} of ${runAll.total} scenarios met every expectation`}
          >
            {runAll.failed === 0
              ? 'The engine behaved exactly as every scenario specifies.'
              : `${runAll.failed} scenario(s) did not match. Open the runs tab to see which assertion failed.`}
          </Notice>
        )}

        <Panel flush>
          <Tabs
            tabs={[
              { id: 'library', label: 'Library', count: scenarios.data?.items.length },
              { id: 'runs', label: 'Executions', count: executions.data?.items.length },
            ]}
            active={tab}
            onChange={(id) => setTab(id as typeof tab)}
          />

          {tab === 'library' && (
            <>
              <div
                className="filters"
                style={{ border: 0, borderBottom: '1px solid var(--line)', borderRadius: 0 }}
              >
                <Field label="Category">
                  <select value={category} onChange={(event) => setCategory(event.target.value)}>
                    <option value="">All categories</option>
                    {(scenarios.data?.categories ?? []).map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>

              {scenarios.loading && !scenarios.data ? (
                <Loading rows={8} />
              ) : (
                <DataTable
                  columns={[
                    {
                      key: 'code',
                      header: 'Scenario',
                      render: (row) => (
                        <>
                          <div className="cell-primary">{row.code}</div>
                          {row.isDemoHighlight && <div className="cell-secondary">demo highlight</div>}
                        </>
                      ),
                    },
                    {
                      key: 'title',
                      header: 'What it reproduces',
                      render: (row) => (
                        <>
                          <div>{row.title}</div>
                          <div className="cell-secondary">{row.description}</div>
                        </>
                      ),
                    },
                    {
                      key: 'category',
                      header: 'Category',
                      render: (row) => <span className="tag">{row.category}</span>,
                    },
                    { key: 'scheme', header: 'Rail', render: (row) => <span className="tag">{row.scheme}</span> },
                    {
                      key: 'expected',
                      header: 'Expected status',
                      render: (row) => <StatusChip value={row.expectedStatus} mode="raw" />,
                    },
                    {
                      key: 'injections',
                      header: 'Injections',
                      render: (row) =>
                        row.failureCodes.length === 0 ? (
                          <span className="dim">none</span>
                        ) : (
                          <div className="row-wrap">
                            {row.failureCodes.map((code) => (
                              <span className="tag" key={code} data-tone="accent">
                                {code}
                              </span>
                            ))}
                          </div>
                        ),
                    },
                    {
                      key: 'run',
                      header: '',
                      render: (row) => (
                        <button
                          type="button"
                          className="btn"
                          data-size="sm"
                          disabled={run.pending}
                          onClick={(event) => {
                            event.stopPropagation()
                            void run.run(row.code)
                          }}
                        >
                          Run
                        </button>
                      ),
                    },
                  ]}
                  rows={rows}
                  rowKey={(row) => row.code}
                  selectedKey={highlighted}
                  onRowClick={(row) => setSelected(row)}
                />
              )}
            </>
          )}

          {tab === 'runs' && (
            <DataTable
              columns={[
                {
                  key: 'reference',
                  header: 'Run',
                  render: (row) => (
                    <>
                      <div className="cell-primary">{row.reference}</div>
                      <div className="cell-secondary">{formatDateTime(row.startedAt)}</div>
                    </>
                  ),
                },
                {
                  key: 'scenario',
                  header: 'Scenario',
                  render: (row) => (
                    <>
                      <div>{row.scenarioCode}</div>
                      <div className="cell-secondary">{row.scenarioTitle}</div>
                    </>
                  ),
                },
                {
                  key: 'outcome',
                  header: 'Outcome',
                  render: (row) => (
                    <StatusChip
                      value={row.outcome}
                      mode="raw"
                      tone={row.outcome === 'PASSED' ? 'ok' : row.outcome === 'FAILED' ? 'error' : 'pending'}
                    />
                  ),
                },
                {
                  key: 'expected',
                  header: 'Expected',
                  render: (row) => <StatusChip value={row.expectedStatus ?? ''} mode="raw" />,
                },
                {
                  key: 'actual',
                  header: 'Actual',
                  render: (row) => <StatusChip value={row.actualStatus ?? ''} mode="raw" />,
                },
                {
                  key: 'payment',
                  header: 'Payment',
                  render: (row) =>
                    row.paymentReference ? (
                      <Link to={`/payments/${row.paymentReference}`} className="mono">
                        {row.paymentReference}
                      </Link>
                    ) : (
                      '—'
                    ),
                },
                {
                  key: 'assertions',
                  header: 'Assertions',
                  render: (row) => (
                    <div className="col-tight">
                      {row.assertions.map((assertion, index) => (
                        <span
                          key={index}
                          className={assertion.passed ? 'cell-secondary' : 'cell-secondary text-error'}
                        >
                          {assertion.passed ? '✓' : '✕'} {assertion.name}
                          {!assertion.passed && ` — expected ${assertion.expected}, got ${assertion.actual}`}
                        </span>
                      ))}
                    </div>
                  ),
                },
              ]}
              rows={executions.data?.items ?? []}
              rowKey={(row) => row.reference}
              emptyTitle="No scenario runs yet"
            />
          )}
        </Panel>
      </div>

      {selected && (
        <Drawer
          title={`${selected.code} — ${selected.title}`}
          subtitle={`${selected.category} · ${selected.scheme}`}
          onClose={() => setSelected(null)}
        >
          <div className="col">
            <Notice tone="info" title="Why this scenario matters">
              {selected.businessContext}
            </Notice>
            <ListBlock title="Preconditions" items={selected.preconditions} />
            <ListBlock title="Execution steps" items={selected.executionSteps} ordered />
            <ListBlock title="Expected result" items={selected.expectedResult} />
            <ListBlock title="Expected messages" items={selected.expectedMessages} mono />
            <ListBlock title="Expected accounting" items={selected.expectedAccounting} />
            <KeyValue
              items={[
                { label: 'Expected status', value: <StatusChip value={selected.expectedStatus} mode="raw" /> },
                {
                  label: 'Expected reconciliation',
                  value: (
                    <StatusChip
                      value={selected.expectedReconciliation}
                      mode="raw"
                      tone={toneFor(selected.expectedReconciliation)}
                    />
                  ),
                },
                {
                  label: 'Failure injections',
                  value: selected.failureCodes.join(', ') || 'none',
                  mono: true,
                },
              ]}
            />
            <ListBlock title="This scenario fails if" items={selected.failureConditions} />
            <button
              type="button"
              className="btn"
              data-variant="primary"
              disabled={run.pending}
              onClick={() => void run.run(selected.code)}
            >
              {run.pending ? 'Running…' : 'Run this scenario'}
            </button>
          </div>
        </Drawer>
      )}

      {result && (
        <Drawer
          title={`${result.scenario.code} — ${result.passed ? 'passed' : 'failed'}`}
          subtitle={result.execution.reference}
          onClose={() => setResult(null)}
        >
          <div className="col">
            <Notice tone={result.passed ? 'ok' : 'error'} title="Expected versus actual">
              {result.passed
                ? 'Every assertion in the scenario matched what the engine actually did.'
                : 'At least one assertion did not match. The engine is the source of truth here, not the scenario.'}
            </Notice>
            <DataTable
              columns={[
                { key: 'name', header: 'Assertion', render: (row) => row.name },
                { key: 'expected', header: 'Expected', render: (row) => <span className="mono">{row.expected}</span> },
                { key: 'actual', header: 'Actual', render: (row) => <span className="mono">{row.actual}</span> },
                {
                  key: 'passed',
                  header: 'Result',
                  render: (row) => (
                    <StatusChip
                      value={row.passed ? 'PASSED' : 'FAILED'}
                      mode="raw"
                      tone={row.passed ? 'ok' : 'error'}
                    />
                  ),
                },
              ]}
              rows={result.assertions}
              rowKey={(row) => row.name}
            />
            <KeyValue
              items={[
                {
                  label: 'Payment produced',
                  value: (
                    <Link to={`/payments/${result.payment.reference}`} className="mono">
                      {result.payment.reference}
                    </Link>
                  ),
                },
                { label: 'Final status', value: <StatusChip value={result.payment.status} /> },
                {
                  label: 'Messages',
                  value: result.payment.messages.map((m) => m.messageType).join(', ') || 'none',
                  mono: true,
                },
                ...(result.execution.notes ? [{ label: 'Notes', value: result.execution.notes }] : []),
              ]}
            />
            <Link className="btn" data-variant="primary" to={`/payments/${result.payment.reference}`}>
              Open the payment journey
            </Link>
          </div>
        </Drawer>
      )}
    </div>
  )
}

function ListBlock({
  title,
  items,
  ordered,
  mono,
}: {
  title: string
  items: string[]
  ordered?: boolean
  mono?: boolean
}) {
  if (items.length === 0) return null
  const List = ordered ? 'ol' : 'ul'
  return (
    <div className="col-tight">
      <span className="label">{title}</span>
      <List className={mono ? 'muted mono' : 'muted'} style={{ fontSize: 'var(--fs-sm)' }}>
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </List>
    </div>
  )
}
