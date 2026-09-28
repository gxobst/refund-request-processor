import * as React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CreateRefundModal } from './CreateRefundModal'
import * as refundService from '@/services/refundService'
import { ApiError } from '@/services/apiClient'
import type { RefundCreateResponse } from '@/types/api'

vi.mock('@/services/refundService', () => ({
  submitRefund: vi.fn(),
}))

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  })
}

function renderWithClient(ui: React.ReactElement, client = createTestQueryClient()) {
  return {
    ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>),
    client,
  }
}

const mockCreateResponse: RefundCreateResponse = {
  refundId: 'ref-new-1001',
  orderId: 'ORD-1001',
  status: 'pending',
  createdAt: '2026-09-28T10:00:00Z',
} as unknown as RefundCreateResponse

describe('CreateRefundModal component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders modal dialog when isOpen is true and does not render when false', () => {
    const { rerender } = renderWithClient(
      <CreateRefundModal isOpen={false} onClose={vi.fn()} />
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    rerender(
      <QueryClientProvider client={createTestQueryClient()}>
        <CreateRefundModal isOpen={true} onClose={vi.fn()} />
      </QueryClientProvider>
    )

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('Submit Refund Request')).toBeInTheDocument()
    expect(screen.getByLabelText(/order id/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/customer request text/i)).toBeInTheDocument()
  })

  it('validates Order ID against regex pattern ^ORD-\\d{4}$ on blur and submission', () => {
    renderWithClient(<CreateRefundModal isOpen={true} onClose={vi.fn()} />)

    const orderInput = screen.getByLabelText(/order id/i)

    // Invalid format on blur
    fireEvent.change(orderInput, { target: { value: 'INVALID-123' } })
    fireEvent.blur(orderInput)
    expect(screen.getByTestId('order-id-error')).toHaveTextContent(
      'Order ID must follow the pattern ORD-#### (e.g. ORD-1001)'
    )

    // Another invalid pattern (3 digits instead of 4)
    fireEvent.change(orderInput, { target: { value: 'ORD-123' } })
    fireEvent.blur(orderInput)
    expect(screen.getByTestId('order-id-error')).toBeInTheDocument()

    // Valid pattern clears error
    fireEvent.change(orderInput, { target: { value: 'ORD-5432' } })
    fireEvent.blur(orderInput)
    expect(screen.queryByTestId('order-id-error')).not.toBeInTheDocument()
  })

  it('blocks submission and displays inline error when explanation is empty or whitespace only', () => {
    renderWithClient(<CreateRefundModal isOpen={true} onClose={vi.fn()} />)

    const orderInput = screen.getByLabelText(/order id/i)
    fireEvent.change(orderInput, { target: { value: 'ORD-1001' } })

    const submitBtn = screen.getByRole('button', { name: /submit refund/i })

    // Submit with empty explanation
    fireEvent.click(submitBtn)
    expect(screen.getByTestId('explanation-error')).toHaveTextContent(
      'Customer explanation is required'
    )
    expect(refundService.submitRefund).not.toHaveBeenCalled()

    // Submit with whitespace only
    const textarea = screen.getByLabelText(/customer request text/i)
    fireEvent.change(textarea, { target: { value: '    \n  \t  ' } })
    fireEvent.click(submitBtn)

    expect(screen.getByTestId('explanation-error')).toHaveTextContent(
      'Customer explanation is required'
    )
    expect(refundService.submitRefund).not.toHaveBeenCalled()

    // Typing non-whitespace clears error
    fireEvent.change(textarea, { target: { value: 'Item arrived shattered.' } })
    expect(screen.queryByTestId('explanation-error')).not.toBeInTheDocument()
  })

  it('validates file size limit (5MB) and rejects oversized files', () => {
    renderWithClient(<CreateRefundModal isOpen={true} onClose={vi.fn()} />)

    const fileInput = screen.getByTestId('file-picker-input')
    const oversizedFile = new File(['x'.repeat(6 * 1024 * 1024)], 'huge-proof.jpg', {
      type: 'image/jpeg',
    })

    fireEvent.change(fileInput, { target: { files: [oversizedFile] } })

    expect(screen.getByTestId('file-error')).toHaveTextContent('File exceeds 5MB size limit')
    expect(screen.queryByTestId('selected-file-badge')).not.toBeInTheDocument()
  })

  it('validates MIME type and rejects unsupported file formats', () => {
    renderWithClient(<CreateRefundModal isOpen={true} onClose={vi.fn()} />)

    const fileInput = screen.getByTestId('file-picker-input')
    const unsupportedFile = new File(['fake content'], 'contract.pdf', {
      type: 'application/pdf',
    })

    fireEvent.change(fileInput, { target: { files: [unsupportedFile] } })

    expect(screen.getByTestId('file-error')).toHaveTextContent(
      'Unsupported file format. Please upload a JPEG, PNG, or WebP image'
    )
    expect(screen.queryByTestId('selected-file-badge')).not.toBeInTheDocument()
  })

  it('supports drag-and-drop file upload, displays file details, and allows file removal', () => {
    renderWithClient(<CreateRefundModal isOpen={true} onClose={vi.fn()} />)

    const dropzone = screen.getByTestId('file-dropzone')
    const validFile = new File(['valid image bytes'], 'broken-screen.png', {
      type: 'image/png',
    })

    // Drag over and drag leave
    fireEvent.dragOver(dropzone)
    fireEvent.dragLeave(dropzone)

    // Drop file
    fireEvent.drop(dropzone, {
      dataTransfer: {
        files: [validFile],
      },
    })

    expect(screen.getByTestId('selected-file-badge')).toBeInTheDocument()
    expect(screen.getByTestId('selected-file-name')).toHaveTextContent('broken-screen.png')
    expect(screen.getByTestId('selected-file-size')).toBeInTheDocument()

    // Remove file
    const removeBtn = screen.getByTestId('remove-file-button')
    fireEvent.click(removeBtn)

    expect(screen.queryByTestId('selected-file-badge')).not.toBeInTheDocument()
    expect(screen.getByTestId('file-dropzone')).toBeInTheDocument()
  })

  it('submits refund request without file attachment using JSON parameters', async () => {
    const onClose = vi.fn()
    const onSuccess = vi.fn()
    vi.mocked(refundService.submitRefund).mockResolvedValueOnce(mockCreateResponse)

    const { client } = renderWithClient(
      <CreateRefundModal isOpen={true} onClose={onClose} onSuccess={onSuccess} />
    )

    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')

    const orderInput = screen.getByLabelText(/order id/i)
    fireEvent.change(orderInput, { target: { value: 'ORD-1001' } })

    const textarea = screen.getByLabelText(/customer request text/i)
    fireEvent.change(textarea, {
      target: { value: 'Item arrived two weeks late and customer requests full refund.' },
    })

    const submitBtn = screen.getByRole('button', { name: /submit refund/i })
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(refundService.submitRefund).toHaveBeenCalledWith({
        orderId: 'ORD-1001',
        customerRequestText: 'Item arrived two weeks late and customer requests full refund.',
        file: null,
      })
    })

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['refunds'] })
      expect(onSuccess).toHaveBeenCalledWith(mockCreateResponse)
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('submits refund request with valid image file attachment', async () => {
    const onClose = vi.fn()
    const onSuccess = vi.fn()
    vi.mocked(refundService.submitRefund).mockResolvedValueOnce(mockCreateResponse)

    renderWithClient(<CreateRefundModal isOpen={true} onClose={onClose} onSuccess={onSuccess} />)

    const orderInput = screen.getByLabelText(/order id/i)
    fireEvent.change(orderInput, { target: { value: 'ORD-2024' } })

    const textarea = screen.getByLabelText(/customer request text/i)
    fireEvent.change(textarea, {
      target: { value: 'Package arrived with water damage to interior electronics.' },
    })

    const fileInput = screen.getByTestId('file-picker-input')
    const validFile = new File(['test image data'], 'damaged_item.webp', {
      type: 'image/webp',
    })
    fireEvent.change(fileInput, { target: { files: [validFile] } })

    const submitBtn = screen.getByRole('button', { name: /submit refund/i })
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(refundService.submitRefund).toHaveBeenCalledWith({
        orderId: 'ORD-2024',
        customerRequestText: 'Package arrived with water damage to interior electronics.',
        file: validFile,
      })
    })

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalledWith(mockCreateResponse)
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('disables controls and displays loading spinner during in-flight submission', async () => {
    let resolvePromise!: (val: RefundCreateResponse) => void
    const pendingPromise = new Promise<RefundCreateResponse>((resolve) => {
      resolvePromise = resolve
    })
    vi.mocked(refundService.submitRefund).mockReturnValueOnce(pendingPromise)

    const onClose = vi.fn()

    renderWithClient(<CreateRefundModal isOpen={true} onClose={onClose} />)

    const orderInput = screen.getByLabelText(/order id/i)
    const textarea = screen.getByLabelText(/customer request text/i)
    fireEvent.change(orderInput, { target: { value: 'ORD-7777' } })
    fireEvent.change(textarea, { target: { value: 'Defective product upon delivery.' } })

    const submitBtn = screen.getByRole('button', { name: /submit refund/i })
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(submitBtn).toBeDisabled()
    })
    expect(screen.getByTestId('button-spinner')).toBeInTheDocument()

    const cancelBtn = screen.getByRole('button', { name: /cancel/i })
    expect(orderInput).toBeDisabled()
    expect(textarea).toBeDisabled()
    expect(cancelBtn).toBeDisabled()

    // Escape key should NOT close the modal while pending
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).not.toHaveBeenCalled()

    // Backdrop click should NOT close the modal while pending
    const backdrop = screen.getByTestId('dialog-backdrop')
    fireEvent.click(backdrop)
    expect(onClose).not.toHaveBeenCalled()

    // Resolve
    resolvePromise(mockCreateResponse)

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('displays RFC 9457 ProblemDetails alert banner on mutation failure without closing modal or clearing inputs', async () => {
    const onClose = vi.fn()
    const apiError = new ApiError({
      type: 'https://api.refund-processor.local/problems/duplicate-order',
      status: 409,
      title: 'Order Conflict',
      detail: 'A refund evaluation for this Order ID is already processing or completed.',
    })
    vi.mocked(refundService.submitRefund).mockRejectedValueOnce(apiError)

    renderWithClient(<CreateRefundModal isOpen={true} onClose={onClose} />)

    const orderInput = screen.getByLabelText(/order id/i)
    const textarea = screen.getByLabelText(/customer request text/i)
    fireEvent.change(orderInput, { target: { value: 'ORD-9999' } })
    fireEvent.change(textarea, { target: { value: 'Duplicate request test' } })

    fireEvent.click(screen.getByRole('button', { name: /submit refund/i }))

    await waitFor(() => {
      expect(screen.getByTestId('create-refund-error-banner')).toBeInTheDocument()
    })

    expect(screen.getByText('Order Conflict')).toBeInTheDocument()
    expect(
      screen.getByText('A refund evaluation for this Order ID is already processing or completed.')
    ).toBeInTheDocument()

    // Modal remains open and values remain intact
    expect(onClose).not.toHaveBeenCalled()
    expect(orderInput).toHaveValue('ORD-9999')
    expect(textarea).toHaveValue('Duplicate request test')
  })

  it('closes cleanly and resets input values when clicking Cancel or pressing Escape when idle', () => {
    const onClose = vi.fn()

    const { rerender } = renderWithClient(<CreateRefundModal isOpen={true} onClose={onClose} />)

    const orderInput = screen.getByLabelText(/order id/i)
    const textarea = screen.getByLabelText(/customer request text/i)
    fireEvent.change(orderInput, { target: { value: 'ORD-1234' } })
    fireEvent.change(textarea, { target: { value: 'Unfinished description' } })

    // Click cancel
    const cancelBtn = screen.getByRole('button', { name: /cancel/i })
    fireEvent.click(cancelBtn)
    expect(onClose).toHaveBeenCalledTimes(1)

    // Reopen modal - verify reset
    rerender(
      <QueryClientProvider client={createTestQueryClient()}>
        <CreateRefundModal isOpen={true} onClose={onClose} />
      </QueryClientProvider>
    )

    expect(screen.getByLabelText(/order id/i)).toHaveValue('')
    expect(screen.getByLabelText(/customer request text/i)).toHaveValue('')

    // Press Escape key when idle
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(2)
  })
})
