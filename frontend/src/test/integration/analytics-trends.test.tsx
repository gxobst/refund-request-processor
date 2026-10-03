import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import App from '@/App'
import type { AnalyticsMetrics, AnalyticsTrendsResponse } from '@/services/analyticsService'

const MOCK_METRICS: AnalyticsMetrics = {
  total_requests: 15,
  status_breakdown: {
    pending: 2,
    completed: 10,
    escalated: 2,
    awaiting_clarification: 1,
  },
  decision_breakdown: {
    auto_approve: 10,
    deny: 2,
    escalate: 2,
    pending: 1,
  },
  auto_approval_rate: 0.6667,
  override_rate: 0.1,
  average_confidence: 0.9125,
  category_breakdown: {
    damaged: 8,
    wrong_item: 7,
  },
  average_latency_ms: 320.5,
  node_latency_breakdown: {
    classifier: 50.0,
    policy_checker: 150.0,
    decision_agent: 120.5,
  },
}

const MOCK_DAILY_TRENDS: AnalyticsTrendsResponse = {
  interval: 'daily',
  start_date: null,
  end_date: null,
  points: [
    {
      period: '2026-10-01',
      total_requests: 6,
      auto_approved: 4,
      denied: 1,
      escalated: 1,
      average_confidence: 0.92,
      average_latency_ms: 310.0,
    },
    {
      period: '2026-10-02',
      total_requests: 9,
      auto_approved: 6,
      denied: 1,
      escalated: 1,
      average_confidence: 0.90,
      average_latency_ms: 330.0,
    },
  ],
}

const MOCK_WEEKLY_TRENDS: AnalyticsTrendsResponse = {
  interval: 'weekly',
  start_date: null,
  end_date: null,
  points: [
    {
      period: '2026-W40',
      total_requests: 15,
      auto_approved: 10,
      denied: 2,
      escalated: 2,
      average_confidence: 0.91,
      average_latency_ms: 320.5,
    },
  ],
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

describe('Time-Series Historical Trend Analytics and Date Range Filtering Tests', () => {
  beforeEach(() => {
    server.use(
      http.get('*/v1/analytics/metrics', () => {
        return HttpResponse.json(MOCK_METRICS, { status: 200 })
      }),
      http.get('*/v1/analytics/trends', () => {
        return HttpResponse.json(MOCK_DAILY_TRENDS, { status: 200 })
      })
    )
  })

  it('renders date filter presets and interval toggle controls in the analytics modal', async () => {
    renderApp()

    fireEvent.click(screen.getByTestId('analytics-button'))

    await waitFor(() => {
      expect(screen.getByTestId('analytics-dashboard-modal')).toBeInTheDocument()
      expect(screen.getByTestId('analytics-date-filter')).toBeInTheDocument()
      expect(screen.getByTestId('analytics-date-filter-preset-all')).toBeInTheDocument()
      expect(screen.getByTestId('analytics-date-filter-preset-7d')).toBeInTheDocument()
      expect(screen.getByTestId('analytics-date-filter-preset-30d')).toBeInTheDocument()
      expect(screen.getByTestId('analytics-interval-daily')).toBeInTheDocument()
      expect(screen.getByTestId('analytics-interval-weekly')).toBeInTheDocument()
    })
  })

  it('renders time-series trend section with data points and decision breakdown', async () => {
    renderApp()

    fireEvent.click(screen.getByTestId('analytics-button'))

    await waitFor(() => {
      expect(screen.getByTestId('analytics-trend-chart')).toBeInTheDocument()
      expect(screen.getByText('2026-10-01')).toBeInTheDocument()
      expect(screen.getByText('2026-10-02')).toBeInTheDocument()
      expect(screen.getByText(/Auto-approved: 4/)).toBeInTheDocument()
      expect(screen.getAllByText(/Denied: 1/).length).toBeGreaterThan(0)
    })
  })

  it('renders empty state indicator when no trend points exist', async () => {
    server.use(
      http.get('*/v1/analytics/trends', () => {
        return HttpResponse.json(
          {
            interval: 'daily',
            start_date: null,
            end_date: null,
            points: [],
          },
          { status: 200 }
        )
      })
    )

    renderApp()
    fireEvent.click(screen.getByTestId('analytics-button'))

    await waitFor(() => {
      expect(screen.getByTestId('analytics-trend-chart')).toBeInTheDocument()
      expect(screen.getByTestId('analytics-trend-empty')).toBeInTheDocument()
      expect(screen.getByText(/no historical trend (data|points) available/i)).toBeInTheDocument()
    })
  })

  it('switches interval between daily and weekly and requests updated trend aggregation', async () => {
    let capturedInterval: string | null = null

    server.use(
      http.get('*/v1/analytics/trends', ({ request }) => {
        const url = new URL(request.url)
        capturedInterval = url.searchParams.get('interval')
        if (capturedInterval === 'weekly') {
          return HttpResponse.json(MOCK_WEEKLY_TRENDS, { status: 200 })
        }
        return HttpResponse.json(MOCK_DAILY_TRENDS, { status: 200 })
      })
    )

    renderApp()
    fireEvent.click(screen.getByTestId('analytics-button'))

    await waitFor(() => {
      expect(screen.getByText('2026-10-01')).toBeInTheDocument()
    })

    const weeklyBtn = screen.getByTestId('analytics-interval-weekly')
    fireEvent.click(weeklyBtn)

    await waitFor(() => {
      expect(capturedInterval).toBe('weekly')
      expect(screen.getByText('2026-W40')).toBeInTheDocument()
    })
  })

  it('switches date filter presets and passes date query parameters to API', async () => {
    let capturedStartDate: string | null = null
    let capturedEndDate: string | null = null

    server.use(
      http.get('*/v1/analytics/metrics', ({ request }) => {
        const url = new URL(request.url)
        capturedStartDate = url.searchParams.get('start_date')
        capturedEndDate = url.searchParams.get('end_date')
        return HttpResponse.json(MOCK_METRICS, { status: 200 })
      }),
      http.get('*/v1/analytics/trends', ({ request }) => {
        return HttpResponse.json(MOCK_DAILY_TRENDS, { status: 200 })
      })
    )

    renderApp()
    fireEvent.click(screen.getByTestId('analytics-button'))

    await waitFor(() => {
      expect(screen.getByTestId('analytics-date-filter-preset-7d')).toBeInTheDocument()
    })

    const preset7d = screen.getByTestId('analytics-date-filter-preset-7d')
    fireEvent.click(preset7d)

    await waitFor(() => {
      expect(capturedStartDate).not.toBeNull()
      expect(capturedEndDate).not.toBeNull()
      // Date should match YYYY-MM-DD pattern
      expect(capturedStartDate).toMatch(/^\d{4}-\d{2}-\d{2}$/)
      expect(capturedEndDate).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    })

    // Click All Time to clear parameters
    const presetAll = screen.getByTestId('analytics-date-filter-preset-all')
    fireEvent.click(presetAll)

    await waitFor(() => {
      expect(capturedStartDate).toBeNull()
      expect(capturedEndDate).toBeNull()
    })
  })
})
