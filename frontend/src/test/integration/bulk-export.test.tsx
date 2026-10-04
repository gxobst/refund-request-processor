import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import { mockRefunds } from '@/test/mocks/handlers'
import { RefundQueueTable } from '@/components/queue/RefundQueueTable'

function renderRefundQueueTable(initialStatus = 'all') {
  const testClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  })
  return {
    ...render(
      <QueryClientProvider client={testClient}>
        <RefundQueueTable initialStatus={initialStatus} />
      </QueryClientProvider>
    ),
    client: testClient,
  }
}

describe('Bulk Export Queue Integration Tests', () => {
  let clickSpy: any

  beforeEach(() => {
    clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  })

  afterEach(() => {
    clickSpy.mockRestore()
    vi.restoreAllMocks()
  })

  it('renders the bulk export trigger button in table toolbar', async () => {
    server.use(
      http.get('*/v1/refunds', () => {
        return HttpResponse.json(mockRefunds)
      })
    )

    renderRefundQueueTable()

    // Wait for queue records to load
    await screen.findByText('ORD-1001')

    const bulkButton = screen.getByTestId('bulk-export-button')
    expect(bulkButton).toBeInTheDocument()
    expect(bulkButton).toHaveTextContent(/Bulk Export/i)
    expect(bulkButton).not.toBeDisabled()
  })

  it('clicking bulk export dispatches createBulkExportJob, shows progress indicator, polls until completed, and triggers file download', async () => {
    let pollCount = 0

    server.use(
      http.get('*/v1/refunds', () => {
        return HttpResponse.json(mockRefunds)
      }),
      http.post('*/v1/refunds/export/jobs', async ({ request }) => {
        const body = (await request.json()) as { format: string; status?: string }
        return HttpResponse.json(
          {
            job_id: 'exp_test_001',
            status: 'pending',
            format: body.format || 'csv',
            created_at: new Date().toISOString(),
            expires_at: new Date(Date.now() + 3600000).toISOString(),
            download_url: null,
            record_count: null,
            error: null,
          },
          { status: 202 }
        )
      }),
      http.get('*/v1/refunds/export/jobs/exp_test_001', () => {
        pollCount++
        if (pollCount === 1) {
          return HttpResponse.json({
            job_id: 'exp_test_001',
            status: 'processing',
            format: 'csv',
            created_at: new Date().toISOString(),
            download_url: null,
            record_count: null,
            error: null,
          })
        }
        return HttpResponse.json({
          job_id: 'exp_test_001',
          status: 'completed',
          format: 'csv',
          created_at: new Date().toISOString(),
          completed_at: new Date().toISOString(),
          download_url: '/v1/refunds/export/jobs/exp_test_001/download',
          record_count: 5,
          error: null,
        })
      })
    )

    renderRefundQueueTable()

    await screen.findByText('ORD-1001')

    const bulkButton = screen.getByTestId('bulk-export-button')
    fireEvent.click(bulkButton)

    // Progress indicator should appear
    const statusIndicator = await screen.findByTestId('bulk-export-status')
    expect(statusIndicator).toBeInTheDocument()
    expect(statusIndicator).toHaveTextContent(/Exporting refund requests in background/i)

    // Wait until completed
    await waitFor(() => {
      expect(screen.getByTestId('bulk-export-status')).toHaveTextContent(/Export completed! Download started./i)
    })

    // Verify browser file download trigger was called
    expect(clickSpy).toHaveBeenCalled()
  })

  it('displays error status banner when export job fails without crashing queue table', async () => {
    server.use(
      http.get('*/v1/refunds', () => {
        return HttpResponse.json(mockRefunds)
      }),
      http.post('*/v1/refunds/export/jobs', () => {
        return HttpResponse.json(
          {
            job_id: 'exp_fail_002',
            status: 'pending',
            format: 'csv',
            created_at: new Date().toISOString(),
            download_url: null,
            record_count: null,
            error: null,
          },
          { status: 202 }
        )
      }),
      http.get('*/v1/refunds/export/jobs/exp_fail_002', () => {
        return HttpResponse.json({
          job_id: 'exp_fail_002',
          status: 'failed',
          format: 'csv',
          created_at: new Date().toISOString(),
          completed_at: new Date().toISOString(),
          download_url: null,
          record_count: null,
          error: 'Backend export worker out of memory',
        })
      })
    )

    renderRefundQueueTable()

    await screen.findByText('ORD-1001')

    const bulkButton = screen.getByTestId('bulk-export-button')
    fireEvent.click(bulkButton)

    // Verify error banner is displayed
    const statusIndicator = await screen.findByTestId('bulk-export-status')
    await waitFor(() => {
      expect(statusIndicator).toHaveTextContent(/Backend export worker out of memory/i)
    })

    // Verify queue table still displays data and did not crash
    expect(screen.getByText('ORD-1001')).toBeInTheDocument()
  })

  it('displays error banner if job creation request fails with network error', async () => {
    server.use(
      http.get('*/v1/refunds', () => {
        return HttpResponse.json(mockRefunds)
      }),
      http.post('*/v1/refunds/export/jobs', () => {
        return HttpResponse.json(
          {
            type: 'urn:problem:bad-request',
            title: 'Bad Request',
            status: 400,
            detail: 'start_date cannot be after end_date.',
          },
          { status: 400 }
        )
      })
    )

    renderRefundQueueTable()

    await screen.findByText('ORD-1001')

    const bulkButton = screen.getByTestId('bulk-export-button')
    fireEvent.click(bulkButton)

    const statusIndicator = await screen.findByTestId('bulk-export-status')
    await waitFor(() => {
      expect(statusIndicator).toHaveTextContent(/Export failed:/i)
    })
  })
})
