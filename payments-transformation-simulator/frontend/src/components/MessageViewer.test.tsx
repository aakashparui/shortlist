import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { MessageViewer } from './MessageViewer'
import { pacs002Rejected, pacs008 } from '../test/fixtures'

describe('MessageViewer', () => {
  it('explains why there are no messages instead of showing an empty box', () => {
    render(<MessageViewer messages={[]} />)
    expect(screen.getByText('No messages yet')).toBeInTheDocument()
    expect(screen.getByText(/never generates a pacs.008/)).toBeInTheDocument()
  })

  it('opens on the business view', () => {
    render(<MessageViewer messages={[pacs008]} />)
    expect(screen.getByText('What this message says')).toBeInTheDocument()
    expect(screen.getByText(/Lindenhof instructs 4850.00 CHF/)).toBeInTheDocument()
  })

  it('offers all five views', () => {
    render(<MessageViewer messages={[pacs008]} />)
    for (const label of ['Business view', 'XML view', 'Field mapping', 'Field validation', 'Timeline']) {
      expect(screen.getByRole('tab', { name: new RegExp(label) })).toBeInTheDocument()
    }
  })

  it('shows the XML payload in the payload view', async () => {
    const user = userEvent.setup()
    render(<MessageViewer messages={[pacs008]} />)
    await user.click(screen.getByRole('tab', { name: /XML view/ }))
    const payload = document.querySelector('pre.code-block')
    expect(payload).not.toBeNull()
    expect(payload?.textContent).toContain('pacs.008.001.08')
    expect(payload?.textContent).toContain('PACS008-20260101-ABCDE12345')
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Download' })).toBeInTheDocument()
  })

  it('distinguishes direct from transformed mappings', async () => {
    const user = userEvent.setup()
    render(<MessageViewer messages={[pacs008]} />)
    await user.click(screen.getByRole('tab', { name: /Field mapping/ }))
    expect(screen.getByText('DIRECT')).toBeInTheDocument()
    expect(screen.getByText('TRANSFORMED')).toBeInTheDocument()
    expect(screen.getByText('CdtTrfTxInf/PmtId/EndToEndId')).toBeInTheDocument()
  })

  it('reports field validation outcomes', async () => {
    const user = userEvent.setup()
    render(<MessageViewer messages={[pacs008]} />)
    await user.click(screen.getByRole('tab', { name: /Field validation/ }))
    expect(screen.getByText(/1 checks, 0 failed/)).toBeInTheDocument()
  })

  it('switches between messages and shows the rejection reason', async () => {
    const user = userEvent.setup()
    render(<MessageViewer messages={[pacs008, pacs002Rejected]} />)
    await user.click(screen.getByRole('button', { name: 'pacs.002' }))
    expect(screen.getByText(/reports status RJCT/)).toBeInTheDocument()
    expect(screen.getByText(/Rejected - the instruction has not been/)).toBeInTheDocument()
  })

  it('shows the message timeline', async () => {
    const user = userEvent.setup()
    render(<MessageViewer messages={[pacs008]} />)
    await user.click(screen.getByRole('tab', { name: 'Timeline' }))
    expect(screen.getByText('Generated')).toBeInTheDocument()
    expect(screen.getByText('Correlation id')).toBeInTheDocument()
  })
})
