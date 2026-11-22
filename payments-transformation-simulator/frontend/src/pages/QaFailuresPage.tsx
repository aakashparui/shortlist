/**
 * Failure injection engine.
 *
 * The catalogue explains, for each failure, the mechanism by which it is caused
 * and the outcome it is expected to produce. A failure can be armed on an
 * existing payment here and then executed.
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { FailureDefinition } from '../api/types'
import { useAction, useAsync } from '../hooks/useAsync'
import { schemeLabel, toneFor } from '../lib/format'
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

export function QaFailuresPage() {
  const [category, setCategory] = useState('')
  const [selected, setSelected] = useState<FailureDefinition | null>(null)

  const catalogue = useAsync((signal) => api.failureCatalogue(signal), [])
  const candidates = useAsync(
    (signal) => api.listPayments({ pageSize: 30, status: ['INITIATED', 'DRAFT'] }, signal),
    [],
  )

  const rows = (catalogue.data?.items ?? []).filter((item) => !category || item.category === category)
  const categories = Object.keys(catalogue.data?.byCategory ?? {})

  return (
    <div className="page">
      <PageHeader
        eyebrow="QA Lab"
        title="Failure injection"
        lede="An injection never fakes a result. It changes the instruction, or the behaviour of a downstream system, and the engines then fail for real."
      />

      <div className="stack">
        {catalogue.data && <Notice tone="info" title="How injection works">{catalogue.data.note}</Notice>}

        <div className="filters">
          <Field label="Category">
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              <option value="">All categories</option>
              {categories.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </Field>
          <span className="spacer" />
          <div className="row-wrap">
            {categories.map((item) => (
              <span className="tag" key={item}>
                {item} {catalogue.data?.byCategory[item]?.length ?? 0}
              </span>
            ))}
          </div>
        </div>

        <Panel
          title={`${rows.length} failure modes`}
          subtitle="Select one to see the mechanism and arm it on a payment"
          flush
        >
          {catalogue.loading && !catalogue.data ? (
            <Loading rows={8} />
          ) : catalogue.error ? (
            <div style={{ padding: 'var(--s-5)' }}>
              <ErrorState error={catalogue.error} onRetry={catalogue.reload} />
            </div>
          ) : (
            <DataTable
              columns={[
                {
                  key: 'code',
                  header: 'Code',
                  render: (row) => (
                    <>
                      <div className="cell-primary">{row.code}</div>
                      <div className="cell-secondary">{row.label}</div>
                    </>
                  ),
                },
                {
                  key: 'category',
                  header: 'Category',
                  render: (row) => <span className="tag">{row.category}</span>,
                },
                { key: 'stage', header: 'Fails at', render: (row) => <span className="tag">{row.stage}</span> },
                { key: 'description', header: 'What it does', render: (row) => row.description },
                {
                  key: 'expected',
                  header: 'Expected status',
                  render: (row) => (
                    <StatusChip value={row.expectedStatus} mode="raw" tone={toneFor(row.expectedStatus)} />
                  ),
                },
                {
                  key: 'rules',
                  header: 'Rules it trips',
                  render: (row) =>
                    row.affectedRuleIds.length === 0 ? (
                      <span className="dim">—</span>
                    ) : (
                      <div className="row-wrap">
                        {row.affectedRuleIds.map((ruleId) => (
                          <Link
                            key={ruleId}
                            className="tag"
                            to={`/system/rules?ruleId=${ruleId}`}
                            onClick={(event) => event.stopPropagation()}
                          >
                            {ruleId}
                          </Link>
                        ))}
                      </div>
                    ),
                },
              ]}
              rows={rows}
              rowKey={(row) => row.code}
              onRowClick={(row) => setSelected(row)}
            />
          )}
        </Panel>
      </div>

      {selected && (
        <ArmDrawer
          definition={selected}
          candidates={candidates.data?.items ?? []}
          onClose={() => setSelected(null)}
          onArmed={() => candidates.reload()}
        />
      )}
    </div>
  )
}

function ArmDrawer({
  definition,
  candidates,
  onClose,
  onArmed,
}: {
  definition: FailureDefinition
  candidates: { reference: string; amount: string; currency: string; scheme: string; status: string }[]
  onClose: () => void
  onArmed: () => void
}) {
  const [reference, setReference] = useState(candidates[0]?.reference ?? '')
  const [armed, setArmed] = useState<string | null>(null)

  const arm = useAction(
    () => api.injectFailure(reference, { code: definition.code, parameters: {} }),
    { onSuccess: () => { setArmed(reference); onArmed() } },
  )
  const execute = useAction(
    () => api.executePayment(reference, { processingMode: 'IMMEDIATE', waitForCompletion: true }),
    { onSuccess: () => onArmed() },
  )

  return (
    <Drawer title={definition.label} subtitle={definition.code} onClose={onClose}>
      <div className="col">
        <KeyValue
          items={[
            { label: 'Category', value: definition.category, mono: true },
            { label: 'Fails at stage', value: definition.stage, mono: true },
            { label: 'What it does', value: definition.description },
            { label: 'Mechanism', value: definition.mechanism },
            { label: 'Expected outcome', value: definition.expectedOutcome },
            {
              label: 'Expected status',
              value: <StatusChip value={definition.expectedStatus} mode="raw" />,
            },
            ...(definition.affectedRuleIds.length > 0
              ? [{ label: 'Rules affected', value: definition.affectedRuleIds.join(', '), mono: true }]
              : []),
            ...(Object.keys(definition.parameters).length > 0
              ? [
                  {
                    label: 'Default parameters',
                    value: JSON.stringify(definition.parameters),
                    mono: true,
                  },
                ]
              : []),
          ]}
        />

        <hr />

        <div className="col">
          <span className="label">Arm it on a payment</span>
          {candidates.length === 0 ? (
            <Notice tone="warn" title="No un-executed payments available">
              Create a payment without executing it, or select the injection directly on the payment
              simulator screen.
            </Notice>
          ) : (
            <>
              <Field
                label="Payment"
                hint="Only payments that have not been executed yet can have a failure armed"
              >
                <select value={reference} onChange={(event) => setReference(event.target.value)}>
                  {candidates.map((item) => (
                    <option key={item.reference} value={item.reference}>
                      {item.reference} — {item.amount} {item.currency} ({schemeLabel(item.scheme)})
                    </option>
                  ))}
                </select>
              </Field>
              {arm.error && <ErrorState error={arm.error} />}
              {execute.error && <ErrorState error={execute.error} />}
              <div className="row-tight">
                <button
                  type="button"
                  className="btn"
                  onClick={() => void arm.run()}
                  disabled={arm.pending || !reference}
                >
                  {arm.pending ? 'Arming…' : 'Arm the failure'}
                </button>
                <button
                  type="button"
                  className="btn"
                  data-variant="primary"
                  onClick={() => void execute.run()}
                  disabled={execute.pending || armed !== reference}
                >
                  {execute.pending ? 'Executing…' : 'Execute now'}
                </button>
              </div>
              {armed && (
                <Notice tone="ok" title="Armed">
                  {definition.code} is armed on{' '}
                  <Link to={`/payments/${armed}`} className="mono">
                    {armed}
                  </Link>
                  . Execute the payment to see it fail, then open the payment to read the
                  investigation.
                </Notice>
              )}
            </>
          )}
        </div>

        <Link className="btn" to="/payments/new">
          Or create a new payment with injections armed
        </Link>
      </div>
    </Drawer>
  )
}
