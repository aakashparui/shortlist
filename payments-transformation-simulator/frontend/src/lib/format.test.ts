import { describe, expect, it } from 'vitest'

import {
  formatAmount,
  formatDuration,
  highlightXml,
  schemeLabel,
  severityTone,
  statusLabel,
  toneFor,
} from './format'

describe('toneFor', () => {
  it('maps terminal success to ok', () => {
    expect(toneFor('COMPLETED')).toBe('ok')
    expect(toneFor('MATCHED')).toBe('ok')
    expect(toneFor('PASSED')).toBe('ok')
  })

  it('maps failures to error', () => {
    for (const status of [
      'REJECTED',
      'BLOCKED',
      'CLEARING_REJECTED',
      'ACCOUNTING_BREAK',
      'RECONCILIATION_BREAK',
      'AMOUNT_MISMATCH',
      'MISSING_ENTRY',
    ]) {
      expect(toneFor(status)).toBe('error')
    }
  })

  it('separates timeouts and investigations from plain failures', () => {
    expect(toneFor('TIMED_OUT')).toBe('warn')
    expect(toneFor('INVESTIGATION_REQUIRED')).toBe('investigate')
  })

  it('falls back to neutral for unknown values', () => {
    expect(toneFor('SOMETHING_NEW')).toBe('neutral')
    expect(toneFor(null)).toBe('neutral')
  })
})

describe('severityTone', () => {
  it('treats FATAL as error', () => {
    expect(severityTone('FATAL')).toBe('error')
    expect(severityTone('ERROR')).toBe('error')
    expect(severityTone('WARNING')).toBe('warn')
    expect(severityTone('INFO')).toBe('info')
  })
})

describe('statusLabel', () => {
  it('returns the raw status in technical mode', () => {
    expect(statusLabel('INVESTIGATION_REQUIRED', 'technical')).toBe('INVESTIGATION_REQUIRED')
  })

  it('returns business language in business mode', () => {
    expect(statusLabel('INVESTIGATION_REQUIRED', 'business')).toBe('Being investigated')
    expect(statusLabel('COMPLETED', 'business')).toBe('Paid')
    expect(statusLabel('CLEARING_REJECTED', 'business')).toBe('Refused by the payment system')
  })

  it('humanises an unmapped status rather than showing an enum', () => {
    expect(statusLabel('SOME_NEW_STATE', 'business')).toBe('Some new state')
  })
})

describe('formatAmount', () => {
  it('formats with two decimals and the currency', () => {
    expect(formatAmount('4850.5', 'CHF')).toBe('4,850.50 CHF')
  })

  it('uses zero decimals for JPY', () => {
    expect(formatAmount('250000', 'JPY')).toBe('250,000 JPY')
  })

  it('handles empty values', () => {
    expect(formatAmount(null, 'CHF')).toBe('—')
    expect(formatAmount('', 'CHF')).toBe('—')
  })
})

describe('formatDuration', () => {
  it('uses milliseconds below a second', () => {
    expect(formatDuration(240)).toBe('240 ms')
  })

  it('uses seconds above a second', () => {
    expect(formatDuration(2450)).toBe('2.45 s')
  })

  it('uses minutes above a minute', () => {
    expect(formatDuration(65_000)).toBe('1m 5s')
  })

  it('handles absent durations', () => {
    expect(formatDuration(null)).toBe('—')
  })
})

describe('schemeLabel', () => {
  it('shortens the scheme codes', () => {
    expect(schemeLabel('SIC_INSTANT')).toBe('SIC Instant')
    expect(schemeLabel('SWIFT_CROSS_BORDER')).toBe('SWIFT')
  })
})

describe('highlightXml', () => {
  it('tokenises declaration, tags, attributes and text', () => {
    const tokens = highlightXml('<?xml version="1.0"?>\n<Doc attr="x">value</Doc>')
    const classes = tokens.map((token) => token.className)
    expect(classes).toContain('xml-decl')
    expect(classes).toContain('xml-tag')
    expect(classes).toContain('xml-attr')
    expect(classes).toContain('xml-text')
  })

  it('round-trips the original content', () => {
    const xml = '<?xml version="1.0"?>\n<A><B ccy="CHF">10.00</B></A>\n'
    expect(highlightXml(xml).map((token) => token.text).join('')).toBe(xml)
  })
})
