/**
 * Message inspection tool.
 *
 * Five views of the same message, which is how a BA and a developer can look at
 * the same artefact: the business meaning, the payload, where each field came
 * from, whether those fields validated, and when it moved.
 */

import { useState } from 'react'

import type { PaymentMessage } from '../api/types'
import { formatDateTime, toneFor } from '../lib/format'
import { CodeBlock, Empty, KeyValue, Notice, SimulationNote, StatusChip, Tabs } from './ui'

type View = 'business' | 'payload' | 'mapping' | 'validation' | 'timeline'

export function MessageViewer({
  messages,
  activeMessageId,
  onSelect,
}: {
  messages: PaymentMessage[]
  activeMessageId?: string | null
  onSelect?: (messageId: string) => void
}) {
  const [internalId, setInternalId] = useState<string | null>(null)
  const selectedId = activeMessageId ?? internalId ?? messages[0]?.messageId ?? null
  const message = messages.find((m) => m.messageId === selectedId) ?? messages[0] ?? null
  const [view, setView] = useState<View>('business')

  const select = (id: string) => {
    setInternalId(id)
    onSelect?.(id)
  }

  if (messages.length === 0) {
    return (
      <Empty title="No messages yet">
        A message is only created when the lifecycle reaches the stage that produces it. A payment
        rejected in validation never generates a pacs.008.
      </Empty>
    )
  }

  return (
    <div className="col">
      <div className="row-wrap" style={{ padding: 'var(--s-4) var(--s-5) 0' }}>
        <span className="label">Messages</span>
        <div className="btn-group" role="group" aria-label="Select a message">
          {messages.map((item) => (
            <button
              key={item.messageId}
              type="button"
              className="btn"
              data-size="sm"
              aria-pressed={item.messageId === selectedId}
              onClick={() => select(item.messageId)}
              title={`${item.messageName} · ${item.messageId}`}
            >
              {item.messageType}
              {item.isMalformed && <span className="text-error"> !</span>}
            </button>
          ))}
        </div>
      </div>

      {message && (
        <>
          <div style={{ padding: '0 var(--s-5)' }}>
            <div className="row-wrap">
              <span className="mono" style={{ fontSize: 'var(--fs-sm)' }}>
                {message.messageId}
              </span>
              <StatusChip value={message.state} mode="raw" tone={toneFor(message.state)} />
              <span className="tag">{message.direction}</span>
              {message.isoIdentifier && <span className="tag">{message.isoIdentifier}</span>}
              {message.reasonCode && (
                <span className="tag" data-tone="accent">
                  {message.reasonCode}
                </span>
              )}
            </div>
          </div>

          <Tabs
            tabs={[
              { id: 'business', label: 'Business view' },
              { id: 'payload', label: message.payloadFormat === 'FIN' ? 'FIN view' : 'XML view' },
              { id: 'mapping', label: 'Field mapping', count: message.fieldMappings.length || undefined },
              {
                id: 'validation',
                label: 'Field validation',
                count: message.validationSummary.length || undefined,
              },
              { id: 'timeline', label: 'Timeline' },
            ]}
            active={view}
            onChange={(id) => setView(id as View)}
          />

          <div style={{ padding: 'var(--s-5)' }}>
            {view === 'business' && <BusinessView message={message} />}
            {view === 'payload' && (
              <div className="col">
                {message.isMalformed && (
                  <Notice tone="error" title="This message is malformed on purpose">
                    {message.notes}
                  </Notice>
                )}
                <CodeBlock
                  content={message.payload ?? '(payload not loaded)'}
                  language={message.payloadFormat === 'FIN' ? 'text' : 'xml'}
                  filename={`${message.messageId}.${message.payloadFormat === 'FIN' ? 'txt' : 'xml'}`}
                />
              </div>
            )}
            {view === 'mapping' && <MappingView message={message} />}
            {view === 'validation' && <ValidationView message={message} />}
            {view === 'timeline' && <TimelineView message={message} />}
          </div>
        </>
      )}
    </div>
  )
}

