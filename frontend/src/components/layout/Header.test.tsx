import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Header } from './Header'

describe('Header component', () => {
  it('renders application branding and default operational status', () => {
    render(<Header />)

    expect(screen.getByText('AI Refund Request Processor')).toBeInTheDocument()
    expect(screen.getByText('Back Office')).toBeInTheDocument()

    const badge = screen.getByTestId('system-health-badge')
    expect(badge).toHaveTextContent('System Operational')

    const polling = screen.getByTestId('polling-status')
    expect(polling).toHaveTextContent(/Idle/i)
  })

  it('renders offline system health badge', () => {
    render(<Header systemHealth="offline" />)

    const badge = screen.getByTestId('system-health-badge')
    expect(badge).toHaveTextContent('System Offline')
  })

  it('renders polling indicator when isPolling is true', () => {
    render(<Header isPolling={true} pollingIntervalSeconds={3} />)

    const polling = screen.getByTestId('polling-status')
    expect(polling).toHaveTextContent(/Live - polling every 3s/i)
  })

  it('triggers onManualRefresh when refresh button clicked', () => {
    const handleRefresh = vi.fn()
    render(<Header onManualRefresh={handleRefresh} />)

    const refreshBtn = screen.getByRole('button', { name: /refresh refund queue/i })
    expect(refreshBtn).toBeInTheDocument()

    fireEvent.click(refreshBtn)
    expect(handleRefresh).toHaveBeenCalledTimes(1)
  })
})
