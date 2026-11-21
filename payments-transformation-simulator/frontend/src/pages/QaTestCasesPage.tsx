/**
 * Test-case generator.
 *
 * Generation reads the rule's own parameters, so a boundary case uses the real
 * scheme ceiling rather than a hand-written number. Running a case executes it
 * against the engine and compares the outcome.
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { TestCase } from '../api/types'
import { useAction, useAsync } from '../hooks/useAsync'
import { formatDateTime } from '../lib/format'
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
} from '../components/ui'

const TYPE_TONES: Record<string, 'ok' | 'error' | 'warn' | 'info' | 'neutral'> = {
  POSITIVE: 'ok',
  NEGATIVE: 'error',
  BOUNDARY: 'warn',
  EXCEPTION: 'error',
  INTEGRATION: 'info',
  REGRESSION: 'neutral',
  RECONCILIATION: 'info',
}

export function QaTestCasesPage() {
  const [ruleId, setRuleId] = useState('SIC-AMOUNT-001')
  const [scheme, setScheme] = useState('SIC_INSTANT')
  const [selected, setSelected] = useState<TestCase | null>(null)
  const [runSummary, setRunSummary] = useState<{ total: number; passed: number; failed: number } | null>(
    null,
  )

  const schemes = useAsync((signal) => api.schemes(signal), [])
  const cases = useAsync((signal) => api.testCases({}, signal), [])

  const generate = useAction(() => api.generateTestCases({ ruleId, scheme, persist: true }), {
    onSuccess: () => {
      setRunSummary(null)
      cases.reload()
    },
  })
  const run = useAction(() => api.runTestCases({ ruleId }), {
    onSuccess: (data) => {
      setRunSummary({ total: data.total, passed: data.passed, failed: data.failed })
      cases.reload()
    },
  })

  const generatable = cases.data?.generatableRules ?? []
  const rows = cases.data?.items ?? []

  return (
    <div className="page">
      <PageHeader
        eyebrow="QA Lab"
        title="Test case generator"
        lede="Pick a rule and generate the cases a payments QA lead would write: positive, negative, boundary, exception, integration, regression and reconciliation."
      />

      <div className="stack">
        <Panel title="Generate from a rule">
          <div className="col">
            <div className="form-grid">
              <Field
                label="Rule"
                hint={
                  generatable.find((item) => item.ruleId === ruleId)?.hasBoundaryAnalysis
                    ? 'This rule has parameters, so real boundary values are derived from it'
                    : 'Generic generation: positive, negative via the matching injection, plus the standard suites'
                }
              >
                <select value={ruleId} onChange={(event) => setRuleId(event.target.value)}>
                  {generatable.map((item) => (
                    <option key={item.ruleId} value={item.ruleId}>
                      {item.ruleId} — {item.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Scheme">
                <select value={scheme} onChange={(event) => setScheme(event.target.value)}>
                  {(schemes.data?.items ?? []).map((item) => (
                    <option key={item.code} value={item.code}>
                      {item.shortName}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            {generate.error && <ErrorState error={generate.error} />}
            {run.error && <ErrorState error={run.error} />}
            <div className="row-tight">
              <button
                type="button"
                className="btn"
                data-variant="primary"
                onClick={() => void generate.run()}
                disabled={generate.pending}
              >
                {generate.pending ? 'Generating…' : 'Generate test cases'}
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => void run.run()}
                disabled={run.pending || rows.filter((row) => row.ruleId === ruleId).length === 0}
              >
                {run.pending ? 'Executing…' : 'Run the suite against the engine'}
              </button>
            </div>
            {runSummary && (
              <Notice
                tone={runSummary.failed === 0 ? 'ok' : 'error'}
                title={`${runSummary.passed} of ${runSummary.total} cases passed`}
              >
                {runSummary.failed === 0
                  ? 'Every generated case behaved as it expects. The rule and the generator agree.'
                  : `${runSummary.failed} case(s) did not match. Open a case to see the comparison.`}
              </Notice>
            )}
          </div>
        </Panel>

        {cases.data?.suites && cases.data.suites.length > 0 && (
          <div className="row-wrap">
            {cases.data.suites.map((suite) => (
              <span className="tag" key={suite.suite}>
                {suite.suite} · {suite.cases} cases
              </span>
            ))}
          </div>
        )}

        <Panel title={`${rows.length} test cases`} flush>
          {cases.loading && !cases.data ? (
            <Loading rows={8} />
          ) : (
            <DataTable
              columns={[
                {
                  key: 'caseId',
                  header: 'Case',
                  render: (row) => (
                    <>
                      <div className="cell-primary">{row.caseId}</div>
                      <div className="cell-secondary">{row.suite}</div>
                    </>
                  ),
                },
                {
                  key: 'type',
                  header: 'Type',
                  render: (row) => (
                    <StatusChip value={row.testType} mode="raw" tone={TYPE_TONES[row.testType] ?? 'neutral'} />
                  ),
                },
                { key: 'title', header: 'Title', render: (row) => row.title },
                {
                  key: 'expected',
                  header: 'Expected',
                  render: (row) => (
                    <div className="col-tight">
                      {row.expectedStatus && <StatusChip value={row.expectedStatus} mode="raw" />}
                      {row.expectedRuleOutcome && (
                        <span className="cell-secondary mono">
                          {row.ruleId}: {row.expectedRuleOutcome}
                        </span>
                      )}
                    </div>
                  ),
                },
                {
                  key: 'priority',
                  header: 'Priority',
                  render: (row) => <span className="tag">{row.priority}</span>,
                },
                {
                  key: 'lastRun',
                  header: 'Last run',
                  render: (row) =>
                    row.lastRunOutcome ? (
                      <>
                        <StatusChip
                          value={row.lastRunOutcome}
                          mode="raw"
                          tone={row.lastRunOutcome === 'PASSED' ? 'ok' : 'error'}
                        />
                        <div className="cell-secondary">{formatDateTime(row.lastRunAt)}</div>
                      </>
                    ) : (
                      <span className="dim">never</span>
                    ),
                },
                {
                  key: 'requirement',
                  header: 'Requirement',
                  render: (row) => <span className="mono">{row.requirementId ?? '—'}</span>,
                },
              ]}
              rows={rows}
              rowKey={(row) => `${row.suite}-${row.caseId}`}
              onRowClick={(row) => setSelected(row)}
              emptyTitle="No test cases yet"
              emptyBody="Generate a suite from a rule above."
            />
          )}
        </Panel>
      </div>

      {selected && <CaseDrawer testCase={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

function CaseDrawer({ testCase, onClose }: { testCase: TestCase; onClose: () => void }) {
  const detail = testCase.lastRunDetail as {
    paymentReference?: string
    checks?: { name: string; expected: string; actual: string; passed: boolean; message?: string }[]
  }

  return (
    <Drawer title={`${testCase.caseId} — ${testCase.title}`} subtitle={testCase.suite} onClose={onClose}>
      <div className="col">
        <KeyValue
          items={[
            { label: 'Test type', value: testCase.testType, mono: true },
            { label: 'Rule under test', value: testCase.ruleId ?? '—', mono: true },
            { label: 'Scheme', value: testCase.scheme, mono: true },
            { label: 'Priority', value: testCase.priority, mono: true },
            { label: 'Requirement', value: testCase.requirementId ?? '—', mono: true },
            { label: 'Expected result', value: testCase.expectedResult },
          ]}
        />

        <div className="col-tight">
          <span className="label">Preconditions</span>
          <ul className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
            {testCase.preconditions.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>

        <div className="col-tight">
          <span className="label">Steps</span>
          <ol className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
            {testCase.steps.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ol>
        </div>

        <div className="col-tight">
          <span className="label">Input data</span>
          <pre className="code-block" style={{ maxHeight: 280 }}>
            {JSON.stringify(testCase.inputData, null, 2)}
          </pre>
        </div>

        {detail?.checks && (
          <div className="col-tight">
            <span className="label">Last execution</span>
            <DataTable
              columns={[
                { key: 'name', header: 'Check', render: (row) => row.name },
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
              rows={detail.checks}
              rowKey={(row) => row.name}
            />
            {detail.paymentReference && (
              <Link className="btn" to={`/payments/${detail.paymentReference}`}>
                Open the payment this case produced
              </Link>
            )}
          </div>
        )}
      </div>
    </Drawer>
  )
}
