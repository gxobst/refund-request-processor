import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import { AnalyticsDashboardModal } from '@/components/analytics/AnalyticsDashboardModal'
import type { AnalyticsMetrics, AnalyticsTrendsResponse } from '@/services/analyticsService'

const MOCK_METRICS: AnalyticsMetrics = {
  total_requests: 10,
  status_breakdown: {
    pending: 2,
    completed: 5,
    escalated: 2,
    awaiting_clarification: 1,
  },
  decision_breakdown: {
    auto_approve: 6,
    deny: 2,
    escalate: 2,
    pending: 0,
  },
  auto_approval_rate: 0.6,
  override_rate: 0.2,
  average_confidence: 0.88,
  category_breakdown: {
    damaged: 6,
    wrong_item: 4,
  },
  average_latency_ms: 150,
  node_latency_breakdown: {
    classifier: 40,
    policy_checker: 60,
    decision_agent: 50,
  },
}

const MOCK_TRENDS: AnalyticsTrendsResponse = {
  interval: 'daily',
  start_date: null,
  end_date: null,
  points: [
    {
      period: '2026-10-01',
      total_requests: 5,
      auto_approved: 3,
      denied: 1,
      escalated: 1,
      average_confidence: 0.9,
      average_latency_ms: 140,
    },
  ],
}

function renderModal(onClose = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AnalyticsDashboardModal isOpen={true} onClose={onClose} />
    </QueryClientProvider>
  )
}

describe('Operational Analytics CSV & PDF Export Integration Tests', () => {
  let createObjectURLSpy: any
  let revokeObjectURLSpy: any
  let anchorClickSpy: any

  beforeEach(() => {
    createObjectURLSpy = vi.fn().mockReturnValue('blob:mock-export-url')
    revokeObjectURLSpy = vi.fn()
    window.URL.createObjectURL = createObjectURLSpy
    window.URL.revokeObjectURL = revokeObjectURLSpy

    anchorClickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    server.use(
      http.get('*/v1/analytics/metrics', () => {
        return HttpResponse.json(MOCK_METRICS)
      }),
      http.get('*/v1/analytics/trends', () => {
        return HttpResponse.json(MOCK_TRENDS)
      })
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders export controls in modal (analytics-export-button, analytics-export-csv, analytics-export-pdf)', async () => {
    renderModal()

    await waitFor(() => {
      expect(screen.getByTestId('analytics-dashboard-modal')).toBeInTheDocument()
    })

    const exportButton = screen.getByTestId('analytics-export-button')
    expect(exportButton).toBeInTheDocument()
    expect(exportButton).toHaveTextContent('Export')

    const csvButton = screen.getByTestId('analytics-export-csv')
    expect(csvButton).toBeInTheDocument()
    expect(csvButton).toHaveTextContent('Export as CSV')

    const pdfButton = screen.getByTestId('analytics-export-pdf')
    expect(pdfButton).toBeInTheDocument()
    expect(pdfButton).toHaveTextContent('Export as PDF')
  })

  it('clicking CSV export calls /v1/analytics/export?format=csv and initiates download', async () => {
    let capturedUrl = ''

    server.use(
      http.get('*/v1/analytics/export', ({ request }) => {
        capturedUrl = request.url
        return new HttpResponse('OVERALL KPIS\nTotal Requests,10\n', {
          status: 200,
          headers: {
            'Content-Type': 'text/csv; charset=utf-8',
            'Content-Disposition': 'attachment; filename="analytics-report-2026-10-03.csv"',
          },
        })
      })
    )

    renderModal()

    await waitFor(() => {
      expect(screen.getByTestId('analytics-dashboard-modal')).toBeInTheDocument()
    })

    const csvButton = screen.getByTestId('analytics-export-csv')
    fireEvent.click(csvButton)

    await waitFor(() => {
      expect(capturedUrl).toContain('/v1/analytics/export')
      expect(capturedUrl).toContain('format=csv')
      expect(createObjectURLSpy).toHaveBeenCalled()
      expect(anchorClickSpy).toHaveBeenCalled()
    })
  })

  it('clicking PDF export calls /v1/analytics/export?format=pdf and initiates download', async () => {
    let capturedUrl = ''

    server.use(
      http.get('*/v1/analytics/export', ({ request }) => {
        capturedUrl = request.url
        return new HttpResponse(new Uint8Array([0x25, 0x50, 0x44, 0x46]), {
          status: 200,
          headers: {
            'Content-Type': 'application/pdf',
            'Content-Disposition': 'attachment; filename="analytics-report-2026-10-03.pdf"',
          },
        })
      })
    )

    renderModal()

    await waitFor(() => {
      expect(screen.getByTestId('analytics-dashboard-modal')).toBeInTheDocument()
    })

    const pdfButton = screen.getByTestId('analytics-export-pdf')
    fireEvent.click(pdfButton)

    await waitFor(() => {
      expect(capturedUrl).toContain('/v1/analytics/export')
      expect(capturedUrl).toContain('format=pdf')
      expect(createObjectURLSpy).toHaveBeenCalled()
      expect(anchorClickSpy).toHaveBeenCalled()
    })
  })

  it('clicking export with active date range passes start_date and end_date parameters', async () => {
    let capturedUrl = ''

    server.use(
      http.get('*/v1/analytics/export', ({ request }) => {
        capturedUrl = request.url
        return new HttpResponse('OVERALL KPIS\n', {
          status: 200,
          headers: { 'Content-Type': 'text/csv; charset=utf-8' },
        })
      })
    )

    renderModal()

    const preset7d = await screen.findByTestId('analytics-date-filter-preset-7d')
    fireEvent.click(preset7d)

    // Export CSV
    const csvButton = screen.getByTestId('analytics-export-csv')
    fireEvent.click(csvButton)

    await waitFor(() => {
      expect(capturedUrl).toContain('format=csv')
      expect(capturedUrl).toContain('start_date=')
      expect(capturedUrl).toContain('end_date=')
      expect(anchorClickSpy).toHaveBeenCalled()
    })
  })

  it('displays error alert when export fails without crashing modal', async () => {
    server.use(
      http.get('*/v1/analytics/export', () => {
        return HttpResponse.json({ detail: 'Internal server error during export' }, { status: 500 })
      })
    )

    renderModal()

    await waitFor(() => {
      expect(screen.getByTestId('analytics-dashboard-modal')).toBeInTheDocument()
    })

    const csvButton = screen.getByTestId('analytics-export-csv')
    fireEvent.click(csvButton)

    await waitFor(() => {
      expect(screen.getByTestId('analytics-export-error')).toBeInTheDocument()
      expect(screen.getByText(/Internal server error during export/i)).toBeInTheDocument()
    })

    // Dismiss error
    const dismissButton = screen.getByRole('button', { name: /dismiss/i })
    fireEvent.click(dismissButton)
    expect(screen.queryByTestId('analytics-export-error')).not.toBeInTheDocument()
  })
})
