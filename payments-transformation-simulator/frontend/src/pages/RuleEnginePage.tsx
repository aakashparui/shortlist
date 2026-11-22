/** Business rule explorer, with enable/disable for simulation. */

import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { api } from '../api/client'
import type { BusinessRule } from '../api/types'
import { useAction, useAsync, useDebounced } from '../hooks/useAsync'
import { schemeLabel } from '../lib/format'
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
  SimulationNote,
  StatusChip,
} from '../components/ui'

export function RuleEnginePage() {
  const [params, setParams] = useSearchParams()
  const [category, setCategory] = useState('')
  const [stage, setStage] = useState('')
  const [scheme, setScheme] = useState('')
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(params.get('ruleId'))

  const debounced = useDebounced(search, 240)
  const schemes = useAsync((signal) => api.schemes(signal), [])
  const rules = useAsync(
    (signal) =>
      api.rules(
        {
          category: category || undefined,
          stage: stage || undefined,
          scheme: scheme || undefined,
          query: debounced || undefined,
        },
        signal,
      ),
    [category, stage, scheme, debounced],
  )
  const detail = useAsync((signal) => api.rule(selectedId ?? '', signal), [selectedId], {
    enabled: Boolean(selectedId),
  })

  const toggle = useAction(
    (rule: BusinessRule) =>
      api.toggleRule(rule.ruleId, {
        enabled: !rule.enabled,
        reason: rule.enabled ? 'Disabled for simulation' : 'Re-enabled',
      }),
    {
      onSuccess: () => {
        rules.reload()
        detail.reload()
      },
    },
  )

  useEffect(() => {
    const next = new URLSearchParams(params)
    if (selectedId) next.set('ruleId', selectedId)
    else next.delete('ruleId')
    setParams(next, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])

  return (
    <div className="page">
      <PageHeader
        eyebrow="System"
        title="Rule engine"
        lede="The rule book the validation engine executes. Rule logic lives in the backend; this view shows the metadata and lets a rule be disabled so its effect can be demonstrated."
      />

      <div className="stack">
        {rules.data && rules.data.disabledCount > 0 && (
          <Notice tone="warn" title={`${rules.data.disabledCount} rule(s) are currently disabled`}>
            A disabled rule is recorded as SKIPPED on every payment rather than silently dropped, so
            it is always visible which checks did and did not run.
          </Notice>
        )}

        <div className="filters">
          <div className="field wide">
            <span className="field-label">Search</span>
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="rule id, name or description"
            />
          </div>
          <Field label="Category">
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              <option value="">Any</option>
              {(rules.data?.categories ?? []).map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Stage">
            <select value={stage} onChange={(event) => setStage(event.target.value)}>
              <option value="">Any</option>
              {(rules.data?.stages ?? []).map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Scheme">
            <select value={scheme} onChange={(event) => setScheme(event.target.value)}>
              <option value="">Any</option>
              {(schemes.data?.items ?? []).map((item) => (
                <option key={item.code} value={item.code}>
                  {item.shortName}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <Panel title={`${rules.data?.total ?? 0} rules`} flush>
          {rules.loading && !rules.data ? (
            <Loading rows={10} />
          ) : rules.error ? (
            <div style={{ padding: 'var(--s-5)' }}>
              <ErrorState error={rules.error} onRetry={rules.reload} />
            </div>
          ) : (
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
                { key: 'category', header: 'Category', render: (row) => <span className="tag">{row.category}</span> },
                { key: 'stage', header: 'Stage', render: (row) => <span className="tag">{row.stage}</span> },
                { key: 'severity', header: 'Severity', render: (row) => <StatusChip value={row.severity} mode="raw" /> },
                {
                  key: 'field',
                  header: 'Field',
                  render: (row) => <span className="mono">{row.field ?? '—'}</span>,
                },
                {
                  key: 'reason',
                  header: 'Reason code',
                  render: (row) => (row.isoReasonCode ? <span className="mono">{row.isoReasonCode}</span> : '—'),
                },
                {
                  key: 'schemes',
                  header: 'Applies to',
                  render: (row) => (
                    <div className="row-wrap">
                      {row.schemes.map((code) => (
                        <span className="tag" key={code}>
                          {schemeLabel(code)}
                        </span>
                      ))}
                    </div>
                  ),
                },
                {
                  key: 'enabled',
                  header: 'State',
                  render: (row) => (
                    <StatusChip
                      value={row.enabled ? 'ENABLED' : 'DISABLED'}
                      mode="raw"
                      tone={row.enabled ? 'ok' : 'neutral'}
                    />
                  ),
                },
                {
                  key: 'toggle',
                  header: '',
                  render: (row) => (
                    <button
                      type="button"
                      className="btn"
                      data-size="sm"
                      data-variant={row.enabled ? undefined : 'primary'}
                      disabled={toggle.pending}
                      onClick={(event) => {
                        event.stopPropagation()
                        void toggle.run(row)
                      }}
                    >
                      {row.enabled ? 'Disable' : 'Enable'}
                    </button>
                  ),
                },
              ]}
              rows={rules.data?.items ?? []}
              rowKey={(row) => row.ruleId}
              selectedKey={selectedId}
              onRowClick={(row) => setSelectedId(row.ruleId)}
            />
          )}
        </Panel>
      </div>

      {selectedId && detail.data && (
        <Drawer
          title={detail.data.ruleId}
          subtitle={detail.data.name}
          onClose={() => setSelectedId(null)}
        >
          <div className="col">
            {toggle.error && <ErrorState error={toggle.error} />}
            <KeyValue
              items={[
                { label: 'Rule', value: detail.data.description },
                { label: 'Category', value: detail.data.category, mono: true },
                { label: 'Stage', value: detail.data.stage, mono: true },
                { label: 'Severity', value: <StatusChip value={detail.data.severity} mode="raw" /> },
                { label: 'Field', value: detail.data.field ?? '—', mono: true },
                { label: 'Applies to', value: detail.data.appliesTo.join(', ') || '—', mono: true },
                { label: 'On failure', value: detail.data.failureBehaviour },
                { label: 'ISO reason code', value: detail.data.isoReasonCode ?? '—', mono: true },
                ...(detail.data.rationale ? [{ label: 'Why it exists', value: detail.data.rationale }] : []),
                {
                  label: 'Schemes',
                  value: detail.data.schemes.map(schemeLabel).join(', '),
                },
                ...(Object.keys(detail.data.parameters).length > 0
                  ? [
                      {
                        label: 'Parameters',
                        value: JSON.stringify(detail.data.parameters),
                        mono: true,
                      },
                    ]
                  : []),
                {
                  label: 'State',
                  value: (
                    <StatusChip
                      value={detail.data.enabled ? 'ENABLED' : 'DISABLED'}
                      mode="raw"
                      tone={detail.data.enabled ? 'ok' : 'neutral'}
                    />
                  ),
                },
              ]}
            />

            {detail.data.standardBasis && <SimulationNote>{detail.data.standardBasis}</SimulationNote>}

            {detail.data.relatedFailureInjections &&
              detail.data.relatedFailureInjections.length > 0 && (
                <div className="col-tight">
                  <span className="label">How to make this rule fail</span>
                  {detail.data.relatedFailureInjections.map((injection) => (
                    <div
                      key={injection.code}
                      style={{
                        border: '1px solid var(--line)',
                        borderRadius: 'var(--radius)',
                        padding: 'var(--s-4)',
                      }}
                    >
                      <div className="row-tight">
                        <span className="mono" style={{ fontSize: 'var(--fs-xs)' }}>
                          {injection.code}
                        </span>
                        <StatusChip value={injection.expectedStatus} mode="raw" />
                      </div>
                      <div className="muted" style={{ fontSize: 'var(--fs-xs)', marginTop: 'var(--s-2)' }}>
                        {injection.mechanism}
                      </div>
                    </div>
                  ))}
                  <Link className="btn" to="/qa/failures">
                    Open the failure injection catalogue
                  </Link>
                </div>
              )}

            <div className="row-tight">
              <button
                type="button"
                className="btn"
                data-variant={detail.data.enabled ? 'danger' : 'primary'}
                disabled={toggle.pending}
                onClick={() => void toggle.run(detail.data!)}
              >
                {detail.data.enabled ? 'Disable this rule' : 'Enable this rule'}
              </button>
              <Link className="btn" to={`/qa/test-cases`}>
                Generate test cases
              </Link>
            </div>
          </div>
        </Drawer>
      )}
    </div>
  )
}