function BusinessView({ message }: { message: PaymentMessage }) {
  const summary = message.businessSummary ?? {}
  return (
    <div className="col">
      <div>
        <div className="label" style={{ marginBottom: 'var(--s-3)' }}>
          {summary.messageName ?? message.messageName} · {summary.isoIdentifier ?? message.isoIdentifier}
        </div>
        {summary.purpose && <p className="muted">{summary.purpose}</p>}
      </div>
      {summary.plainEnglish && (
        <Notice tone="info" title="What this message says">
          {summary.plainEnglish}
        </Notice>
      )}
      {summary.statusMeaning && (
        <KeyValue items={[{ label: 'Status code meaning', value: summary.statusMeaning }]} />
      )}
      {summary.keyFacts && summary.keyFacts.length > 0 && (
        <KeyValue
          items={summary.keyFacts.map((fact) => ({
            label: fact.label,
            value: fact.value,
            mono: true,
          }))}
        />
      )}
      {message.notes && <Notice tone="warn">{message.notes}</Notice>}
      {summary.simulationNote && <SimulationNote>{summary.simulationNote}</SimulationNote>}
    </div>
  )
}

function MappingView({ message }: { message: PaymentMessage }) {
  if (message.fieldMappings.length === 0) {
    return (
      <Empty title="No field mapping recorded">
        Field mapping is captured for outbound instruction messages, where the simulator maps the
        payment record onto the ISO 20022 structure.
      </Empty>
    )
  }
  return (
    <div className="col">
      <SimulationNote>
        Mapping types are explicit: a value that is copied is DIRECT, a value that is re-shaped is
        TRANSFORMED, a value the simulator derives is DERIVED, and a field with no counterpart is
        marked as having no equivalent.
      </SimulationNote>
      <div className="table-wrap" style={{ border: '1px solid var(--line)', borderRadius: 'var(--radius)' }}>
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Payment field</th>
              <th scope="col" aria-label="maps to" />
              <th scope="col">ISO 20022 element</th>
              <th scope="col">Value</th>
              <th scope="col">Mapping</th>
            </tr>
          </thead>
          <tbody>
            {message.fieldMappings.map((row, index) => (
              <tr key={index}>
                <td>
                  <div>{row.sourceLabel}</div>
                  <div className="cell-secondary mono">{row.sourceField}</div>
                </td>
                <td className="mapping-arrow" aria-hidden="true">
                  →
                </td>
                <td className="mono" style={{ fontSize: 'var(--fs-xs)' }}>
                  {row.isoPath}
                </td>
                <td className="mono" style={{ fontSize: 'var(--fs-xs)' }}>
                  {row.present ? row.value : <span className="dim">not present</span>}
                </td>
                <td>
                  <span className="mapping-type" data-kind={row.mappingType}>
                    {row.mappingType}
                  </span>
                  {row.note && <div className="cell-secondary">{row.note}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ValidationView({ message }: { message: PaymentMessage }) {
  if (message.validationSummary.length === 0) {
    return <Empty title="No field validation recorded for this message" />
  }
  const failures = message.validationSummary.filter((check) => check.status === 'FAILED')
  return (
    <div className="col">
      <div className="row-tight">
        <StatusChip value={failures.length === 0 ? 'PASSED' : 'FAILED'} mode="raw" />
        <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
          {message.validationSummary.length} checks, {failures.length} failed
        </span>
      </div>
      <div className="table-wrap" style={{ border: '1px solid var(--line)', borderRadius: 'var(--radius)' }}>
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Check</th>
              <th scope="col">Field</th>
              <th scope="col">Outcome</th>
              <th scope="col">Detail</th>
            </tr>
          </thead>
          <tbody>
            {message.validationSummary.map((check, index) => (
              <tr key={`${check.ruleId}-${index}`}>
                <td>
                  <div className="cell-primary" style={{ fontSize: 'var(--fs-xs)' }}>
                    {check.ruleId}
                  </div>
                  <div className="cell-secondary">{check.ruleName}</div>
                </td>
                <td className="mono" style={{ fontSize: 'var(--fs-xs)' }}>
                  {check.field ?? '—'}
                </td>
                <td>
                  <StatusChip value={check.status} mode="raw" />
                </td>
                <td style={{ fontSize: 'var(--fs-xs)' }}>{check.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function TimelineView({ message }: { message: PaymentMessage }) {
  return (
    <KeyValue
      items={[
        { label: 'Generated', value: formatDateTime(message.createdAt), mono: true },
        { label: 'Sent', value: formatDateTime(message.sentAt), mono: true },
        { label: 'Received', value: formatDateTime(message.receivedAt), mono: true },
        { label: 'Direction', value: message.direction, mono: true },
        { label: 'State', value: <StatusChip value={message.state} mode="raw" /> },
        { label: 'Correlation id', value: message.correlationId, mono: true },
        { label: 'Related message', value: message.relatedMessageId ?? '—', mono: true },
        { label: 'Reason code', value: message.reasonCode ?? '—', mono: true },
      ]}
    />
  )
}
