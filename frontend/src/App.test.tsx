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
})
