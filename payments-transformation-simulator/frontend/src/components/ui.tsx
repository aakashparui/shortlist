/** Shared presentation primitives. Thin wrappers over the CSS design system. */

import type { ReactNode } from 'react'
import { useMemo, useState } from 'react'

import type { ApiError } from '../api/client'
import type { Severity } from '../api/types'
import {
  formatDuration,
  highlightXml,
  severityTone,
  statusLabel,
  toneFor,
  type Tone,
} from '../lib/format'
import { useViewMode } from './ViewModeContext'

/* ---------------------------------------------------------------- panels */

export function Panel({
  title,
  subtitle,
  actions,
  children,
  flush,
  footer,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
  flush?: boolean
  footer?: ReactNode
}) {
  return (
    <section className="panel">
      {(title || actions) && (
        <header className="panel-header">
          <div className="col-tight" style={{ minWidth: 0 }}>
            {title && <div className="panel-title">{title}</div>}
            {subtitle && <div className="panel-subtitle">{subtitle}</div>}
          </div>
          {actions && (
            <>
              <span className="spacer" />
              <div className="row-tight">{actions}</div>
            </>
          )}
        </header>
      )}
      <div className={flush ? 'panel-body-flush' : 'panel-body'}>{children}</div>
      {footer && <footer className="panel-footer">{footer}</footer>}
    </section>
  )
}

export function PageHeader({
  eyebrow,
  title,
  lede,
  actions,
}: {
  eyebrow?: string
  title: string
  lede?: ReactNode
  actions?: ReactNode
}) {
  return (
    <header className="page-header">
      <div className="page-title-block">
        {eyebrow && <div className="page-eyebrow">{eyebrow}</div>}
        <h1 className="page-title">{title}</h1>
        {lede && <p className="page-lede">{lede}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  )
}

/* ------------------------------------------------------------- indicators */

export function StatusChip({
  value,
  tone,
  mode,
  plain,
}: {
  value: string | null | undefined
  tone?: Tone
  mode?: 'raw' | 'label'
  plain?: boolean
}) {
  const view = useViewMode()
  if (!value) return <span className="dim">—</span>
  const text = mode === 'raw' || view.mode === 'technical' ? value : statusLabel(value, view.mode)
  return (
    <span className={plain ? 'status plain' : 'status'} data-tone={tone ?? toneFor(value)} title={value}>
      {text}
    </span>
  )
}

export function SeverityChip({ value }: { value: Severity | string }) {
  return (
    <span className="status" data-tone={severityTone(value)}>
      {value}
    </span>
  )
}

export function Tag({ children, tone }: { children: ReactNode; tone?: 'accent' }) {
  return (
    <span className="tag" data-tone={tone}>
      {children}
    </span>
  )
}

export function Metric({
  label,
  value,
  note,
  tone,
}: {
  label: string
  value: ReactNode
  note?: ReactNode
  tone?: 'ok' | 'warn' | 'error' | 'investigate'
}) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value" data-tone={tone}>
        {value}
      </div>
      {note && <div className="metric-note">{note}</div>}
    </div>
  )
}

export function Notice({
  tone = 'info',
  title,
  children,
}: {
  tone?: 'info' | 'warn' | 'error' | 'ok'
  title?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="notice" data-tone={tone} role={tone === 'error' ? 'alert' : undefined}>
      <div style={{ minWidth: 0 }}>
        {title && <div className="notice-title">{title}</div>}
        <div className="muted">{children}</div>
      </div>
    </div>
  )
}

export function SimulationNote({ children }: { children: ReactNode }) {
  return (
    <div className="simulation-note">
      <strong>SIMULATION</strong>
      <span>{children}</span>
    </div>
  )
}

/* ------------------------------------------------------------------ states */

export function Loading({ rows = 4, label = 'Loading' }: { rows?: number; label?: string }) {
  return (
    <div className="col" role="status" aria-live="polite" style={{ padding: 'var(--s-5)' }}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="skeleton"
          style={{ width: `${100 - index * 11}%`, maxWidth: 520 }}
        />
      ))}
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  return (
    <div className="notice" data-tone="error" role="alert">
      <div style={{ minWidth: 0 }}>
        <div className="notice-title">{error.code}</div>
        <div className="muted">{error.message}</div>
        {error.fieldErrors.length > 0 && (
          <ul className="muted" style={{ marginTop: 'var(--s-3)', fontSize: 'var(--fs-xs)' }}>
            {error.fieldErrors.map((item, index) => (
              <li key={index}>
                <span className="mono">{item.field || 'request'}</span>: {item.message}
              </li>
            ))}
          </ul>
        )}
        {error.requestId && (
          <div className="dim mono" style={{ marginTop: 'var(--s-3)', fontSize: 'var(--fs-micro)' }}>
            request {error.requestId}
          </div>
        )}
        {onRetry && (
          <button type="button" className="btn" data-size="sm" onClick={onRetry} style={{ marginTop: 'var(--s-4)' }}>
            Try again
          </button>
        )}
      </div>
    </div>
  )
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-title">{title}</div>
      {children}
    </div>
  )
}

/* ------------------------------------------------------------------- data */

