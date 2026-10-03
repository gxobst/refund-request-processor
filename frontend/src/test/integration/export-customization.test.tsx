import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import { mockRefunds } from '@/test/mocks/handlers'
import { RefundQueueTable } from '@/components/queue/RefundQueueTable'
import { LOCAL_STORAGE_KEY } from '@/components/modals/ExportCustomizationModal'

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

describe('Customizable Queue Export Integration Tests', () => {
  let clickSpy: ReturnType<typeof vi.spyOn>
  let createObjectURLSpy: ReturnType<typeof vi.fn>
  let revokeObjectURLSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    localStorage.clear()
    clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    createObjectURLSpy = vi.fn(() => 'blob:http://localhost/mock-blob-uuid')
    revokeObjectURLSpy = vi.fn()
    window.URL.createObjectURL = createObjectURLSpy
    window.URL.revokeObjectURL = revokeObjectURLSpy

    server.use(
      http.get('*/v1/refunds', () => {
        return HttpResponse.json(mockRefunds)
      })
    )
  })

  afterEach(() => {
    clickSpy.mockRestore()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('clicking "Customize Export..." opens ExportCustomizationModal', async () => {
    renderRefundQueueTable()
    await screen.findByText('ORD-1001')

    const exportDropdownButton = screen.getByTestId('export-dropdown-button')
    fireEvent.click(exportDropdownButton)

    const customizeMenuItem = screen.getByTestId('customize-export-menu-item')
    expect(customizeMenuItem).toBeInTheDocument()
    expect(customizeMenuItem).toHaveTextContent(/Customize Export/i)

    fireEvent.click(customizeMenuItem)

    const modal = await screen.findByTestId('export-customization-modal')
    expect(modal).toBeInTheDocument()
    expect(screen.getByText('Customize Queue Export')).toBeInTheDocument()
  })

  it('toggles column checkboxes and updates column selections with Select All and Deselect All', async () => {
    renderRefundQueueTable()
    await screen.findByText('ORD-1001')

    fireEvent.click(screen.getByTestId('export-dropdown-button'))
    fireEvent.click(screen.getByTestId('customize-export-menu-item'))

    await screen.findByTestId('export-customization-modal')

    const refundIdCheckbox = screen.getByTestId('column-checkbox-refund_id') as HTMLInputElement
    expect(refundIdCheckbox.checked).toBe(true)

    // Toggle off refund_id
    fireEvent.click(refundIdCheckbox)
    expect(refundIdCheckbox.checked).toBe(false)

    // Deselect All
    const deselectAllButton = screen.getByTestId('column-deselect-all')
    fireEvent.click(deselectAllButton)

    expect(refundIdCheckbox.checked).toBe(false)
    const orderIdCheckbox = screen.getByTestId('column-checkbox-order_id') as HTMLInputElement
    expect(orderIdCheckbox.checked).toBe(false)

    // Select All
    const selectAllButton = screen.getByTestId('column-select-all')
    fireEvent.click(selectAllButton)

    expect(refundIdCheckbox.checked).toBe(true)
    expect(orderIdCheckbox.checked).toBe(true)
  })

  it('reorders columns via Move Up and Move Down buttons', async () => {
    renderRefundQueueTable()
    await screen.findByText('ORD-1001')

    fireEvent.click(screen.getByTestId('export-dropdown-button'))
    fireEvent.click(screen.getByTestId('customize-export-menu-item'))

    await screen.findByTestId('export-customization-modal')

    // On initial default list, first item is refund_id
    const moveUpRefundId = screen.getByTestId('column-move-up-refund_id') as HTMLButtonElement
    const moveDownRefundId = screen.getByTestId('column-move-down-refund_id') as HTMLButtonElement

    expect(moveUpRefundId).toBeDisabled()
    expect(moveDownRefundId).not.toBeDisabled()

    // Move refund_id down
    fireEvent.click(moveDownRefundId)

    // Now refund_id is at index 1, so Move Up is enabled
    expect(screen.getByTestId('column-move-up-refund_id')).not.toBeDisabled()
    // and order_id is first item, so its move up is disabled
    expect(screen.getByTestId('column-move-up-order_id')).toBeDisabled()

    // Move refund_id back up
    fireEvent.click(screen.getByTestId('column-move-up-refund_id'))
    expect(screen.getByTestId('column-move-up-refund_id')).toBeDisabled()
  })

  it('applies "Accounting" and "Carrier Audit" presets correctly', async () => {
    renderRefundQueueTable()
    await screen.findByText('ORD-1001')

    fireEvent.click(screen.getByTestId('export-dropdown-button'))
    fireEvent.click(screen.getByTestId('customize-export-menu-item'))

    await screen.findByTestId('export-customization-modal')

    const presetSelect = screen.getByTestId('export-preset-select') as HTMLSelectElement

    // Select Accounting preset
    fireEvent.change(presetSelect, { target: { value: 'accounting' } })

    const refundIdCheckbox = screen.getByTestId('column-checkbox-refund_id') as HTMLInputElement
    const refundAmountCheckbox = screen.getByTestId('column-checkbox-refund_amount') as HTMLInputElement
    const categoryCheckbox = screen.getByTestId('column-checkbox-category') as HTMLInputElement
    const reasoningCheckbox = screen.getByTestId('column-checkbox-reasoning') as HTMLInputElement

    expect(refundIdCheckbox.checked).toBe(true)
    expect(refundAmountCheckbox.checked).toBe(true)
    expect(categoryCheckbox.checked).toBe(false)
    expect(reasoningCheckbox.checked).toBe(false)

    // Select Carrier Audit preset
    fireEvent.change(presetSelect, { target: { value: 'carrier_audit' } })

    expect(refundIdCheckbox.checked).toBe(true)
    expect(refundAmountCheckbox.checked).toBe(false)
    expect(categoryCheckbox.checked).toBe(true)
    expect(reasoningCheckbox.checked).toBe(true)

    // Reset to Default
    fireEvent.change(presetSelect, { target: { value: 'default' } })
    expect(refundAmountCheckbox.checked).toBe(true)
    expect(categoryCheckbox.checked).toBe(true)
  })

  it('disables export action buttons when 0 columns are selected', async () => {
    renderRefundQueueTable()
    await screen.findByText('ORD-1001')

    fireEvent.click(screen.getByTestId('export-dropdown-button'))
    fireEvent.click(screen.getByTestId('customize-export-menu-item'))

    await screen.findByTestId('export-customization-modal')

    const exportCsvBtn = screen.getByTestId('modal-export-csv') as HTMLButtonElement
    const exportJsonBtn = screen.getByTestId('modal-export-json') as HTMLButtonElement

    expect(exportCsvBtn).not.toBeDisabled()
    expect(exportJsonBtn).not.toBeDisabled()

    // Deselect all columns
    fireEvent.click(screen.getByTestId('column-deselect-all'))

    expect(exportCsvBtn).toBeDisabled()
    expect(exportJsonBtn).toBeDisabled()

    // Validation error message should be displayed
    const errorMsg = screen.getByTestId('column-validation-error')
    expect(errorMsg).toBeInTheDocument()
    expect(errorMsg).toHaveTextContent(/At least one column must be selected/i)
  })

  it('clicking export triggers CSV and JSON download with customized columns and closes modal', async () => {
    renderRefundQueueTable()
    await screen.findByText('ORD-1001')

    fireEvent.click(screen.getByTestId('export-dropdown-button'))
    fireEvent.click(screen.getByTestId('customize-export-menu-item'))

    await screen.findByTestId('export-customization-modal')

    // Select Accounting preset
    fireEvent.change(screen.getByTestId('export-preset-select'), { target: { value: 'accounting' } })

    // Click Export CSV
    fireEvent.click(screen.getByTestId('modal-export-csv'))

    // Verify browser file download trigger was called
    expect(clickSpy).toHaveBeenCalledTimes(1)

    // Verify modal is closed
    await waitFor(() => {
      expect(screen.queryByTestId('export-customization-modal')).not.toBeInTheDocument()
    })

    // Verify localStorage has persisted the customized columns
    const saved = localStorage.getItem(LOCAL_STORAGE_KEY)
    expect(saved).not.toBeNull()
    const parsed = JSON.parse(saved!)
    expect(parsed.selected).toEqual(
      expect.arrayContaining(['refund_id', 'order_id', 'refund_amount', 'status', 'decision', 'created_at'])
    )

    // Open modal again to export JSON
    fireEvent.click(screen.getByTestId('export-dropdown-button'))
    fireEvent.click(screen.getByTestId('customize-export-menu-item'))

    await screen.findByTestId('export-customization-modal')

    // Click Export JSON
    fireEvent.click(screen.getByTestId('modal-export-json'))
    expect(clickSpy).toHaveBeenCalledTimes(2)

    await waitFor(() => {
      expect(screen.queryByTestId('export-customization-modal')).not.toBeInTheDocument()
    })
  })
})
