import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { PaymentJourney } from './PaymentJourney'
import { completedPayment, timedOutPayment } from '../test/fixtures'

describe('PaymentJourney', () => {
  it('renders one node per stage', () => {
    render(<PaymentJourney payment={completedPayment} />)
    expect(screen.getByText(/4 of 4 stages completed/)).toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(completedPayment.stages.length)
  })

  it('shows each stage state', () => {
    render(<PaymentJourney payment={timedOutPayment} />)
    expect(screen.getByText('TIMED_OUT')).toBeInTheDocument()
    expect(screen.getByText('SKIPPED')).toBeInTheDocument()
  })

  it('opens the failed stage automatically and explains the failure', () => {
    render(<PaymentJourney payment={timedOutPayment} />)
    expect(screen.getByText('CLEARING TIMEOUT')).toBeInTheDocument()
    expect(screen.getByText('What happened')).toBeInTheDocument()
    expect(screen.getByText('Why')).toBeInTheDocument()
    expect(screen.getByText('Expected')).toBeInTheDocument()
    expect(screen.getByText('Actual')).toBeInTheDocument()
    expect(screen.getByText('Payment state')).toBeInTheDocument()
    expect(screen.getByText('Next possible action')).toBeInTheDocument()
  })

  it('reports the expected and actual values from the stage detail', () => {
    render(<PaymentJourney payment={timedOutPayment} />)
    expect(screen.getByText('pacs.002 within 25s')).toBeInTheDocument()
    expect(screen.getByText('no response after 25.4s')).toBeInTheDocument()
  })

  it('surfaces the investigation recommendation, not a generic message', () => {
    render(<PaymentJourney payment={timedOutPayment} />)
    expect(screen.getByText(/Do not re-send the pacs.008/)).toBeInTheDocument()
  })

  it('collapses and expands a stage on click', async () => {
    const user = userEvent.setup()
    render(<PaymentJourney payment={completedPayment} />)
    const button = screen.getByRole('button', { name: /INITIATION business label/ })
    expect(button).toHaveAttribute('aria-expanded', 'false')
    await user.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    await user.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'false')
  })

  it('lets a stage hand off to the message viewer', async () => {
    const user = userEvent.setup()
    const onOpenMessage = vi.fn()
    const payment = {
      ...completedPayment,
      stages: completedPayment.stages.map((stage) =>
        stage.stageKey === 'INITIATION'
          ? { ...stage, detail: { messageId: 'PACS008-20260101-ABCDE12345' } }
          : stage,
      ),
    }
    render(<PaymentJourney payment={payment} onOpenMessage={onOpenMessage} />)
    await user.click(screen.getByRole('button', { name: /INITIATION business label/ }))
    await user.click(screen.getByRole('button', { name: 'Inspect' }))
    expect(onOpenMessage).toHaveBeenCalledWith('PACS008-20260101-ABCDE12345')
  })
})
