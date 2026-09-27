import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AppLayout } from './AppLayout'

describe('AppLayout component', () => {
  it('renders header branding, system health status, and child content', () => {
    render(
      <AppLayout>
        <div data-testid="test-content">Back-Office Queue Dashboard</div>
      </AppLayout>
    )

    // Header branding
    const brandTitles = screen.getAllByText('AI Refund Request Processor')
    expect(brandTitles.length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('Back Office')).toBeInTheDocument()

    // System health badge default (operational)
    const healthBadge = screen.getByTestId('system-health-badge')
    expect(healthBadge).toBeInTheDocument()
    expect(healthBadge).toHaveTextContent('System Operational')

    // Child content
    expect(screen.getByTestId('test-content')).toBeInTheDocument()
    expect(screen.getByText('Back-Office Queue Dashboard')).toBeInTheDocument()

    // Footer
    expect(screen.getByText(/Autonomous Multi-Agent Decision Engine/i)).toBeInTheDocument()
    expect(screen.getByText(/WCAG AA Compliant/i)).toBeInTheDocument()
  })

  it('renders degraded system health status when specified', () => {
    render(
      <AppLayout headerProps={{ systemHealth: 'degraded' }}>
        <div>Content</div>
      </AppLayout>
    )

    const healthBadge = screen.getByTestId('system-health-badge')
    expect(healthBadge).toHaveTextContent('Degraded Performance')
  })

  it('renders polling indicator when isPolling is active', () => {
    render(
      <AppLayout headerProps={{ isPolling: true, pollingIntervalSeconds: 2 }}>
        <div>Content</div>
      </AppLayout>
    )

    const pollingStatus = screen.getByTestId('polling-status')
    expect(pollingStatus).toHaveTextContent(/Live - polling every 2s/i)
  })

  it('renders idle status when isPolling is false', () => {
    render(
      <AppLayout headerProps={{ isPolling: false }}>
        <div>Content</div>
      </AppLayout>
    )

    const pollingStatus = screen.getByTestId('polling-status')
    expect(pollingStatus).toHaveTextContent(/Idle/i)
  })
})
