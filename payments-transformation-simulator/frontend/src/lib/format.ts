/** Presentation helpers: status tones, labels, dates, amounts. */

import type { Severity, StageState, ViewMode } from '../api/types'

export type Tone = 'ok' | 'warn' | 'error' | 'info' | 'investigate' | 'pending' | 'neutral'

const STATUS_TONES: Record<string, Tone> = {
  DRAFT: 'neutral',
  INITIATED: 'info',
  VALIDATING: 'info',
  VALIDATED: 'info',
  COMPLIANCE_CHECK: 'info',
  MESSAGE_GENERATED: 'info',
  SENT_TO_CLEARING: 'info',
  CLEARING_ACCEPTED: 'info',
  SETTLEMENT_PENDING: 'pending',
  SETTLED: 'info',
  ACCOUNTED: 'info',
  RECONCILED: 'info',
  COMPLETED: 'ok',
  REJECTED: 'error',
  BLOCKED: 'error',
  CLEARING_REJECTED: 'error',
  SETTLEMENT_FAILED: 'error',
  ACCOUNTING_BREAK: 'error',
  RECONCILIATION_BREAK: 'error',
  TIMED_OUT: 'warn',
  INVESTIGATION_REQUIRED: 'investigate',
  REPROCESSING: 'warn',
  CANCELLED: 'neutral',
  RETURNED: 'warn',
  REVERSED: 'warn',
  // stage states
  PENDING: 'pending',
  IN_PROGRESS: 'info',
  FAILED: 'error',
  SKIPPED: 'neutral',
  // validation
  PASSED: 'ok',
  NOT_APPLICABLE: 'neutral',
  // clearing / settlement
  NOT_SENT: 'neutral',
  SENT: 'info',
  AWAITING_RESPONSE: 'pending',
  ACCEPTED: 'ok',
  UNAVAILABLE: 'error',
  SUBMITTED: 'info',
  PARTIALLY_SETTLED: 'warn',
  POSTED: 'ok',
  DUPLICATE: 'error',
  // reconciliation
  MATCHED: 'ok',
  UNMATCHED: 'error',
  AMOUNT_MISMATCH: 'error',
  CURRENCY_MISMATCH: 'error',
  MISSING_ENTRY: 'error',
  TIMING_DIFFERENCE: 'warn',
  REFERENCE_MISMATCH: 'warn',
  NOT_RUN: 'neutral',
  // investigations
  OPEN: 'investigate',
  AWAITING_RESPONSE_INV: 'pending',
  RESOLVED: 'ok',
  CLOSED_UNRESOLVED: 'warn',
  // outcomes
  RUNNING: 'pending',
  // severity
  INFO: 'info',
  WARNING: 'warn',
  ERROR: 'error',
  FATAL: 'error',
}

export function toneFor(value: string | null | undefined): Tone {
  if (!value) return 'neutral'
  return STATUS_TONES[value] ?? 'neutral'
}

export function severityTone(severity: Severity | string | null | undefined): Tone {
  switch (severity) {
    case 'FATAL':
    case 'ERROR':
      return 'error'
    case 'WARNING':
      return 'warn'
    case 'INFO':
      return 'info'
    default:
      return 'neutral'
  }
}

/** Human label for an ALL_CAPS enum value. */
export function humanise(value: string | null | undefined): string {
  if (!value) return '—'
  return value
    .split('_')
    .map((part, index) =>
      index === 0
        ? part.charAt(0) + part.slice(1).toLowerCase()
        : part.length <= 3
          ? part.toLowerCase()
          : part.toLowerCase(),
    )
    .join(' ')
}

