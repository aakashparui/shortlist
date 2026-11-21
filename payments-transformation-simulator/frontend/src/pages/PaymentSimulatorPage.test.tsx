/** Payment creation: the form, the scheme rulebook and the injection picker. */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api/client'
import { ViewModeProvider } from '../components/ViewModeContext'
import { PaymentSimulatorPage } from './PaymentSimulatorPage'
import { completedPayment, failureDefinitions, scheme } from '../test/fixtures'

const sepaScheme = {
  ...scheme,
  code: 'SEPA_INSTANT',
  name: 'SEPA Instant Credit Transfer (simulated)',
  shortName: 'SEPA Instant',
  settlementCurrency: 'EUR',
  allowedCurrencies: ['EUR'],
  amountLimits: [{ currency: 'EUR', minimum: '0.01', maximum: '100000.00' }],
  allowedServiceLevels: ['SEPA'],
}

function renderPage() {
  return render(
    <ViewModeProvider>
      <MemoryRouter>
        <PaymentSimulatorPage />
      </MemoryRouter>
    </ViewModeProvider>,
  )
}

beforeEach(() => {
  vi.spyOn(api, 'schemes').mockResolvedValue({ items: [scheme, sepaScheme], default: 'SIC_INSTANT' })
  vi.spyOn(api, 'failureCatalogue').mockResolvedValue({
    items: failureDefinitions,
    byCategory: { TIMEOUT: failureDefinitions },
    note: 'An injection changes the input or a downstream system behaviour.',
  })
})

describe('PaymentSimulatorPage', () => {
  it('shows the scheme rulebook alongside the form', async () => {
    renderPage()
    expect(await screen.findByText('SIC Instant rulebook')).toBeInTheDocument()
    expect(screen.getByText('SIC Instant Clearing (simulated)')).toBeInTheDocument()
    expect(screen.getByText(/25s realistic/)).toBeInTheDocument()
  })

  it('states the scheme amount range as a hint', async () => {
    renderPage()
    expect(await screen.findByText(/Scheme range 0.01 CHF – 20,000.00 CHF/)).toBeInTheDocument()
  })

  it('warns when the amount is above the scheme ceiling', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('SIC Instant rulebook')
    const amount = screen.getByLabelText(/^Amount/)
    await user.clear(amount)
    await user.type(amount, '25000.00')
    expect(await screen.findByText(/Above the 20000.00 CHF scheme ceiling/)).toBeInTheDocument()
    expect(amount).toHaveAttribute('aria-invalid', 'true')
  })

  it('switching scheme switches the currency and the preset data', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('SIC Instant rulebook')
    await user.selectOptions(screen.getByLabelText('Payment scheme'), 'SEPA_INSTANT')
    await waitFor(() => expect(screen.getByLabelText(/^Currency/)).toHaveValue('EUR'))
    expect(await screen.findByText('SEPA Instant rulebook')).toBeInTheDocument()
  })

  it('keeps ISO codes behind progressive disclosure', async () => {
    renderPage()
    await screen.findByText('SIC Instant rulebook')

    // The primary fields are always visible.
    expect(screen.getByLabelText(/^Amount/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Remittance information/)).toBeInTheDocument()

    // ISO codes and identifiers live inside a collapsed section.
    const advanced = screen.getByText('Advanced payment data').closest('details')
    expect(advanced).not.toBeNull()
    expect(advanced).not.toHaveAttribute('open')
    expect(within(advanced as HTMLElement).getByLabelText(/Purpose code/)).toBeInTheDocument()
    expect(
      within(advanced as HTMLElement).getByLabelText(/End-to-end identification/),
    ).toBeInTheDocument()
    expect(within(advanced as HTMLElement).getByLabelText(/Charge bearer/)).toBeInTheDocument()
  })

  it('lists the failure injections with their expected outcome', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('SIC Instant rulebook')
    await user.click(screen.getByText(/Break it on purpose/))
    expect(screen.getByText(/The clearing system never answers/)).toBeInTheDocument()
    expect(screen.getByText(/Expected outcome: INVESTIGATION_REQUIRED/)).toBeInTheDocument()
  })

  it('submits the instruction and executes it', async () => {
    const user = userEvent.setup()
    const create = vi.spyOn(api, 'createPayment').mockResolvedValue(completedPayment)
    const execute = vi.spyOn(api, 'executePayment').mockResolvedValue(completedPayment)
    renderPage()
    await screen.findByText('SIC Instant rulebook')

    await user.click(screen.getByRole('button', { name: /Create and execute payment/ }))

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
    const body = create.mock.calls[0][0]
    expect(body.scheme).toBe('SIC_INSTANT')
    expect(body.currency).toBe('CHF')
    expect(body.debtor.iban).toBe('CH0700910000123456780')
    expect(body.creditor.name).toBe('Zentrum Bauservice AG')
    expect(execute).toHaveBeenCalledWith('TXN-10001', expect.objectContaining({ processingMode: 'SIMULATED' }))
  })

  it('passes the selected injections through to the API', async () => {
    const user = userEvent.setup()
    const create = vi.spyOn(api, 'createPayment').mockResolvedValue(completedPayment)
    vi.spyOn(api, 'executePayment').mockResolvedValue(completedPayment)
    renderPage()
    await screen.findByText('SIC Instant rulebook')

    await user.click(screen.getByText(/Break it on purpose/))
    const section = screen.getByText(/The clearing system never answers/).closest('label')
    await user.click(within(section as HTMLElement).getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: /Create and execute payment/ }))

    await waitFor(() => expect(create).toHaveBeenCalled())
    expect(create.mock.calls[0][0].failureInjections).toEqual([
      { code: 'CLEARING_TIMEOUT', parameters: {} },
    ])
  })

  it('reports an API rejection without losing the entered data', async () => {
    const user = userEvent.setup()
    const { ApiError } = await import('../api/client')
    vi.spyOn(api, 'createPayment').mockRejectedValue(
      new ApiError(400, 'UNKNOWN_SCHEME', "Payment scheme 'NOPE' is not registered.", null, 'req-1'),
    )
    renderPage()
    await screen.findByText('SIC Instant rulebook')
    await user.click(screen.getByRole('button', { name: /Create and execute payment/ }))
    expect(await screen.findByText('UNKNOWN_SCHEME')).toBeInTheDocument()
    expect(screen.getByLabelText(/^Amount/)).toHaveValue('4850.00')
  })
})