export interface Column<T> {
  key: string
  header: ReactNode
  render: (row: T) => ReactNode
  numeric?: boolean
  width?: string
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  selectedKey,
  emptyTitle = 'Nothing to show',
  emptyBody,
}: {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  onRowClick?: (row: T) => void
  selectedKey?: string | null
  emptyTitle?: string
  emptyBody?: ReactNode
}) {
  if (rows.length === 0) {
    return <Empty title={emptyTitle}>{emptyBody}</Empty>
  }
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                className={column.numeric ? 'num' : undefined}
                style={column.width ? { width: column.width } : undefined}
                scope="col"
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = rowKey(row)
            return (
              <tr
                key={key}
                className={onRowClick ? 'clickable' : undefined}
                data-selected={selectedKey === key ? 'true' : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                onKeyDown={
                  onRowClick
                    ? (event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault()
                          onRowClick(row)
                        }
                      }
                    : undefined
                }
              >
                {columns.map((column) => (
                  <td key={column.key} className={column.numeric ? 'num' : undefined}>
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function KeyValue({
  items,
}: {
  items: { label: ReactNode; value: ReactNode; mono?: boolean }[]
}) {
  const visible = items.filter((item) => item.value !== null && item.value !== undefined)
  return (
    <dl className="kv">
      {visible.map((item, index) => (
        <div key={index} style={{ display: 'contents' }}>
          <dt>{item.label}</dt>
          <dd className={item.mono ? 'mono' : undefined}>{item.value}</dd>
        </div>
      ))}
    </dl>
  )
}

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: string; label: string; count?: number }[]
  active: string
  onChange: (id: string) => void
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          className="tab"
          aria-selected={active === tab.id}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
          {tab.count !== undefined && <span className="tab-count">{tab.count}</span>}
        </button>
      ))}
    </div>
  )
}

export function Pager({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number
  pageSize: number
  total: number
  onPage: (page: number) => void
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1
  const to = Math.min(page * pageSize, total)
  return (
    <div className="pager">
      <span>
        {from}–{to} of {total}
      </span>
      <span className="spacer" />
      <button
        type="button"
        className="btn"
        data-size="sm"
        onClick={() => onPage(page - 1)}
        disabled={page <= 1}
      >
        Previous
      </button>
      <span className="mono">
        {page} / {pages}
      </span>
      <button
        type="button"
        className="btn"
        data-size="sm"
        onClick={() => onPage(page + 1)}
        disabled={page >= pages}
      >
        Next
      </button>
    </div>
  )
}

/* -------------------------------------------------------------- code view */

export function CodeBlock({
  content,
  language = 'xml',
  filename,
}: {
  content: string
  language?: 'xml' | 'text' | 'json'
  filename?: string
}) {
  const [copied, setCopied] = useState(false)
  const tokens = useMemo(
    () => (language === 'xml' ? highlightXml(content) : null),
    [content, language],
  )

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      setCopied(false)
    }
  }

  const download = () => {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename ?? `message.${language === 'xml' ? 'xml' : 'txt'}`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="col-tight">
      <div className="row-tight">
        <button type="button" className="btn" data-size="sm" onClick={copy}>
          {copied ? 'Copied' : 'Copy'}
        </button>
        <button type="button" className="btn" data-size="sm" onClick={download}>
          Download
        </button>
        <span className="spacer" />
        <span className="dim mono" style={{ fontSize: 'var(--fs-micro)' }}>
          {content.split('\n').length} lines
        </span>
      </div>
      <pre className="code-block" tabIndex={0}>
        {tokens
          ? tokens.map((token, index) => (
              <span key={index} className={token.className}>
                {token.text}
              </span>
            ))
          : content}
      </pre>
    </div>
  )
}

export function JsonBlock({ value }: { value: unknown }) {
  const text = useMemo(() => JSON.stringify(value, null, 2), [value])
  return <CodeBlock content={text} language="json" filename="detail.json" />
}

/* ------------------------------------------------------------------ misc */

export function Duration({ ms }: { ms: number | null | undefined }) {
  return <span className="num dim">{formatDuration(ms)}</span>
}

export function Drawer({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: ReactNode
  subtitle?: ReactNode
  onClose: () => void
  children: ReactNode
}) {
  return (
    <div
      className="overlay"
      style={{ padding: 0, alignItems: 'stretch', justifyContent: 'flex-end' }}
      onClick={onClose}
      role="presentation"
    >
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : 'Detail'}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="drawer-header">
          <div className="col-tight" style={{ minWidth: 0 }}>
            <div className="panel-title">{title}</div>
            {subtitle && <div className="panel-subtitle">{subtitle}</div>}
          </div>
          <span className="spacer" />
          <button
            type="button"
            className="btn"
            data-variant="quiet"
            data-size="sm"
            onClick={onClose}
            aria-label="Close"
          >
            Close
          </button>
        </header>
        <div className="drawer-body">{children}</div>
      </aside>
    </div>
  )
}

export function Field({
  label,
  hint,
  error,
  required,
  children,
}: {
  label: string
  hint?: ReactNode
  error?: string | null
  required?: boolean
  children: ReactNode
}) {
  return (
    <label className="field">
      <span className="field-label">
        {label}
        {required && <span className="req" aria-hidden="true">*</span>}
      </span>
      {children}
      {error ? <span className="field-error">{error}</span> : hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  )
}

export function Bar({ value, max, tone }: { value: number; max: number; tone?: Tone }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0
  return (
    <div className="bar" role="img" aria-label={`${value} of ${max}`}>
      <div className="bar-fill" data-tone={tone} style={{ width: `${pct}%` }} />
    </div>
  )
}
