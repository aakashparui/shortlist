/**
 * Payment entry.
 *
 * Progressive disclosure: the fields an operator needs are visible, ISO 20022
 * codes and identifiers sit behind "Advanced payment data", and the scheme
 * rulebook is shown alongside so limits are never a surprise.
 */

import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import type { FailureDefinition, PaymentCreateInput, Scheme } from '../api/types'
import { useAction, useAsync } from '../hooks/useAsync'
import { formatAmount, schemeLabel } from '../lib/format'
import {
  ErrorState,
  Field,
  KeyValue,
  Loading,
  Notice,
  PageHeader,
  Panel,
  SimulationNote,
} from '../components/ui'

interface PartyForm {
  name: string
  iban: string
  accountIdentifier: string
  bic: string
  bankName: string
  country: string
  town: string
  addressLine: string
}

const EMPTY_PARTY: PartyForm = {
  name: '',
  iban: '',
  accountIdentifier: '',
  bic: '',
  bankName: '',
  country: '',
  town: '',
  addressLine: '',
}

/** Fictional starting data per rail, so an operator can submit immediately. */
const PRESETS: Record<string, { debtor: PartyForm; creditor: PartyForm; amount: string; remittance: string }> = {
  SIC_INSTANT: {
    amount: '4850.00',
    remittance: 'Invoice 2026-0481',
    debtor: {
      ...EMPTY_PARTY,
      name: 'Lindenhof Maschinenbau AG',
      iban: 'CH0700910000123456780',
      bic: 'SIMUCHZZXXX',
      bankName: 'Simulator Bank AG',
      country: 'CH',
      town: 'Zurich',
      addressLine: 'Lindenhofstrasse 42',
    },
    creditor: {
      ...EMPTY_PARTY,
      name: 'Zentrum Bauservice AG',
      iban: 'CH0500920100887766550',
      bic: 'ALPNCHZZXXX',
      bankName: 'Alpine Kantonalbank',
      country: 'CH',
      town: 'Bern',
      addressLine: 'Bundesgasse 14',
    },
  },
  SEPA_INSTANT: {
    amount: '9340.00',
    remittance: 'Order 884512 part delivery',
    debtor: {
      ...EMPTY_PARTY,
      name: 'Lindenhof Maschinenbau AG',
      iban: 'CH2800910000123456790',
      bic: 'SIMUCHZZXXX',
      bankName: 'Simulator Bank AG',
      country: 'CH',
      town: 'Zurich',
    },
    creditor: {
      ...EMPTY_PARTY,
      name: 'Hanse Maschinen GmbH',
      iban: 'DE43500105170032198765',
      bic: 'NORDDEFFXXX',
      bankName: 'Norddeutsche Handelsbank',
      country: 'DE',
      town: 'Hamburg',
      addressLine: 'Speicherstadt 8',
    },
  },
  SWIFT_CROSS_BORDER: {
    amount: '86500.00',
    remittance: 'Consultancy services Q1',
    debtor: {
      ...EMPTY_PARTY,
      name: 'Quintet Pharma Holding',
      iban: 'CH4700910000441122330',
      bic: 'SIMUCHZZXXX',
      bankName: 'Simulator Bank AG',
      country: 'CH',
      town: 'Zug',
    },
    creditor: {
      ...EMPTY_PARTY,
      name: 'Mercer Analytics Inc',
      accountIdentifier: '4410028876',
      bic: 'HUDSUS33XXX',
      bankName: 'Hudson River Bank',
      country: 'US',
      town: 'New York',
      addressLine: '120 Water Street',
    },
  },
  GENERIC_ISO20022: {
    amount: '5600.00',
    remittance: 'Freight settlement week 13',
    debtor: {
      ...EMPTY_PARTY,
      name: 'Rheintal Textil AG',
      iban: 'CH6200910000559988770',
      bic: 'SIMUCHZZXXX',
      bankName: 'Simulator Bank AG',
      country: 'CH',
      town: 'St. Gallen',
    },
    creditor: {
      ...EMPTY_PARTY,
      name: 'Thameside Freight Ltd',
      iban: 'GB38THAM20415538294000',
      bic: 'THAMGB2LXXX',
      bankName: 'Thames Commercial Bank',
      country: 'GB',
      town: 'London',
    },
  },
}

