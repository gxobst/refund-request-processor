import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import { mockRefunds } from '@/test/mocks/handlers'
import { RefundQueueTable } from '@/components/queue/RefundQueueTable'
import * as exportUtils from '@/utils/exportUtils'

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

describe('Refund Queue Export Integration Tests', () => {
  let downloadSpy: any

  beforeEach(() => {
    downloadSpy = vi.spyOn(exportUtils, 'downloadExportFile').mockImplementation(() => {})
  })

  afterEach(() => {
    downloadSpy.mockRestore()
    vi.restoreAllMocks()
  })

  it('renders Export trigger button in table toolbar alongside Refresh', async () => {
    server.use(
      http.get('*/v1/refunds', () => {
        return HttpResponse.json(mockRefunds)
      })
    )

    renderRefundQueueTable()

    // Wait for records to load
    await screen.findByText('ORD-1001')

    const exportButton = screen.getByTestId('export-dropdown-button')
    expect(exportButton).toBeInTheDocument()
    expect(exportButton).toHaveTextContent('Export')
    expect(exportButton).not.toBeDisabled()

    const refreshButton = screen.getByRole('button', { name: /refresh table/i })
    expect(refreshButton).toBeInTheDocument()
  })

  it('toggles dropdown menu on click, closes on Escape, and closes on outside click', async () => {
    const user = userEvent.setup()
    server.use(
      http.get('*/v1/refunds', () => {
        return HttpResponse.json(mockRefunds)
      })
    )

    renderRefundQueueTable()

    await screen.findByText('ORD-1001')

    const exportButton = screen.getByTestId('export-dropdown-button')
    expect(screen.queryByTestId('export-csv-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('export-json-button')).not.toBeInTheDocument()

    // Click to open dropdown
    await user.click(exportButton)
    expect(screen.getByTestId('export-csv-button')).toBeInTheDocument()
    expect(screen.getByTestId('export-json-button')).toBeInTheDocument()
    expect(exportButton).toHaveAttribute('aria-expanded', 'true')

    // Press Escape to close dropdown
    await user.keyboard('{Escape}')
    expect(screen.queryByTestId('export-csv-button')).not.toBeInTheDocument()
    expect(exportButton).toHaveAttribute('aria-expanded', 'false')

    // Click to open again
    await user.click(exportButton)
    expect(screen.getByTestId('export-csv-button')).toBeInTheDocument()

    // Click outside to close dropdown
    await user.click(document.body)
    expect(screen.queryByTestId('export-csv-button')).not.toBeInTheDocument()
  })

  it('disables Export button with tooltip title when queue is empty', async () => {
    server.use(
      http.get('*/v1/refunds', () => {
        return HttpResponse.json([])
      })
    )

    renderRefundQueueTable()

    await waitFor(() => {
      expect(screen.getByTestId('empty-state')).toBeInTheDocument()
    })

    const exportButton = screen.getByTestId('export-dropdown-button')
    expect(exportButton).toBeDisabled()
    expect(exportButton).toHaveAttribute('title', 'No refund requests to export')

    // Clicking disabled button should not open dropdown
    fireEvent.click(exportButton)
    expect(screen.queryByTestId('export-csv-button')).not.toBeInTheDocument()
  })

  it('clicking Export as CSV downloads CSV file with active "all" tab filename and closes dropdown', async () => {
    const user = userEvent.setup()
    server.use(
      http.get('*/v1/refunds', () => {
        return HttpResponse.json(mockRefunds)
      })
    )

    renderRefundQueueTable('all')

    await screen.findByText('ORD-1001')

    const exportButton = screen.getByTestId('export-dropdown-button')
    await user.click(exportButton)

    const csvButton = screen.getByTestId('export-csv-button')
    await user.click(csvButton)

    // Dropdown should close
    expect(screen.queryByTestId('export-csv-button')).not.toBeInTheDocument()

    // Download should have been invoked
    expect(downloadSpy).toHaveBeenCalledTimes(1)
    const [content, filename, mimeType] = downloadSpy.mock.calls[0]
    expect(mimeType).toContain('text/csv')

    // Verify filename format
    expect(filename).toMatch(/^refunds-all-\d{8}-\d{6}\.csv$/)

    // Verify content contains RFC 4180 headers
    expect(content).toContain('Refund ID,Order ID,Status,Decision,Category')
    expect(content).toContain('ORD-1001')
  })

  it('clicking Export as JSON downloads JSON file with active status tab filename and closes dropdown', async () => {
    const user = userEvent.setup()
    server.use(
      http.get('*/v1/refunds', ({ request }) => {
        const url = new URL(request.url)
        const status = url.searchParams.get('status')
        const filtered = status ? mockRefunds.filter((r) => r.status === status) : mockRefunds
        return HttpResponse.json(filtered)
      })
    )

    renderRefundQueueTable('all')

    await screen.findByText('ORD-1001')

    // Switch to Pending tab
    const pendingTab = screen.getByRole('tab', { name: /^pending/i })
    await user.click(pendingTab)

    await waitFor(() => {
      expect(screen.getByText('ORD-1004')).toBeInTheDocument()
    })

    const exportButton = screen.getByTestId('export-dropdown-button')
    await user.click(exportButton)

    const jsonButton = screen.getByTestId('export-json-button')
    await user.click(jsonButton)

    // Dropdown should close
    expect(screen.queryByTestId('export-json-button')).not.toBeInTheDocument()

    // Download should have been invoked
    expect(downloadSpy).toHaveBeenCalledTimes(1)
    const [content, filename, mimeType] = downloadSpy.mock.calls[0]
    expect(mimeType).toContain('application/json')

    // Verify filename format reflects pending status
    expect(filename).toMatch(/^refunds-pending-\d{8}-\d{6}\.json$/)

    // Verify JSON content represents pending records
    const parsed = JSON.parse(content as string)
    expect(Array.isArray(parsed)).toBe(true)
    expect(parsed.every((r: { status: string }) => r.status === 'pending')).toBe(true)
  })
})
