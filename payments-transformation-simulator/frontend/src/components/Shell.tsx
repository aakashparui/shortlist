/** Application shell: brand, command bar, navigation rail, status bar. */

import type { ReactNode } from 'react'
import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

import { api } from '../api/client'
import { useAsync, usePolling } from '../hooks/useAsync'
import { CommandPalette, useCommandPalette } from './CommandPalette'
import { useViewMode } from './ViewModeContext'

interface NavEntry {
  to: string
  label: string
  icon: string
  end?: boolean
  countKey?: 'investigations' | 'breaks' | 'failures'
}

interface NavGroup {
  label: string
  items: NavEntry[]
}

const NAVIGATION: NavGroup[] = [
  {
    label: 'Payments',
    items: [
      { to: '/', label: 'Control room', icon: '▣', end: true },
      { to: '/payments/new', label: 'Payment simulator', icon: '✎' },
      { to: '/payments', label: 'Payment search', icon: '⌕' },
    ],
  },
  {
    label: 'Operations',
    items: [
      { to: '/investigations', label: 'Investigations', icon: '◎', countKey: 'investigations' },
      { to: '/exceptions', label: 'Exceptions', icon: '⚠', countKey: 'failures' },
      { to: '/reconciliation', label: 'Reconciliation', icon: '⇄', countKey: 'breaks' },
    ],
  },
  {
    label: 'Messages',
    items: [
      { to: '/messages', label: 'ISO 20022 explorer', icon: '⟨⟩' },
      { to: '/messages/trace', label: 'Message trace', icon: '≡' },
      { to: '/messages/mt-mx', label: 'MT → MX mapping', icon: '⇝' },
    ],
  },
  {
    label: 'Schemes',
    items: [{ to: '/schemes', label: 'Scheme rulebooks', icon: '⊞' }],
  },
  {
    label: 'QA Lab',
    items: [
      { to: '/qa/scenarios', label: 'Scenarios', icon: '▶' },
      { to: '/qa/failures', label: 'Failure injection', icon: '✕' },
      { to: '/qa/test-cases', label: 'Test cases', icon: '☑' },
    ],
  },
  {
    label: 'BA Workbench',
    items: [{ to: '/ba', label: 'Requirements & traceability', icon: '§' }],
  },
  {
    label: 'System',
    items: [
      { to: '/system/events', label: 'Event log', icon: '⧗' },
      { to: '/system/rules', label: 'Rule engine', icon: '⚖' },
      { to: '/system/accounts', label: 'Accounts & nostro', icon: '∑' },
      { to: '/system/configuration', label: 'Configuration', icon: '⚙' },
    ],
  },
]

export function Shell() {
  const [collapsed, setCollapsed] = useState(false)
  const { open, setOpen } = useCommandPalette()
  const view = useViewMode()

  const stats = useAsync((signal) => api.statistics(signal), [])
  const config = useAsync((signal) => api.config(signal), [])
  usePolling(() => stats.reload(), 15000, true)

  const counts = {
    investigations: stats.data?.openInvestigations ?? 0,
    breaks: stats.data?.reconciliationBreaks ?? 0,
    failures: stats.data?.failureCount ?? 0,
  }

  return (
    <div className="shell" data-nav={collapsed ? 'collapsed' : 'expanded'}>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>

      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          PT
        </span>
        <span className="brand-text">
          <span className="brand-name">Payments Transformation</span>
          <span className="brand-sub">Simulator</span>
        </span>
      </div>

      <header className="topbar">
        <button
          type="button"
          className="btn"
          data-variant="quiet"
          data-size="icon"
          onClick={() => setCollapsed(!collapsed)}
          aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
          aria-expanded={!collapsed}
        >
          ☰
        </button>

        <button type="button" className="command-trigger" onClick={() => setOpen(true)}>
          <span aria-hidden="true">⌕</span>
          <span className="truncate">Search payments, references, rules, scenarios…</span>
          <span className="spacer" />
          <kbd>Ctrl</kbd>
          <kbd>K</kbd>
        </button>

        <span className="spacer" />

        <div className="btn-group" role="group" aria-label="Terminology mode">
          <button
            type="button"
            className="btn"
            data-size="sm"
            aria-pressed={view.mode === 'business'}
            onClick={() => view.setMode('business')}
            title="Business terminology"
          >
            Business
          </button>
          <button
            type="button"
            className="btn"
            data-size="sm"
            aria-pressed={view.mode === 'technical'}
            onClick={() => view.setMode('technical')}
            title="Technical terminology, payloads and system states"
          >
            Technical
          </button>
        </div>

        <button
          type="button"
          className="btn"
          data-variant="quiet"
          data-size="icon"
          onClick={view.toggleTheme}
          aria-label={view.theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
        >
          {view.theme === 'dark' ? '☀' : '☾'}
        </button>
      </header>

      <nav className="nav" aria-label="Main navigation">
        {NAVIGATION.map((group) => (
          <div className="nav-group" key={group.label}>
            <div className="nav-group-label">{group.label}</div>
            {group.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => (isActive ? 'nav-item active' : 'nav-item')}
                title={item.label}
              >
                <span className="nav-icon" aria-hidden="true">
                  {item.icon}
                </span>
                <span className="nav-label">{item.label}</span>
                {item.countKey && counts[item.countKey] > 0 && (
                  <span
                    className="nav-count"
                    data-tone={item.countKey === 'investigations' ? 'warn' : 'error'}
                  >
                    {counts[item.countKey]}
                  </span>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <main className="main" id="main-content" tabIndex={-1}>
        <Outlet />
      </main>

      <footer className="statusbar">
        <StatusItem label="env" value={config.data?.environment ?? '…'} />
        <StatusItem label="db" value={config.data?.database ?? '…'} />
        <StatusItem
          label="payments"
          value={stats.data ? String(stats.data.totalPayments) : '…'}
        />
        <StatusItem
          label="failures"
          value={stats.data ? String(stats.data.failureCount) : '…'}
          tone={counts.failures > 0 ? 'error' : undefined}
        />
        <StatusItem
          label="investigations"
          value={stats.data ? String(stats.data.openInvestigations) : '…'}
          tone={counts.investigations > 0 ? 'warn' : undefined}
        />
        <StatusItem
          label="recon breaks"
          value={stats.data ? String(stats.data.reconciliationBreaks) : '…'}
          tone={counts.breaks > 0 ? 'error' : undefined}
        />
        {config.data?.demoMode && (
          <StatusItem label="mode" value={`demo ×${config.data.simulationSpeedFactor}`} />
        )}
        <span className="spacer" />
        <span className="statusbar-item">
          SIMULATED ENVIRONMENT · FICTIONAL DATA · v{config.data?.appVersion ?? '—'}
        </span>
      </footer>

      <CommandPalette open={open} onClose={() => setOpen(false)} />
    </div>
  )
}

function StatusItem({
  label,
  value,
  tone,
}: {
  label: string
  value: ReactNode
  tone?: 'error' | 'warn'
}) {
  return (
    <span className="statusbar-item">
      <span style={{ opacity: 0.65 }}>{label}</span>
      <span
        style={{
          color:
            tone === 'error' ? 'var(--error)' : tone === 'warn' ? 'var(--warn)' : 'var(--text-secondary)',
        }}
      >
        {value}
      </span>
    </span>
  )
}
