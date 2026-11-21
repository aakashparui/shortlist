/**
 * BA workbench.
 *
 * Business requirement → functional requirement → business rule → payment flow
 * → ISO 20022 message → test case. Every artefact is derived from the live
 * scheme configuration and rule book, so the documentation cannot drift away
 * from what the engine does.
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import { useAsync } from '../hooks/useAsync'
import { toneFor } from '../lib/format'
import {
  DataTable,
  ErrorState,
  Field,
  KeyValue,
  Loading,
  Notice,
  PageHeader,
  Panel,
  SimulationNote,
  StatusChip,
  Tabs,
} from '../components/ui'

type Tab =
  | 'requirement'
  | 'functional'
  | 'rules'
  | 'flow'
  | 'acceptance'
  | 'exceptions'
  | 'tests'
  | 'traceability'

export function BaWorkbenchPage() {
  const [scheme, setScheme] = useState('SIC_INSTANT')
  const [scenarioCode, setScenarioCode] = useState('')
  const [tab, setTab] = useState<Tab>('requirement')

  const context = useAsync((signal) => api.baContext(signal), [])
  const scenarios = useAsync((signal) => api.scenarios(signal), [])
  const pkg = useAsync(
    (signal) => api.baPackage(scheme, scenarioCode || null, signal),
    [scheme, scenarioCode],
  )

  const data = pkg.data

  return (
    <div className="page">
      <PageHeader
        eyebrow="BA Workbench"
        title="Requirements & traceability"
        lede="The artefact chain a payments BA is asked to deliver, generated from the system's own configuration rather than written by hand."
      />

      <div className="stack">
        {context.data && (
          <div className="flow">
            {context.data.artefactChain.map((item, index) => (
              <div className="row-tight" key={item}>
                <div className="flow-node">
                  <div className="flow-node-title">Step {index + 1}</div>
                  <div>{item}</div>
                </div>
                {index < context.data!.artefactChain.length - 1 && (
                  <span className="flow-arrow" aria-hidden="true">
                    →
                  </span>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="filters">
          <Field label="Scheme">
            <select value={scheme} onChange={(event) => setScheme(event.target.value)}>
              {(context.data?.schemes ?? []).map((item) => (
                <option key={item.code} value={item.code}>
                  {item.shortName} — {item.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Focus scenario" hint="Optional: adds a scenario-specific acceptance criterion">
            <select value={scenarioCode} onChange={(event) => setScenarioCode(event.target.value)}>
              <option value="">All scenarios</option>
              {(scenarios.data?.items ?? []).map((item) => (
                <option key={item.code} value={item.code}>
                  {item.code} — {item.title}
                </option>
              ))}
            </select>
          </Field>
        </div>

        {pkg.loading && !data && <Loading rows={10} />}
        {pkg.error && <ErrorState error={pkg.error} onRetry={pkg.reload} />}

        {data && (
          <Panel flush>
            <Tabs
              tabs={[
                { id: 'requirement', label: 'Business requirement' },
                { id: 'functional', label: 'Functional requirements', count: data.functionalRequirements.length },
                { id: 'rules', label: 'Business rules', count: data.businessRules.length },
                { id: 'flow', label: 'Process flow', count: data.processFlow.length },
                { id: 'acceptance', label: 'Acceptance criteria', count: data.acceptanceCriteria.length },
                { id: 'exceptions', label: 'Exception scenarios', count: data.exceptionScenarios.length },
                { id: 'tests', label: 'Test scenarios', count: data.testScenarios.length },
                { id: 'traceability', label: 'Traceability matrix', count: data.traceabilityMatrix.length },
              ]}
              active={tab}
              onChange={(id) => setTab(id as Tab)}
            />

            <div style={{ padding: tab === 'requirement' ? 'var(--s-5)' : 0 }}>
              {tab === 'requirement' && (
                <div className="col">
                  <Notice tone="info" title={`${data.businessRequirement.id} — ${data.businessRequirement.title}`}>
                    {data.businessRequirement.statement}
                  </Notice>
                  <KeyValue items={[{ label: 'Rationale', value: data.businessRequirement.rationale }]} />
                  <div className="grid grid-2">
                    <ListPanel title="In scope" items={data.businessRequirement.scope} />
                    <ListPanel title="Out of scope" items={data.businessRequirement.outOfScope} />
                    <ListPanel title="Assumptions" items={data.businessRequirement.assumptions} />
                    <ListPanel title="Stakeholders" items={data.businessRequirement.stakeholders} />
                  </div>
                  <SimulationNote>{data.scheme.simulationNotes}</SimulationNote>
                </div>
              )}

              {tab === 'functional' && (
                <DataTable
                  columns={[
                    { key: 'id', header: 'ID', render: (row) => <span className="mono">{row.id}</span> },
                    {
                      key: 'title',
                      header: 'Requirement',
                      render: (row) => (
                        <>
                          <div>{row.title}</div>
                          <div className="cell-secondary">{row.statement}</div>
                        </>
                      ),
                    },
                    { key: 'stage', header: 'Stage', render: (row) => <span className="tag">{row.stage}</span> },
                    {
                      key: 'rules',
                      header: 'Enforced by',
                      render: (row) =>
                        row.ruleIds.length === 0 ? (
                          <span className="dim">orchestration behaviour</span>
                        ) : (
                          <div className="row-wrap">
                            {row.ruleIds.map((ruleId) => (
                              <Link className="tag" to={`/system/rules?ruleId=${ruleId}`} key={ruleId}>
                                {ruleId}
                              </Link>
                            ))}
                          </div>
                        ),
                    },
                  ]}
                  rows={data.functionalRequirements}
                  rowKey={(row) => row.id}
                />
              )}

              {tab === 'rules' && (
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
                    { key: 'description', header: 'Rule', render: (row) => row.description },
                    { key: 'category', header: 'Category', render: (row) => <span className="tag">{row.category}</span> },
                    { key: 'severity', header: 'Severity', render: (row) => <StatusChip value={row.severity} mode="raw" /> },
                    { key: 'behaviour', header: 'On failure', render: (row) => row.failureBehaviour },
                    {
                      key: 'basis',
                      header: 'Standard basis',
                      render: (row) => <span className="cell-secondary">{row.standardBasis || '—'}</span>,
                    },
                  ]}
                  rows={data.businessRules}
                  rowKey={(row) => row.ruleId}
                />
              )}

              {tab === 'flow' && (
                <DataTable
                  columns={[
                    { key: 'step', header: '#', numeric: true, render: (row) => String(row.step) },
                    {
                      key: 'stage',
                      header: 'Stage',
                      render: (row) => (
                        <>
                          <div className="cell-primary">{row.stage}</div>
                          <div className="cell-secondary">{row.businessLabel}</div>
                        </>
                      ),
                    },
                    { key: 'technical', header: 'Technically', render: (row) => row.technicalLabel },
                    { key: 'actor', header: 'Actor', render: (row) => row.actor },
                    { key: 'output', header: 'Output', render: (row) => row.output },
                  ]}
                  rows={data.processFlow}
                  rowKey={(row) => row.stage}
                />
              )}

              {tab === 'acceptance' && (
                <DataTable
                  columns={[
                    { key: 'id', header: 'ID', render: (row) => <span className="mono">{row.id}</span> },
                    { key: 'given', header: 'Given', render: (row) => row.given },
                    { key: 'when', header: 'When', render: (row) => row.when },
                    { key: 'then', header: 'Then', render: (row) => row.then },
                    {
                      key: 'link',
                      header: 'Requirement',
                      render: (row) => <span className="mono">{row.linkedRequirement}</span>,
                    },
                  ]}
                  rows={data.acceptanceCriteria}
                  rowKey={(row) => row.id}
                />
              )}

              {tab === 'exceptions' && (
                <DataTable
                  columns={[
                    {
                      key: 'scenario',
                      header: 'Scenario',
                      render: (row) => (
                        <>
                          <div className="cell-primary">{row.scenarioCode}</div>
                          <div className="cell-secondary">{row.title}</div>
                        </>
                      ),
                    },
                    { key: 'trigger', header: 'Trigger', render: (row) => row.trigger },
                    { key: 'detected', header: 'Detected at', render: (row) => <span className="tag">{row.detectedAt}</span> },
                    {
                      key: 'status',
                      header: 'Resulting status',
                      render: (row) => <StatusChip value={row.expectedStatus} mode="raw" tone={toneFor(row.expectedStatus)} />,
                    },
                    { key: 'response', header: 'Operational response', render: (row) => row.operationalResponse },
                    { key: 'impact', header: 'Customer impact', render: (row) => row.customerImpact },
                  ]}
                  rows={data.exceptionScenarios}
                  rowKey={(row) => row.scenarioCode}
                />
              )}

              {tab === 'tests' && (
                <DataTable
                  columns={[
                    { key: 'id', header: 'ID', render: (row) => <span className="mono">{row.testScenarioId}</span> },
                    { key: 'title', header: 'Scenario', render: (row) => row.title },
                    { key: 'category', header: 'Category', render: (row) => <span className="tag">{row.category}</span> },
                    {
                      key: 'expected',
                      header: 'Expected status',
                      render: (row) => <StatusChip value={row.expectedStatus} mode="raw" />,
                    },
                    {
                      key: 'messages',
                      header: 'Expected messages',
                      render: (row) =>
                        row.expectedMessages.length > 0 ? (
                          <span className="mono" style={{ fontSize: 'var(--fs-xs)' }}>
                            {row.expectedMessages.join(', ')}
                          </span>
                        ) : (
                          <span className="dim">none</span>
                        ),
                    },
                    {
                      key: 'recon',
                      header: 'Reconciliation',
                      render: (row) => (
                        <StatusChip value={row.expectedReconciliation} mode="raw" tone={toneFor(row.expectedReconciliation)} />
                      ),
                    },
                    {
                      key: 'run',
                      header: '',
                      render: (row) => (
                        <Link className="btn" data-size="sm" to={`/qa/scenarios?code=${row.scenarioCode}`}>
                          Open
                        </Link>
                      ),
                    },
                  ]}
                  rows={data.testScenarios}
                  rowKey={(row) => row.testScenarioId}
                />
              )}

              {tab === 'traceability' && (
                <DataTable
                  columns={[
                    {
                      key: 'br',
                      header: 'Business requirement',
                      render: (row) => <span className="mono">{row.businessRequirementId}</span>,
                    },
                    {
                      key: 'fr',
                      header: 'Functional requirement',
                      render: (row) => (
                        <>
                          <div className="cell-primary">{row.functionalRequirementId}</div>
                          <div className="cell-secondary">{row.functionalRequirement}</div>
                        </>
                      ),
                    },
                    {
                      key: 'rules',
                      header: 'Business rules',
                      render: (row) =>
                        row.businessRuleIds.length === 0 ? (
                          <span className="dim">—</span>
                        ) : (
                          <div className="row-wrap">
                            {row.businessRuleIds.map((ruleId) => (
                              <span className="tag" key={ruleId}>
                                {ruleId}
                              </span>
                            ))}
                          </div>
                        ),
                    },
                    { key: 'stage', header: 'Payment stage', render: (row) => <span className="tag">{row.stage}</span> },
                    {
                      key: 'messages',
                      header: 'ISO messages',
                      render: (row) =>
                        row.isoMessages.length > 0 ? (
                          <span className="mono" style={{ fontSize: 'var(--fs-xs)' }}>
                            {row.isoMessages.join(', ')}
                          </span>
                        ) : (
                          <span className="dim">—</span>
                        ),
                    },
                    {
                      key: 'tests',
                      header: 'Test scenarios',
                      render: (row) => (
                        <span className="mono" style={{ fontSize: 'var(--fs-xs)' }}>
                          {row.testScenarioIds.join(', ')}
                        </span>
                      ),
                    },
                    {
                      key: 'coverage',
                      header: 'Coverage',
                      render: (row) => (
                        <StatusChip
                          value={row.coverage}
                          mode="raw"
                          tone={row.coverage === 'COVERED' ? 'ok' : 'warn'}
                        />
                      ),
                    },
                  ]}
                  rows={data.traceabilityMatrix}
                  rowKey={(row) => row.functionalRequirementId}
                />
              )}
            </div>
          </Panel>
        )}
      </div>
    </div>
  )
}

function ListPanel({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">{title}</span>
      </div>
      <div className="panel-body">
        <ul className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
          {items.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      </div>
    </div>
  )
}
