import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import { mockRefunds, resetMockSchedules } from '@/test/mocks/handlers'
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

describe('Scheduled Queue Reports Integration Tests', () => {
  beforeEach(() => {
    resetMockSchedules()
    server.use(
      http.get('*/v1/refunds', () => {
        return HttpResponse.json(mockRefunds)
      })
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
    resetMockSchedules()
  })

  it('clicking "Scheduled Reports..." in export menu opens ScheduledExportsModal', async () => {
    renderRefundQueueTable()
    await screen.findByText('ORD-1001')

    // Open export dropdown
    const exportDropdownButton = screen.getByTestId('export-dropdown-button')
    fireEvent.click(exportDropdownButton)

    // Scheduled Reports menu item
    const scheduledMenuItem = screen.getByTestId('scheduled-exports-button')
    expect(scheduledMenuItem).toBeInTheDocument()
    expect(scheduledMenuItem).toHaveTextContent(/Scheduled Reports/i)

    fireEvent.click(scheduledMenuItem)

    const modal = await screen.findByTestId('scheduled-exports-modal')
    expect(modal).toBeInTheDocument()
    expect(screen.getByText('Scheduled Queue Reports')).toBeInTheDocument()
  })

  it('renders configured schedules list with frequency badge, recipients, format, and enabled toggle', async () => {
    renderRefundQueueTable()
    await screen.findByText('ORD-1001')

    fireEvent.click(screen.getByTestId('export-dropdown-button'))
    fireEvent.click(screen.getByTestId('scheduled-exports-button'))

    await screen.findByTestId('scheduled-exports-modal')

    // Schedule list container
    const list = await screen.findByTestId('schedule-list')
    expect(list).toBeInTheDocument()

    // Default mock schedule elements
    expect(screen.getByText('Daily Queue Summary')).toBeInTheDocument()
    const freqBadge = screen.getByTestId('schedule-frequency-sch_default_1')
    expect(freqBadge).toHaveTextContent(/daily/i)

    const recipientsEl = screen.getByTestId('schedule-recipients-sch_default_1')
    expect(recipientsEl).toHaveTextContent(/admin@example\.com/)

    const formatBadge = screen.getByTestId('schedule-format-sch_default_1')
    expect(formatBadge).toHaveTextContent(/CSV/i)

    const toggle = screen.getByTestId('schedule-enabled-sch_default_1') as HTMLInputElement
    expect(toggle.checked).toBe(true)
  })

  it('creates a new schedule via create-schedule-form and adds it to the list', async () => {
    renderRefundQueueTable()
    await screen.findByText('ORD-1001')

    fireEvent.click(screen.getByTestId('export-dropdown-button'))
    fireEvent.click(screen.getByTestId('scheduled-exports-button'))

    await screen.findByTestId('scheduled-exports-modal')

    // Fill form
    const nameInput = screen.getByTestId('schedule-name-input') as HTMLInputElement
    const recipientsInput = screen.getByTestId('schedule-recipients-input') as HTMLInputElement
    const freqSelect = screen.getByTestId('schedule-frequency-select') as HTMLSelectElement
    const formatSelect = screen.getByTestId('schedule-format-select') as HTMLSelectElement

    fireEvent.change(nameInput, { target: { value: 'Weekly Audit Digest' } })
    fireEvent.change(recipientsInput, { target: { value: 'auditor@example.com, security@example.com' } })
    fireEvent.change(freqSelect, { target: { value: 'weekly' } })
    fireEvent.change(formatSelect, { target: { value: 'json' } })

    const submitBtn = screen.getByTestId('create-schedule-submit')
    fireEvent.click(submitBtn)

    // Should appear in list
    await waitFor(() => {
      expect(screen.getByText('Weekly Audit Digest')).toBeInTheDocument()
    })

    // Form inputs should reset
    expect(nameInput.value).toBe('')
    expect(recipientsInput.value).toBe('')
  })

  it('triggers manual run via "Run Now" button and displays execution result feedback', async () => {
    renderRefundQueueTable()
    await screen.findByText('ORD-1001')

    fireEvent.click(screen.getByTestId('export-dropdown-button'))
    fireEvent.click(screen.getByTestId('scheduled-exports-button'))

    await screen.findByTestId('scheduled-exports-modal')
    await screen.findByText('Daily Queue Summary')

    const triggerBtn = screen.getByTestId('schedule-trigger-sch_default_1')
    fireEvent.click(triggerBtn)

    // Verify feedback message
    await waitFor(() => {
      expect(
        screen.getByText(/Dispatched to 2 recipient\(s\) \(12 records\)\./i)
      ).toBeInTheDocument()
    })
  })

  it('deletes a schedule via "Delete" button and removes it from the list', async () => {
    renderRefundQueueTable()
    await screen.findByText('ORD-1001')

    fireEvent.click(screen.getByTestId('export-dropdown-button'))
    fireEvent.click(screen.getByTestId('scheduled-exports-button'))

    await screen.findByTestId('scheduled-exports-modal')
    await screen.findByText('Daily Queue Summary')

    const deleteBtn = screen.getByTestId('schedule-delete-sch_default_1')
    fireEvent.click(deleteBtn)

    await waitFor(() => {
      expect(screen.queryByText('Daily Queue Summary')).not.toBeInTheDocument()
    })
  })
})
