import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse, delay } from 'msw'
import { server } from '@/test/mocks/server'
import App from '@/App'
import type { AnalyticsMetrics } from '@/services/analyticsService'

const MOCK_METRICS: AnalyticsMetrics = {
  total_requests: 20,
  status_breakdown: {
    pending: 4,
    completed: 10,
    escalated: 4,
    awaiting_clarification: 2,
  },
  decision_breakdown: {
    auto_approve: 13,
    deny: 2,
    escalate: 4,
    pending: 1,
  },
  auto_approval_rate: 0.6500,
  override_rate: 0.1250,
  average_confidence: 0.9240,
  category_breakdown: {
    damaged: 10,
    wrong_item: 6,
    late_delivery: 4,
  },
  average_latency_ms: 1240,
  node_latency_breakdown: {
    classifier: 240,
    policy_checker: 400,
    decision_agent: 600,
  },
}

function renderApp() {
  const testClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  })
  return render(
    <QueryClientProvider client={testClient}>
      <App />
    </QueryClientProvider>
  )
}

describe('Operational Analytics and AI Metrics Dashboard Integration Tests', () => {
  beforeEach(() => {
    server.use(
      http.get('*/v1/analytics/metrics', () => {
        return HttpResponse.json(MOCK_METRICS, { status: 200 })
      })
    )
  })

  it('opens the Analytics modal when header button is clicked', async () => {
    renderApp()

    const analyticsButton = screen.getByTestId('analytics-button')
    expect(analyticsButton).toBeInTheDocument()

    fireEvent.click(analyticsButton)

    await waitFor(() => {
      expect(screen.getByTestId('analytics-dashboard-modal')).toBeInTheDocument()
      expect(
        screen.getByRole('heading', { name: /operational analytics & ai metrics/i })
      ).toBeInTheDocument()
    })
  })

  it('renders loading state while metrics are being fetched', async () => {
    server.use(
      http.get('*/v1/analytics/metrics', async () => {
        await delay(150)
        return HttpResponse.json(MOCK_METRICS, { status: 200 })
      })
    )

    renderApp()
    fireEvent.click(screen.getByTestId('analytics-button'))

    expect(screen.getByTestId('analytics-loading')).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.queryByTestId('analytics-loading')).not.toBeInTheDocument()
      expect(screen.getByTestId('kpi-total-volume')).toBeInTheDocument()
    })
  })

  it('renders four KPI cards with properly formatted values', async () => {
    renderApp()
    fireEvent.click(screen.getByTestId('analytics-button'))

    await waitFor(() => {
      expect(screen.getByTestId('kpi-total-volume')).toBeInTheDocument()
    })

    const totalVolumeCard = screen.getByTestId('kpi-total-volume')
    expect(totalVolumeCard).toHaveTextContent('20')

    const autoApprovalCard = screen.getByTestId('kpi-auto-approval-rate')
    expect(autoApprovalCard).toHaveTextContent('65.0%')

    const overrideRateCard = screen.getByTestId('kpi-override-rate')
    expect(overrideRateCard).toHaveTextContent('12.5%')

    const avgConfidenceCard = screen.getByTestId('kpi-average-confidence')
    expect(avgConfidenceCard).toHaveTextContent('92.4%')
  })

  it('renders decision, status, and category breakdown sections with expected counts', async () => {
    renderApp()
    fireEvent.click(screen.getByTestId('analytics-button'))

    await waitFor(() => {
      expect(screen.getByTestId('decision-distribution')).toBeInTheDocument()
    })

    // Decision breakdown
    const decisionSection = screen.getByTestId('decision-distribution')
    expect(decisionSection).toHaveTextContent('Auto-Approve')
    expect(decisionSection).toHaveTextContent('13')
    expect(decisionSection).toHaveTextContent('Deny')
    expect(decisionSection).toHaveTextContent('2')
    expect(decisionSection).toHaveTextContent('Escalate')
    expect(decisionSection).toHaveTextContent('4')
    expect(decisionSection).toHaveTextContent('Pending')
    expect(decisionSection).toHaveTextContent('1')

    // Status breakdown
    const statusSection = screen.getByTestId('status-distribution')
    expect(statusSection).toHaveTextContent('Pending')
    expect(statusSection).toHaveTextContent('4')
    expect(statusSection).toHaveTextContent('Completed')
    expect(statusSection).toHaveTextContent('10')
    expect(statusSection).toHaveTextContent('Escalated')
    expect(statusSection).toHaveTextContent('4')
    expect(statusSection).toHaveTextContent('Awaiting Clarification')
    expect(statusSection).toHaveTextContent('2')

    // Category breakdown
    const categorySection = screen.getByTestId('category-distribution')
    expect(categorySection).toHaveTextContent('Damaged Item')
    expect(categorySection).toHaveTextContent('10')
    expect(categorySection).toHaveTextContent('Wrong Item')
    expect(categorySection).toHaveTextContent('6')
    expect(categorySection).toHaveTextContent('Late Delivery')
    expect(categorySection).toHaveTextContent('4')
  })

  it('displays empty state banner when total_requests is 0', async () => {
    server.use(
      http.get('*/v1/analytics/metrics', () => {
        return HttpResponse.json(
          {
            total_requests: 0,
            status_breakdown: { pending: 0, completed: 0, escalated: 0, awaiting_clarification: 0 },
            decision_breakdown: { auto_approve: 0, deny: 0, escalate: 0, pending: 0 },
            auto_approval_rate: 0.0,
            override_rate: 0.0,
            average_confidence: 0.0,
            category_breakdown: {},
          },
          { status: 200 }
        )
      })
    )

    renderApp()
    fireEvent.click(screen.getByTestId('analytics-button'))

    await waitFor(() => {
      expect(screen.getByTestId('analytics-empty')).toBeInTheDocument()
    })

    expect(screen.getByText('No Analytics Data Available')).toBeInTheDocument()
    expect(screen.queryByTestId('kpi-total-volume')).not.toBeInTheDocument()
  })

  it('displays error alert on API failure with working retry button', async () => {
    let callCount = 0
    server.use(
      http.get('*/v1/analytics/metrics', () => {
        callCount++
        if (callCount === 1) {
          return HttpResponse.json(
            { detail: 'Internal server error processing analytics' },
            { status: 500 }
          )
        }
        return HttpResponse.json(MOCK_METRICS, { status: 200 })
      })
    )

    renderApp()
    fireEvent.click(screen.getByTestId('analytics-button'))

    await waitFor(() => {
      expect(screen.getByTestId('analytics-error')).toBeInTheDocument()
    })

    expect(screen.getByText(/failed to load analytics metrics/i)).toBeInTheDocument()

    // Click retry
    const retryButton = screen.getByRole('button', { name: /retry/i })
    fireEvent.click(retryButton)

    await waitFor(() => {
      expect(screen.queryByTestId('analytics-error')).not.toBeInTheDocument()
      expect(screen.getByTestId('kpi-total-volume')).toBeInTheDocument()
      expect(screen.getByTestId('kpi-total-volume')).toHaveTextContent('20')
    })
  })

  it('refetches metrics when refresh button is clicked without closing modal', async () => {
    let requestCount = 0
    server.use(
      http.get('*/v1/analytics/metrics', () => {
        requestCount++
        if (requestCount === 1) {
          return HttpResponse.json(MOCK_METRICS, { status: 200 })
        }
        return HttpResponse.json(
          {
            ...MOCK_METRICS,
            total_requests: 35,
          },
          { status: 200 }
        )
      })
    )

    renderApp()
    fireEvent.click(screen.getByTestId('analytics-button'))

    await waitFor(() => {
      expect(screen.getByTestId('kpi-total-volume')).toHaveTextContent('20')
    })

    const refreshButton = screen.getByTestId('analytics-refresh-button')
    fireEvent.click(refreshButton)

    await waitFor(() => {
      expect(screen.getByTestId('kpi-total-volume')).toHaveTextContent('35')
    })

    expect(screen.getByTestId('analytics-dashboard-modal')).toBeInTheDocument()
  })

  it('closes the modal when close button is clicked', async () => {
    renderApp()
    fireEvent.click(screen.getByTestId('analytics-button'))

    await waitFor(() => {
      expect(screen.getByTestId('analytics-dashboard-modal')).toBeInTheDocument()
    })

    const closeButton = screen.getByTestId('analytics-close-button')
    fireEvent.click(closeButton)

    await waitFor(() => {
      expect(screen.queryByTestId('analytics-dashboard-modal')).not.toBeInTheDocument()
    })
  })
})
