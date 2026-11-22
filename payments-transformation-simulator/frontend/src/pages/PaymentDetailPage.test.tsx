/** The investigation workbench for one payment. */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api/client'
import { ViewModeProvider } from '../components/ViewModeContext'
import { PaymentDetailPage } from './PaymentDetailPage'
import { completedPayment, timedOutPayment } from '../test/fixtures'

function renderPayment(reference: string) {
  return render(
    <ViewModeProvider>
      <MemoryRouter initialEntries={[`/payments/${reference}`]}>
        <Routes>
          <Route path="/payments/:reference" element={<PaymentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </ViewModeProvider>,
  )
}

beforeEach(() => {
  vi.spyOn(api, 'paymentTracking').mockResolvedValue({
    reference: 'TXN-10001',
    supported: false,
    note: 'SIC Instant does not carry a UETR.',
    events: [],
  })
})

describe('PaymentDetailPage', () => {
  it('renders the payment header with amount and parties', async () => {
    vi.spyOn(api, 'getPayment').mockResolvedValue(completedPayment)
    renderPayment('TXN-10001')
    expect(await screen.findByRole('heading', { name: 'TXN-10001' })).toBeInTheDocument()
    expect(screen.getAllByText(/4,850.00 CHF/).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Lindenhof Maschinenbau AG').length).toBeGreaterThan(0)
  })

  it('exposes every identifier for cross-system tracing', async () => {
    vi.spyOn(api, 'getPayment').mockResolvedValue(completedPayment)
    renderPayment('TXN-10001')
    await screen.findByRole('heading', { name: 'TXN-10001' })
    for (const label of [
      'Payment reference',
      'Correlation id',
      'Instruction id',
      'End-to-end id',
      'Transaction id',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(screen.getByText('CORR-ABCDEF0123456789')).toBeInTheDocument()
  })

  it('shows the permitted next states from the state machine', async () => {
    vi.spyOn(api, 'getPayment').mockResolvedValue(completedPayment)
    renderPayment('TXN-10001')
    await screen.findByRole('heading', { name: 'TXN-10001' })
    expect(screen.getByText('Permitted next')).toBeInTheDocument()
    expect(screen.getByText('RETURNED')).toBeInTheDocument()
  })

  it('surfaces the failure summary and the open investigation', async () => {
    vi.spyOn(api, 'getPayment').mockResolvedValue(timedOutPayment)
    renderPayment('TXN-10002')
    await screen.findByRole('heading', { name: 'TXN-10002' })
    expect(screen.getByText('This payment is in a failure state')).toBeInTheDocument()
    expect(screen.getByText(/no pacs.002 within 25s/)).toBeInTheDocument()
    expect(screen.getByText('1 investigation(s) on this payment')).toBeInTheDocument()
    expect(screen.getByText('INV-7001')).toBeInTheDocument()
  })

  it('offers reprocessing only when the state machine permits it', async () => {
    vi.spyOn(api, 'getPayment').mockResolvedValue(timedOutPayment)
    renderPayment('TXN-10002')
    await screen.findByRole('heading', { name: 'TXN-10002' })
    expect(screen.getByRole('button', { name: 'Reprocess' })).toBeInTheDocument()
  })

  it('does not offer reprocessing for a completed payment', async () => {
    vi.spyOn(api, 'getPayment').mockResolvedValue(completedPayment)
    renderPayment('TXN-10001')
    await screen.findByRole('heading', { name: 'TXN-10001' })
    expect(screen.queryByRole('button', { name: 'Reprocess' })).not.toBeInTheDocument()
  })

  it('warns that reprocessing is not a way to force success', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'getPayment').mockResolvedValue(timedOutPayment)
    renderPayment('TXN-10002')
    await screen.findByRole('heading', { name: 'TXN-10002' })
    await user.click(screen.getByRole('button', { name: 'Reprocess' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/not a way to force a success/)).toBeInTheDocument()
  })

  it('sends the reprocess reason to the API', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'getPayment').mockResolvedValue(timedOutPayment)
    const retry = vi.spyOn(api, 'retryPayment').mockResolvedValue(timedOutPayment)
    renderPayment('TXN-10002')
    await screen.findByRole('heading', { name: 'TXN-10002' })
    await user.click(screen.getByRole('button', { name: 'Reprocess' }))
    await user.type(screen.getByLabelText(/Reason for reprocessing/), 'Clearing confirmed acceptance')
    await user.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() =>
      expect(retry).toHaveBeenCalledWith('TXN-10002', {
        reason: 'Clearing confirmed acceptance',
        processingMode: 'IMMEDIATE',
      }),
    )
  })

  it('switches to the messages tab and shows the payload', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'getPayment').mockResolvedValue(completedPayment)
    renderPayment('TXN-10001')
    await screen.findByRole('heading', { name: 'TXN-10001' })
    await user.click(screen.getByRole('tab', { name: /^Messages/ }))
    expect(screen.getByText(/Lindenhof instructs 4850.00 CHF/)).toBeInTheDocument()
  })

  it('shows validation results with expected and actual values', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'getPayment').mockResolvedValue(completedPayment)
    renderPayment('TXN-10001')
    await screen.findByRole('heading', { name: 'TXN-10001' })
    await user.click(screen.getByRole('tab', { name: /^Validations/ }))
    expect(screen.getByText('SIC-AMOUNT-001')).toBeInTheDocument()
    expect(screen.getByText(/actual: 4850.00 CHF · expected: 0.01 - 20000.00 CHF/)).toBeInTheDocument()
  })

  it('explains an empty clearing tab rather than showing nothing', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'getPayment').mockResolvedValue(completedPayment)
    renderPayment('TXN-10001')
    await screen.findByRole('heading', { name: 'TXN-10001' })
    await user.click(screen.getByRole('tab', { name: /Clearing & settlement/ }))
    expect(screen.getByText('Never dispatched to clearing')).toBeInTheDocument()
  })

  it('shows a structured error and a way back when the payment is missing', async () => {
    const { ApiError } = await import('../api/client')
    vi.spyOn(api, 'getPayment').mockRejectedValue(
      new ApiError(404, 'HTTP_404', "Payment 'TXN-99999' not found", null, 'req-9'),
    )
    renderPayment('TXN-99999')
    expect(await screen.findByText('HTTP_404')).toBeInTheDocument()
    expect(screen.getByText(/not found/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to payment search' })).toBeInTheDocument()
  })
})
