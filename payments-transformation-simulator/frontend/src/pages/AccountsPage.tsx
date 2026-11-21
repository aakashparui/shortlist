/** Accounts, nostro/vostro positions and the camt.053 statement generator. */

import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { api } from '../api/client'
import { useAsync } from '../hooks/useAsync'
import { formatAmount, formatDate, formatDateTime } from '../lib/format'
import {
  CodeBlock,
  DataTable,
  Drawer,
  Empty,
  ErrorState,
  KeyValue,
  Loading,
  Notice,
  PageHeader,
  Panel,
  StatusChip,
  Tabs,
} from '../components/ui'

const ORDER = ['CUSTOMER', 'NOSTRO', 'VOSTRO', 'SETTLEMENT', 'SUSPENSE']

export function AccountsPage() {
  const [params] = useSearchParams()
  const [selected, setSelected] = useState<string | null>(params.get('account'))
  const [tab, setTab] = useState<'accounts' | 'explainer' | 'banks'>('accounts')

  const accounts = useAsync((signal) => api.accounts({}, signal), [])
  const banks = useAsync((signal) => api.banks(signal), [tab])

  return (
    <div className="page">
      <PageHeader
        eyebrow="System"
        title="Accounts, nostro and vostro"
        lede="The books the simulator posts to. Customer accounts, our nostro positions with correspondents, their vostro accounts on our books, settlement accounts and suspense."
      />

      <div className="stack">
        <Panel flush>
          <Tabs
            tabs={[
              { id: 'accounts', label: 'Accounts', count: accounts.data?.items.length },
              { id: 'explainer', label: 'Nostro / vostro explained' },
              { id: 'banks', label: 'Bank directory', count: banks.data?.items.length },
            ]}
            active={tab}
            onChange={(id) => setTab(id as typeof tab)}
          />

          {tab === 'accounts' && (
            <>
              {accounts.loading && !accounts.data ? (
                <Loading rows={8} />
              ) : accounts.error ? (
                <div style={{ padding: 'var(--s-5)' }}>
                  <ErrorState error={accounts.error} onRetry={accounts.reload} />
                </div>
              ) : (
                ORDER.filter((type) => accounts.data?.byType[type]?.length).map((type) => (
                  <div key={type}>
                    <div
                      className="panel-header"
                      style={{ borderRadius: 0, borderTop: '1px solid var(--line)' }}
                    >
                      <span className="panel-title">{type}</span>
                      <span className="panel-subtitle">
                        {accounts.data?.byType[type]?.length} accounts
                      </span>
                    </div>
                    <DataTable
                      columns={[
                        {
                          key: 'account',
                          header: 'Account',
                          render: (row) => (
                            <>
                              <div className="cell-primary">{row.accountNumber}</div>
                              {row.iban && <div className="cell-secondary mono">{row.iban}</div>}
                            </>
                          ),
                        },
                        { key: 'name', header: 'Name', render: (row) => row.name },
                        { key: 'currency', header: 'Ccy', render: (row) => <span className="mono">{row.currency}</span> },
                        {
                          key: 'balance',
                          header: 'Balance',
                          numeric: true,
                          render: (row) => row.balanceFormatted,
                        },
                        {
                          key: 'movement',
                          header: 'Movement',
                          numeric: true,
                          render: (row) => {
                            const delta = Number(row.balance) - Number(row.openingBalance)
                            if (Math.abs(delta) < 0.005) return <span className="dim">—</span>
                            return (
                              <span className={delta < 0 ? 'text-debit' : 'text-credit'}>
                                {delta > 0 ? '+' : ''}
                                {formatAmount(delta, row.currency)}
                              </span>
                            )
                          },
                        },
                        {
                          key: 'overdraft',
                          header: 'Overdraft',
                          numeric: true,
                          render: (row) =>
                            Number(row.overdraftLimit) > 0
                              ? formatAmount(row.overdraftLimit, row.currency)
                              : '—',
                        },
                        {
                          key: 'correspondent',
                          header: 'Correspondent',
                          render: (row) =>
                            row.correspondentBank ? (
                              <>
                                <div style={{ fontSize: 'var(--fs-xs)' }}>{row.correspondentBank.name}</div>
                                <div className="cell-secondary mono">{row.correspondentBank.bic}</div>
                              </>
                            ) : (
                              '—'
                            ),
                        },
                        {
                          key: 'active',
                          header: 'State',
                          render: (row) => (
                            <StatusChip
                              value={row.isActive ? 'ACTIVE' : 'BLOCKED'}
                              mode="raw"
                              tone={row.isActive ? 'ok' : 'error'}
                            />
                          ),
                        },
                      ]}
                      rows={accounts.data?.byType[type] ?? []}
                      rowKey={(row) => row.accountNumber}
                      onRowClick={(row) => setSelected(row.accountNumber)}
                    />
                  </div>
                ))
              )}
            </>
          )}

          {tab === 'explainer' && (
            <div className="col" style={{ padding: 'var(--s-5)' }}>
              {Object.entries(accounts.data?.explainer ?? {}).map(([type, text]) => (
                <div key={type} className="row" style={{ alignItems: 'flex-start' }}>
                  <span className="tag" data-tone="accent" style={{ flex: '0 0 110px' }}>
                    {type}
                  </span>
                  <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
                    {text}
                  </span>
                </div>
              ))}
              <hr />
              <div className="flow">
                {['Our bank', 'Nostro account', 'Correspondent bank', 'Clearing / settlement'].map(
                  (node, index, array) => (
                    <div className="row-tight" key={node}>
                      <div className="flow-node">
                        <div className="flow-node-title">Step {index + 1}</div>
                        <div>{node}</div>
                      </div>
                      {index < array.length - 1 && (
                        <span className="flow-arrow" aria-hidden="true">
                          →
                        </span>
                      )}
                    </div>
                  ),
                )}
              </div>
              <Notice tone="info" title="What the simulator does with these accounts">
                An outgoing cross-border payment debits the customer and credits the nostro position,
                reducing what we hold with the correspondent. A domestic instant payment settles over
                the central-bank settlement account instead. Both postings appear on the payment's
                accounting tab.
              </Notice>
            </div>
          )}

          {tab === 'banks' && (
            <>
              {banks.loading && !banks.data ? (
                <Loading rows={6} />
              ) : (
                <DataTable
                  columns={[
                    { key: 'bic', header: 'BIC', render: (row) => <span className="mono">{row.bic}</span> },
                    {
                      key: 'name',
                      header: 'Institution',
                      render: (row) => (
                        <>
                          <div>{row.name}</div>
                          {row.isInternal && <div className="cell-secondary">our institution</div>}
                        </>
                      ),
                    },
                    {
                      key: 'location',
                      header: 'Location',
                      render: (row) => `${row.city}, ${row.country}`,
                    },
                    {
                      key: 'clearing',
                      header: 'National code',
                      render: (row) => <span className="mono">{row.nationalClearingCode ?? '—'}</span>,
                    },
                    {
                      key: 'schemes',
                      header: 'Reachable on',
                      render: (row) =>
                        row.supportedSchemes.length === 0 ? (
                          <span className="dim">not reachable</span>
                        ) : (
                          <div className="row-wrap">
                            {row.supportedSchemes.map((scheme) => (
                              <span className="tag" key={scheme}>
                                {scheme}
                              </span>
                            ))}
                          </div>
                        ),
                    },
                    { key: 'notes', header: 'Notes', render: (row) => row.notes },
                  ]}
                  rows={banks.data?.items ?? []}
                  rowKey={(row) => row.bic}
                />
              )}
              {banks.data && (
                <div style={{ padding: 'var(--s-5)' }}>
                  <Notice tone="warn" title="Fictional directory">
                    {banks.data.note}
                  </Notice>
                </div>
              )}
            </>
          )}
        </Panel>
      </div>

      {selected && <AccountDrawer accountNumber={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

function AccountDrawer({ accountNumber, onClose }: { accountNumber: string; onClose: () => void }) {
  const [view, setView] = useState<'movements' | 'statement'>('movements')
  const account = useAsync((signal) => api.account(accountNumber, signal), [accountNumber])
  const statement = useAsync((signal) => api.statement(accountNumber, signal), [accountNumber, view], {
    enabled: view === 'statement',
  })

  return (
    <Drawer title={accountNumber} subtitle={account.data?.name} onClose={onClose}>
      {account.loading && !account.data ? (
        <Loading rows={6} />
      ) : account.error ? (
        <ErrorState error={account.error} onRetry={account.reload} />
      ) : account.data ? (
        <div className="col">
          <KeyValue
            items={[
              { label: 'Type', value: account.data.accountType, mono: true },
              { label: 'Currency', value: account.data.currency, mono: true },
              { label: 'IBAN', value: account.data.iban ?? '—', mono: true },
              { label: 'Opening balance', value: formatAmount(account.data.movement.openingBalance, account.data.currency), mono: true },
              { label: 'Current balance', value: account.data.balanceFormatted, mono: true },
              { label: 'Net movement', value: formatAmount(account.data.movement.netMovement, account.data.currency), mono: true },
              { label: 'Description', value: account.data.description },
              ...(account.data.correspondentBank
                ? [
                    {
                      label: 'Correspondent',
                      value: `${account.data.correspondentBank.name} (${account.data.correspondentBank.bic})`,
                    },
                  ]
                : []),
            ]}
          />

          <Tabs
            tabs={[
              { id: 'movements', label: 'Ledger movements', count: account.data.accountingEntries.length },
              { id: 'statement', label: 'camt.053 statement' },
            ]}
            active={view}
            onChange={(id) => setView(id as typeof view)}
          />

          {view === 'movements' && (
            <>
              <DataTable
                columns={[
                  { key: 'entry', header: 'Entry', render: (row) => <span className="mono">{row.entryId}</span> },
                  {
                    key: 'side',
                    header: 'Side',
                    render: (row) => (
                      <span className="ledger-side" data-side={row.side}>
                        {row.side}
                      </span>
                    ),
                  },
                  {
                    key: 'amount',
                    header: 'Amount',
                    numeric: true,
                    render: (row) => formatAmount(row.amount, row.currency),
                  },
                  {
                    key: 'balance',
                    header: 'Balance after',
                    numeric: true,
                    render: (row) => (row.balanceAfter ? formatAmount(row.balanceAfter, row.currency) : '—'),
                  },
                  { key: 'posted', header: 'Posted', render: (row) => formatDateTime(row.postedAt) },
                  { key: 'status', header: 'Status', render: (row) => <StatusChip value={row.status} mode="raw" /> },
                  { key: 'narrative', header: 'Narrative', render: (row) => row.narrative },
                ]}
                rows={account.data.accountingEntries}
                rowKey={(row) => row.entryId}
                emptyTitle="No ledger movements on this account yet"
              />
              {account.data.statementEntries.length > 0 && (
                <>
                  <span className="label">Statement entries</span>
                  <DataTable
                    columns={[
                      {
                        key: 'reference',
                        header: 'Entry',
                        render: (row) => <span className="mono">{row.statementReference}</span>,
                      },
                      {
                        key: 'amount',
                        header: 'Amount',
                        numeric: true,
                        render: (row) => formatAmount(row.amount, row.currency),
                      },
                      { key: 'booked', header: 'Booked', render: (row) => formatDate(row.bookingDate) },
                      {
                        key: 'match',
                        header: 'Match',
                        render: (row) =>
                          row.isOrphan ? (
                            <StatusChip value="UNMATCHED" mode="raw" tone="error" />
                          ) : (
                            <StatusChip value="MATCHED" mode="raw" tone="ok" />
                          ),
                      },
                    ]}
                    rows={account.data.statementEntries}
                    rowKey={(row) => row.statementReference}
                  />
                </>
              )}
            </>
          )}

          {view === 'statement' && (
            <>
              {statement.loading && !statement.data ? (
                <Loading rows={5} />
              ) : statement.error ? (
                <ErrorState error={statement.error} onRetry={statement.reload} />
              ) : statement.data ? (
                <div className="col">
                  <Notice tone="info" title={statement.data.messageId}>
                    {statement.data.businessSummary.plainEnglish}
                  </Notice>
                  <CodeBlock
                    content={statement.data.payload}
                    language="xml"
                    filename={`${statement.data.messageId}.xml`}
                  />
                </div>
              ) : (
                <Empty title="No statement available" />
              )}
            </>
          )}
        </div>
      ) : null}
    </Drawer>
  )
}