const BUSINESS_STATUS_LABELS: Record<string, string> = {
  DRAFT: 'Not yet submitted',
  INITIATED: 'Received',
  VALIDATING: 'Being checked',
  VALIDATED: 'Checks passed',
  REJECTED: 'Refused',
  COMPLIANCE_CHECK: 'Being screened',
  BLOCKED: 'Stopped by compliance',
  MESSAGE_GENERATED: 'Ready to send',
  SENT_TO_CLEARING: 'Sent to the payment system',
  CLEARING_ACCEPTED: 'Accepted by the payment system',
  CLEARING_REJECTED: 'Refused by the payment system',
  TIMED_OUT: 'No response yet',
  INVESTIGATION_REQUIRED: 'Being investigated',
  REPROCESSING: 'Being reprocessed',
  SETTLEMENT_PENDING: 'Settling',
  SETTLED: 'Funds settled',
  SETTLEMENT_FAILED: 'Settlement failed',
  ACCOUNTED: 'Accounts updated',
  ACCOUNTING_BREAK: 'Accounting problem',
  RECONCILED: 'Records matched',
  RECONCILIATION_BREAK: 'Records do not match',
  COMPLETED: 'Paid',
  CANCELLED: 'Cancelled',
  RETURNED: 'Returned by the beneficiary bank',
  REVERSED: 'Reversed',
}

export function statusLabel(status: string | null | undefined, mode: ViewMode): string {
  if (!status) return '—'
  if (mode === 'technical') return status
  return BUSINESS_STATUS_LABELS[status] ?? humanise(status)
}

const SCHEME_LABELS: Record<string, string> = {
  SIC_INSTANT: 'SIC Instant',
  SEPA_INSTANT: 'SEPA Instant',
  SWIFT_CROSS_BORDER: 'SWIFT',
  GENERIC_ISO20022: 'Generic ISO',
}

export function schemeLabel(code: string | null | undefined): string {
  if (!code) return '—'
  return SCHEME_LABELS[code] ?? code
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${date.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })}.${String(date.getMilliseconds()).padStart(3, '0')}`
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(`${value}T00:00:00`)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: '2-digit' })
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return '—'
  const then = new Date(value).getTime()
  if (Number.isNaN(then)) return value
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${ms} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`
}

const CURRENCY_DIGITS: Record<string, number> = { JPY: 0 }

export function formatAmount(
  amount: string | number | null | undefined,
  currency?: string | null,
): string {
  if (amount === null || amount === undefined || amount === '') return '—'
  const value = typeof amount === 'number' ? amount : Number(amount)
  if (Number.isNaN(value)) return String(amount)
  const digits = currency ? (CURRENCY_DIGITS[currency] ?? 2) : 2
  const formatted = value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
  return currency ? `${formatted} ${currency}` : formatted
}

export function signedAmount(amount: string | null | undefined, side: 'DEBIT' | 'CREDIT'): string {
  if (!amount) return '—'
  const value = Number(amount)
  if (Number.isNaN(value)) return amount
  const sign = side === 'DEBIT' ? '-' : '+'
  return `${sign}${Math.abs(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

export function stageTone(state: StageState): Tone {
  return toneFor(state)
}

/** Lightweight XML syntax highlighting for the message viewer. */
export function highlightXml(xml: string): { text: string; className: string }[] {
  const tokens: { text: string; className: string }[] = []
  const pattern = /(<\?[\s\S]*?\?>)|(<\/?[A-Za-z][\w.:-]*)|(\s[\w.:-]+="[^"]*")|(\/?>)|([^<]+)/g
  let match: RegExpExecArray | null
  while ((match = pattern.exec(xml)) !== null) {
    if (match[1]) tokens.push({ text: match[1], className: 'xml-decl' })
    else if (match[2]) tokens.push({ text: match[2], className: 'xml-tag' })
    else if (match[3]) tokens.push({ text: match[3], className: 'xml-attr' })
    else if (match[4]) tokens.push({ text: match[4], className: 'xml-tag' })
    else if (match[5]) tokens.push({ text: match[5], className: 'xml-text' })
  }
  return tokens
}

export function pluralise(count: number, singular: string, plural?: string): string {
  return `${count} ${count === 1 ? singular : (plural ?? `${singular}s`)}`
}

export function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1)
}
