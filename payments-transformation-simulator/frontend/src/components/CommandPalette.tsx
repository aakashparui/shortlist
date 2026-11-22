/**
 * Global command centre (Ctrl/Cmd + K).
 *
 * Accepts references, identifiers, message types and plain-language intents
 * ("find failed payments"). Resolution happens on the backend so the same
 * search works from the API.
 */

import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import type { SearchHit } from '../api/types'
import { useAsync, useDebounced } from '../hooks/useAsync'

const EXAMPLES = [
  'TXN-10001',
  'payment E2E…',
  'UETR …',
  'find failed payments',
  'show unmatched reconciliations',
  'open pacs.008',
  'SIC-AMOUNT-001',
  'nostro',
]

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const debounced = useDebounced(query, 180)
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)

  const { data, loading } = useAsync(
    (signal) => api.search(debounced, 14, signal),
    [debounced],
    { enabled: open && debounced.trim().length > 0 },
  )

  const hits: SearchHit[] = data?.items ?? []

  useEffect(() => {
    if (open) {
      setQuery('')
      setCursor(0)
      window.setTimeout(() => inputRef.current?.focus(), 10)
    }
  }, [open])

  useEffect(() => setCursor(0), [debounced])

  if (!open) return null

  const go = (hit: SearchHit) => {
    navigate(hit.route)
    onClose()
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setCursor((c) => Math.min(c + 1, Math.max(0, hits.length - 1)))
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      setCursor((c) => Math.max(0, c - 1))
      return
    }
    if (event.key === 'Enter' && hits[cursor]) {
      event.preventDefault()
      go(hits[cursor])
    }
  }

  return (
    <div className="overlay" onClick={onClose} role="presentation">
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command centre"
        onClick={(event) => event.stopPropagation()}
      >
        <input
          ref={inputRef}
          className="palette-input"
          type="search"
          placeholder="Search a payment, reference, UETR, rule, scenario or view…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={onKeyDown}
          aria-label="Search"
          autoComplete="off"
          spellCheck={false}
        />
        <div className="palette-results" role="listbox" aria-label="Results">
          {query.trim().length === 0 && (
            <div style={{ padding: 'var(--s-5) var(--s-6)' }}>
              <div className="label" style={{ marginBottom: 'var(--s-4)' }}>
                Try
              </div>
              <div className="row-wrap">
                {EXAMPLES.map((example) => (
                  <button
                    key={example}
                    type="button"
                    className="tag"
                    style={{ cursor: 'pointer' }}
                    onClick={() => setQuery(example.replace('…', ''))}
                  >
                    {example}
                  </button>
                ))}
              </div>
            </div>
          )}
          {query.trim().length > 0 && loading && (
            <div style={{ padding: 'var(--s-5) var(--s-6)' }} className="dim">
              Searching…
            </div>
          )}
          {query.trim().length > 0 && !loading && hits.length === 0 && (
            <div style={{ padding: 'var(--s-5) var(--s-6)' }} className="dim">
              Nothing matched “{query}”.
            </div>
          )}
          {hits.map((hit, index) => (
            <button
              key={`${hit.kind}-${hit.route}-${index}`}
              type="button"
              className="palette-item"
              data-active={index === cursor ? 'true' : undefined}
              role="option"
              aria-selected={index === cursor}
              onClick={() => go(hit)}
              onMouseEnter={() => setCursor(index)}
            >
              <span className="tag" style={{ flex: '0 0 auto' }}>
                {hit.badge ?? hit.kind}
              </span>
              <span style={{ minWidth: 0 }}>
                <span className="palette-item-title truncate" style={{ display: 'block' }}>
                  {hit.title}
                </span>
                <span className="palette-item-sub truncate" style={{ display: 'block' }}>
                  {hit.subtitle}
                </span>
              </span>
            </button>
          ))}
        </div>
        <div className="palette-hint">
          <kbd>↑</kbd> <kbd>↓</kbd> to move · <kbd>Enter</kbd> to open · <kbd>Esc</kbd> to close
        </div>
      </div>
    </div>
  )
}

/** Register the Ctrl/Cmd + K shortcut. */
export function useCommandPalette(): { open: boolean; setOpen: (open: boolean) => void } {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setOpen((value) => !value)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])
  return { open, setOpen }
}
