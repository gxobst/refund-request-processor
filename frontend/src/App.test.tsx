import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import App from './App'

describe('App smoke tests', () => {
  it('mounts cleanly, renders header branding, system status badge, live polling status, and queue table', async () => {
    render(<App />)

    // Header branding
    const titleElement = screen.getByRole('heading', {
      level: 1,
      name: /AI Refund Request Processor/i,
    })
    expect(titleElement).toBeInTheDocument()

    // System status badge
    const healthBadge = screen.getByTestId('system-health-badge')
    expect(healthBadge).toBeInTheDocument()
    expect(healthBadge).toHaveTextContent(/System Operational/i)

    // Live polling status indicator
    const pollingStatus = screen.getByTestId('polling-status')
    expect(pollingStatus).toBeInTheDocument()

    // Section header and New Refund button
    expect(screen.getByText(/Back-Office Operations/i)).toBeInTheDocument()
    expect(screen.getByTestId('new-refund-button')).toHaveTextContent(/\+ New Refund/i)

    // Refund queue table renders records
    await waitFor(() => {
      expect(screen.getByRole('table')).toBeInTheDocument()
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
    })
  })

  it('detects URL query param ?clarify=<refundId> on load and automatically opens CustomerClarificationModal', async () => {
    window.history.pushState({}, '', '/?clarify=ref-102')

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument()
      expect(screen.getByText('Customer Clarification Portal')).toBeInTheDocument()
      expect(screen.getByTestId('clarification-order-id')).toHaveTextContent('ORD-1002')
    })

    window.history.pushState({}, '', '/')
  })

  it('detects URL pathname /clarify/<refundId> on load and automatically opens CustomerClarificationModal', async () => {
    window.history.pushState({}, '', '/clarify/ref-102')

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument()
      expect(screen.getByText('Customer Clarification Portal')).toBeInTheDocument()
      expect(screen.getByTestId('clarification-order-id')).toHaveTextContent('ORD-1002')
    })

    window.history.pushState({}, '', '/')
  })

  it('opens CustomerClarificationModal from RefundDetailDrawer when status is awaiting_clarification and submits clarification', async () => {
    const { fireEvent } = await import('@testing-library/react')
    render(<App />)

    // Wait for queue table to load
    await waitFor(() => {
      expect(screen.getByText('ORD-1003')).toBeInTheDocument()
    })

    // Click inspect button for ORD-1003
    const inspectBtn = screen.getByRole('button', { name: /review order ord-1003/i })
    fireEvent.click(inspectBtn)

    // Wait for drawer and click "Submit Clarification" button
    await waitFor(() => {
      const clarifyBtn = screen.getByTestId('drawer-clarify-button')
      expect(clarifyBtn).toBeInTheDocument()
      expect(clarifyBtn).toBeEnabled()
    })

    const drawerClarifyBtn = screen.getByTestId('drawer-clarify-button')
    fireEvent.click(drawerClarifyBtn)

    // Verify modal is open with prompt
    await waitFor(() => {
      expect(screen.getByText('Customer Clarification Portal')).toBeInTheDocument()
      expect(screen.getByTestId('clarification-order-id')).toHaveTextContent('ORD-1003')
      expect(screen.getByTestId('clarification-inquiry-prompt')).toHaveTextContent(
        'Please upload a photo of the exterior shipping box and packing slip.'
      )
    })

    // Fill clarification response
    const textarea = screen.getByTestId('clarification-response-textarea')
    fireEvent.change(textarea, {
      target: { value: 'Here is the clarification: the outer box was partially opened upon arrival.' },
    })

    // Submit clarification
    const submitBtn = screen.getByTestId('clarification-submit-button')
    fireEvent.click(submitBtn)

    // Verify success confirmation state
    await waitFor(() => {
      expect(screen.getByTestId('clarification-success-state')).toBeInTheDocument()
    })

    // Click Done to close modal
    const doneBtn = screen.getByTestId('clarification-done-button')
    fireEvent.click(doneBtn)

    await waitFor(() => {
      expect(screen.queryByTestId('clarification-success-state')).not.toBeInTheDocument()
    })
  })
})