export function PaymentSimulatorPage() {
  const navigate = useNavigate()
  const schemes = useAsync((signal) => api.schemes(signal), [])
  const catalogue = useAsync((signal) => api.failureCatalogue(signal), [])

  const [schemeCode, setSchemeCode] = useState('SIC_INSTANT')
  const [amount, setAmount] = useState(PRESETS.SIC_INSTANT.amount)
  const [currency, setCurrency] = useState('CHF')
  const [executionDate, setExecutionDate] = useState('')
  const [remittance, setRemittance] = useState(PRESETS.SIC_INSTANT.remittance)
  const [debtor, setDebtor] = useState<PartyForm>(PRESETS.SIC_INSTANT.debtor)
  const [creditor, setCreditor] = useState<PartyForm>(PRESETS.SIC_INSTANT.creditor)
  const [purposeCode, setPurposeCode] = useState('GDDS')
  const [serviceLevel, setServiceLevel] = useState('')
  const [chargeBearer, setChargeBearer] = useState('')
  const [endToEndId, setEndToEndId] = useState('')
  const [instructionId, setInstructionId] = useState('')
  const [notes, setNotes] = useState('')
  const [processingMode, setProcessingMode] = useState<'IMMEDIATE' | 'SIMULATED'>('SIMULATED')
  const [executeNow, setExecuteNow] = useState(true)
  const [injections, setInjections] = useState<string[]>([])

  const scheme: Scheme | undefined = useMemo(
    () => schemes.data?.items.find((item) => item.code === schemeCode),
    [schemes.data, schemeCode],
  )

  // Applying a rail resets the data to that rail's fictional preset.
  const applyScheme = (code: string) => {
    setSchemeCode(code)
    const preset = PRESETS[code]
    const target = schemes.data?.items.find((item) => item.code === code)
    if (preset) {
      setDebtor(preset.debtor)
      setCreditor(preset.creditor)
      setAmount(preset.amount)
      setRemittance(preset.remittance)
    }
    if (target) {
      setCurrency(target.settlementCurrency)
      setServiceLevel(target.allowedServiceLevels[0] ?? '')
      setChargeBearer('')
    }
  }

  useEffect(() => {
    if (!scheme) return
    if (!scheme.allowedCurrencies.includes(currency)) {
      setCurrency(scheme.settlementCurrency)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scheme?.code])

  const limit = scheme?.amountLimits.find((item) => item.currency === currency)
  const amountValue = Number(amount)
  const overLimit = limit && !Number.isNaN(amountValue) && amountValue > Number(limit.maximum)

  const create = useAction(
    async () => {
      const body: PaymentCreateInput = {
        scheme: schemeCode,
        amount,
        currency,
        requestedExecutionDate: executionDate || null,
        debtor: toParty(debtor),
        creditor: toParty(creditor),
        remittanceInformation: remittance,
        purposeCode: purposeCode || null,
        serviceLevel: serviceLevel || null,
        chargeBearer: chargeBearer || null,
        endToEndId: endToEndId || null,
        instructionId: instructionId || null,
        notes,
        processingMode,
        failureInjections: injections.map((code) => ({ code, parameters: {} })),
      }
      const payment = await api.createPayment(body)
      if (!executeNow) return payment
      return api.executePayment(payment.reference, {
        processingMode,
        waitForCompletion: processingMode === 'SIMULATED',
        waitTimeoutSeconds: 30,
      })
    },
    { onSuccess: (payment) => navigate(`/payments/${payment.reference}`) },
  )

  const toggleInjection = (code: string) =>
    setInjections((current) =>
      current.includes(code) ? current.filter((item) => item !== code) : [...current, code],
    )

  if (schemes.loading && !schemes.data) {
    return (
      <div className="page">
        <Loading rows={8} label="Loading scheme configuration" />
      </div>
    )
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="Payments"
        title="Payment simulator"
        lede="Create an instruction and watch it travel through validation, screening, messaging, clearing, settlement, accounting and reconciliation."
      />

      <form
        className="grid grid-main-aside"
        onSubmit={(event) => {
          event.preventDefault()
          void create.run()
        }}
      >
        <div className="stack">
          {create.error && <ErrorState error={create.error} />}

          <Panel title="Instruction" subtitle="What the customer asked the bank to do">
            <div className="col">
              <div className="form-grid">
                <Field label="Payment scheme" required hint={scheme?.jurisdiction}>
                  <select
                    value={schemeCode}
                    onChange={(event) => applyScheme(event.target.value)}
                    aria-label="Payment scheme"
                  >
                    {(schemes.data?.items ?? []).map((item) => (
                      <option key={item.code} value={item.code}>
                        {item.shortName} — {item.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field
                  label="Amount"
                  required
                  error={overLimit ? `Above the ${limit?.maximum} ${limit?.currency} scheme ceiling` : null}
                  hint={
                    limit
                      ? `Scheme range ${formatAmount(limit.minimum, limit.currency)} – ${formatAmount(limit.maximum, limit.currency)}`
                      : undefined
                  }
                >
                  <input
                    type="text"
                    inputMode="decimal"
                    data-mono="true"
                    value={amount}
                    onChange={(event) => setAmount(event.target.value)}
                    aria-invalid={overLimit ? 'true' : undefined}
                    required
                  />
                </Field>
                <Field label="Currency" required>
                  <select value={currency} onChange={(event) => setCurrency(event.target.value)}>
                    {(scheme?.allowedCurrencies ?? ['CHF']).map((code) => (
                      <option key={code} value={code}>
                        {code}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field
                  label="Requested execution date"
                  hint={
                    scheme?.allowsFutureDated
                      ? `Future dating allowed up to ${scheme.maxFutureDays} days`
                      : 'This rail executes immediately'
                  }
                >
                  <input
                    type="date"
                    value={executionDate}
                    onChange={(event) => setExecutionDate(event.target.value)}
                  />
                </Field>
              </div>
              <Field
                label="Remittance information"
                hint={`Up to ${scheme?.maxRemittanceLength ?? 140} characters · ${remittance.length} used`}
              >
                <input
                  type="text"
                  value={remittance}
                  onChange={(event) => setRemittance(event.target.value)}
                  maxLength={400}
                />
              </Field>
            </div>
          </Panel>

          <Panel title="Debtor" subtitle="The paying customer, held on our book">
            <PartyFields
              value={debtor}
              onChange={setDebtor}
              requireIban={scheme?.allowedCurrencies !== undefined && schemeCode !== 'SWIFT_CROSS_BORDER'}
            />
          </Panel>

          <Panel title="Creditor" subtitle="The beneficiary and their bank">
            <PartyFields
              value={creditor}
              onChange={setCreditor}
              requireIban={schemeCode === 'SIC_INSTANT' || schemeCode === 'SEPA_INSTANT'}
              requireAddress={schemeCode === 'SWIFT_CROSS_BORDER'}
            />
          </Panel>

          <details className="form-section">
            <summary>Advanced payment data</summary>
            <div className="form-section-body">
              <div className="form-grid">
                <Field label="Purpose code" hint="ISO 20022 ExternalPurpose code">
                  <input
                    type="text"
                    data-mono="true"
                    value={purposeCode}
                    onChange={(event) => setPurposeCode(event.target.value.toUpperCase())}
                    maxLength={10}
                  />
                </Field>
                <Field label="Service level">
                  <select value={serviceLevel} onChange={(event) => setServiceLevel(event.target.value)}>
                    <option value="">Scheme default</option>
                    {(scheme?.allowedServiceLevels ?? []).map((code) => (
                      <option key={code} value={code}>
                        {code}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Charge bearer">
                  <select value={chargeBearer} onChange={(event) => setChargeBearer(event.target.value)}>
                    <option value="">Scheme default</option>
                    <option value="SLEV">SLEV — following service level</option>
                    <option value="DEBT">DEBT — borne by the debtor</option>
                    <option value="CRED">CRED — borne by the creditor</option>
                    <option value="SHAR">SHAR — shared</option>
                  </select>
                </Field>
                <Field label="Clearing channel" hint="Derived from the scheme">
                  <input type="text" value={scheme?.clearing.system ?? ''} readOnly disabled />
                </Field>
                <Field label="End-to-end identification" hint="Left blank, the simulator assigns one">
                  <input
                    type="text"
                    data-mono="true"
                    value={endToEndId}
                    onChange={(event) => setEndToEndId(event.target.value)}
                    maxLength={35}
                    placeholder="auto"
                  />
                </Field>
                <Field label="Instruction identification" hint="Left blank, the simulator assigns one">
                  <input
                    type="text"
                    data-mono="true"
                    value={instructionId}
                    onChange={(event) => setInstructionId(event.target.value)}
                    maxLength={35}
                    placeholder="auto"
                  />
                </Field>
              </div>
              <div style={{ marginTop: 'var(--s-5)' }}>
                <Field label="Operator notes">
                  <textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={2} />
                </Field>
              </div>
            </div>
          </details>

          <details className="form-section">
            <summary>Break it on purpose ({injections.length} selected)</summary>
            <div className="form-section-body">
              <div className="col">
                <p className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
                  An injection changes the instruction or the behaviour of a downstream system. The
                  engines then fail for real, so the failure is reproducible and the investigation
                  shows exactly what changed.
                </p>
                {catalogue.loading && !catalogue.data && <Loading rows={3} />}
                {Object.entries(catalogue.data?.byCategory ?? {}).map(([category, items]) => (
                  <div key={category}>
                    <div className="label" style={{ marginBottom: 'var(--s-3)' }}>
                      {category}
                    </div>
                    <div className="col-tight">
                      {items.map((item: FailureDefinition) => (
                        <label className="checkbox" key={item.code}>
                          <input
                            type="checkbox"
                            checked={injections.includes(item.code)}
                            onChange={() => toggleInjection(item.code)}
                          />
                          <span style={{ minWidth: 0 }}>
                            <span style={{ display: 'block' }}>{item.label}</span>
                            <span className="dim" style={{ display: 'block', fontSize: 'var(--fs-xs)' }}>
                              {item.description} Expected outcome: {item.expectedStatus}.
                            </span>
                          </span>
                        </label>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </details>
        </div>

        <div className="stack">
          <Panel title="Execution">
            <div className="col">
              <Field
                label="Processing mode"
                hint={
                  processingMode === 'SIMULATED'
                    ? 'Clearing responses and timeouts run through the scheduler, with scheme timings divided by the demo speed factor.'
                    : 'Runs the whole lifecycle synchronously with no artificial delay.'
                }
              >
                <select
                  value={processingMode}
                  onChange={(event) => setProcessingMode(event.target.value as 'IMMEDIATE' | 'SIMULATED')}
                >
                  <option value="SIMULATED">Simulated timing (watch it happen)</option>
                  <option value="IMMEDIATE">Immediate (no delays)</option>
                </select>
              </Field>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={executeNow}
                  onChange={(event) => setExecuteNow(event.target.checked)}
                />
                <span>Execute immediately after creating</span>
              </label>
              <button type="submit" className="btn" data-variant="primary" disabled={create.pending}>
                {create.pending
                  ? 'Processing…'
                  : executeNow
                    ? 'Create and execute payment'
                    : 'Create payment'}
              </button>
              {injections.length > 0 && (
                <Notice tone="warn" title={`${injections.length} failure injection(s) armed`}>
                  {injections.join(', ')}
                </Notice>
              )}
            </div>
          </Panel>

          {scheme && (
            <Panel title={`${schemeLabel(scheme.code)} rulebook`} subtitle={scheme.operator}>
              <div className="col">
                <p className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
                  {scheme.description}
                </p>
                <KeyValue
                  items={[
                    { label: 'Settlement currency', value: scheme.settlementCurrency, mono: true },
                    { label: 'Clearing system', value: scheme.clearing.system },
                    {
                      label: 'Response threshold',
                      value: `${scheme.clearing.timeoutSeconds}s realistic · ${scheme.acceleratedTimeoutSeconds ?? '—'}s in demo mode`,
                      mono: true,
                    },
                    { label: 'Settlement finality', value: scheme.clearing.settlementFinality },
                    { label: 'Operating hours', value: scheme.clearing.operatingHours },
                    { label: 'Settlement account', value: scheme.settlement.accountType, mono: true },
                    {
                      label: 'Value date',
                      value: `T+${scheme.settlement.valueDateOffsetDays}`,
                      mono: true,
                    },
                    {
                      label: 'Country scope',
                      value: scheme.countryScope ? `${scheme.countryScope.length} countries` : 'Global',
                    },
                    { label: 'Carries UETR', value: scheme.usesUetr ? 'Yes' : 'No' },
                    { label: 'Messages', value: scheme.messages.join(', '), mono: true },
                    { label: 'Rules applied', value: String(scheme.validationRuleIds.length), mono: true },
                  ]}
                />
                <SimulationNote>{scheme.simulationNotes}</SimulationNote>
              </div>
            </Panel>
          )}
        </div>
      </form>
    </div>
  )
}

function PartyFields({
  value,
  onChange,
  requireIban,
  requireAddress,
}: {
  value: PartyForm
  onChange: (value: PartyForm) => void
  requireIban?: boolean
  requireAddress?: boolean
}) {
  const set = (patch: Partial<PartyForm>) => onChange({ ...value, ...patch })
  return (
    <div className="form-grid">
      <Field label="Name" required>
        <input
          type="text"
          value={value.name}
          onChange={(event) => set({ name: event.target.value })}
          maxLength={140}
          required
        />
      </Field>
      <Field
        label="IBAN"
        required={requireIban}
        hint={requireIban ? 'Checked against ISO 13616 mod-97' : 'Optional on this rail'}
      >
        <input
          type="text"
          data-mono="true"
          value={value.iban}
          onChange={(event) => set({ iban: event.target.value.toUpperCase().replace(/\s/g, '') })}
          maxLength={42}
        />
      </Field>
      {!requireIban && (
        <Field label="Other account identifier" hint="Used when no IBAN exists">
          <input
            type="text"
            data-mono="true"
            value={value.accountIdentifier}
            onChange={(event) => set({ accountIdentifier: event.target.value })}
            maxLength={40}
          />
        </Field>
      )}
      <Field label="BIC" hint="ISO 9362, 8 or 11 characters">
        <input
          type="text"
          data-mono="true"
          value={value.bic}
          onChange={(event) => set({ bic: event.target.value.toUpperCase().replace(/\s/g, '') })}
          maxLength={11}
        />
      </Field>
      <Field label="Bank name">
        <input
          type="text"
          value={value.bankName}
          onChange={(event) => set({ bankName: event.target.value })}
          maxLength={140}
        />
      </Field>
      <Field label="Country" required={requireAddress} hint="ISO 3166 alpha-2">
        <input
          type="text"
          data-mono="true"
          value={value.country}
          onChange={(event) => set({ country: event.target.value.toUpperCase().slice(0, 2) })}
          maxLength={2}
        />
      </Field>
      <Field
        label="Town"
        required={requireAddress}
        hint={requireAddress ? 'Required for cross-border transparency' : undefined}
      >
        <input
          type="text"
          value={value.town}
          onChange={(event) => set({ town: event.target.value })}
          maxLength={80}
        />
      </Field>
      <Field label="Address line">
        <input
          type="text"
          value={value.addressLine}
          onChange={(event) => set({ addressLine: event.target.value })}
          maxLength={70}
        />
      </Field>
    </div>
  )
}

function toParty(form: PartyForm) {
  return {
    name: form.name,
    iban: form.iban || null,
    accountIdentifier: form.accountIdentifier,
    bic: form.bic || null,
    bankName: form.bankName,
    country: form.country,
    town: form.town,
    addressLines: form.addressLine ? [form.addressLine] : [],
  }
}
