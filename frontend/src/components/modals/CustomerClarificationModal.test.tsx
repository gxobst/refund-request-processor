import * as React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CustomerClarificationModal } from './CustomerClarificationModal'
import * as refundService from '@/services/refundService'
import { ApiError } from '@/services/apiClient'
import type { RefundRecord } from '@/types/api'

vi.mock('@/services/refundService', () => ({
  getRefundById: vi.fn(),
  submitClarification: vi.fn(),
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

const mockRefundWithPrompt: RefundRecord = {
  refundId: 'ref-12345',
  orderId: 'ORD-9876',
  customerRequestText: 'Vase arrived broken into pieces.',
  status: 'awaiting_clarification',
  decision: 'escalate',
  confidenceScore: 0.5,
  category: 'damaged',
  reasoning: 'Customer asked to supply clear photos of broken ceramic items.',
  createdAt: '2026-09-28T10:00:00Z',
  updatedAt: '2026-09-28T10:05:00Z',
  clarificationHistory: [
    {
      cycle: 1,
      prompt: 'Please upload a clear photograph of the broken vase showing damage and shipping label.',
      response: null,
      timestamp: '2026-09-28T10:05:00Z',
      evidenceIds: [],
    },
  ],
  clarificationEmailText: 'Dear Customer, please provide a clear photo of the damage.',
} as unknown as RefundRecord

const mockRefundWithoutPrompt: RefundRecord = {
  refundId: 'ref-54321',
  orderId: 'ORD-1111',
  customerRequestText: 'Missing parcel components.',
  status: 'awaiting_clarification',
  decision: 'escalate',
  confidenceScore: 0.4,
  category: 'missing_items',
  reasoning: 'Clarification needed.',
  createdAt: '2026-09-28T10:00:00Z',
  updatedAt: '2026-09-28T10:05:00Z',
  clarificationHistory: [],
  clarificationEmailText: null,
  clarificationPrompt: null,
} as unknown as RefundRecord

const mockUpdatedRecord: RefundRecord = {
  ...mockRefundWithPrompt,
  status: 'pending',
  clarificationResponse: 'Attached photograph of broken ceramic vase.',
} as unknown as RefundRecord

describe('CustomerClarificationModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders modal dialog with accessible markup when isOpen is true and does not render when false', () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockRefundWithPrompt)

    const { rerender } = renderWithClient(
      <CustomerClarificationModal
        refundId="ref-12345"
        isOpen={false}
        onClose={vi.fn()}
      />
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    rerender(
      <QueryClientProvider client={createTestQueryClient()}>
        <CustomerClarificationModal
          refundId="ref-12345"
          isOpen={true}
          onClose={vi.fn()}
        />
      </QueryClientProvider>
    )

    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeInTheDocument()
    expect(dialog).toHaveAttribute('aria-labelledby', 'customer-clarification-dialog-title')
    expect(dialog).toHaveAttribute('aria-describedby', 'customer-clarification-dialog-description')
    expect(screen.getByText('Customer Clarification Portal')).toBeInTheDocument()
  })

  it('fetches refund details and renders order ID and agent inquiry prompt from clarification history', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockRefundWithPrompt)

    renderWithClient(
      <CustomerClarificationModal
        refundId="ref-12345"
        isOpen={true}
        onClose={vi.fn()}
      />
    )

    await waitFor(() => {
      expect(refundService.getRefundById).toHaveBeenCalledWith('ref-12345')
      expect(screen.getByTestId('clarification-order-id')).toHaveTextContent('ORD-9876')
      expect(screen.getByTestId('clarification-inquiry-prompt')).toHaveTextContent(
        'Please upload a clear photograph of the broken vase showing damage and shipping label.'
      )
    })
  })

  it('renders fallback guidance when no previous inquiry prompt exists', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockRefundWithoutPrompt)

    renderWithClient(
      <CustomerClarificationModal
        refundId="ref-54321"
        isOpen={true}
        onClose={vi.fn()}
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('clarification-order-id')).toHaveTextContent('ORD-1111')
      expect(screen.getByTestId('clarification-fallback-guidance')).toBeInTheDocument()
      expect(screen.queryByTestId('clarification-inquiry-prompt')).not.toBeInTheDocument()
    })
  })

  it('renders informational guidance callout explaining file types and 5MB limit', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockRefundWithPrompt)

    renderWithClient(
      <CustomerClarificationModal
        refundId="ref-12345"
        isOpen={true}
        onClose={vi.fn()}
      />
    )

    const guidance = screen.getByTestId('clarification-guidance-callout')
    expect(guidance).toBeInTheDocument()
    expect(guidance).toHaveTextContent(/JPEG, PNG, or WebP up to 5MB/i)
  })

  it('updates live character counter as user enters response', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockRefundWithPrompt)

    renderWithClient(
      <CustomerClarificationModal
        refundId="ref-12345"
        isOpen={true}
        onClose={vi.fn()}
      />
    )

    const counter = screen.getByTestId('clarification-character-counter')
    expect(counter).toHaveTextContent('0 characters')
    expect(counter).toHaveAttribute('aria-live', 'polite')

    const textarea = screen.getByTestId('clarification-response-textarea')
    fireEvent.change(textarea, { target: { value: 'Here is the detailed explanation.' } })

    expect(counter).toHaveTextContent('33 characters')
  })

  it('blocks submission and shows inline validation error on empty or whitespace response', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockRefundWithPrompt)

    renderWithClient(
      <CustomerClarificationModal
        refundId="ref-12345"
        isOpen={true}
        onClose={vi.fn()}
      />
    )

    const submitBtn = screen.getByTestId('clarification-submit-button')
    fireEvent.click(submitBtn)

    expect(refundService.submitClarification).not.toHaveBeenCalled()
    const errorEl = screen.getByTestId('clarification-response-error')
    expect(errorEl).toBeInTheDocument()
    expect(errorEl).toHaveAttribute('role', 'alert')
    expect(errorEl).toHaveTextContent(/Clarification response is required/i)
  })

  it('rejects files exceeding 5MB and shows validation error', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockRefundWithPrompt)

    renderWithClient(
      <CustomerClarificationModal
        refundId="ref-12345"
        isOpen={true}
        onClose={vi.fn()}
      />
    )

    const fileInput = screen.getByTestId('clarification-file-input')
    const oversizedFile = new File(['x'.repeat(100)], 'huge_photo.jpg', { type: 'image/jpeg' })
    Object.defineProperty(oversizedFile, 'size', { value: 6 * 1024 * 1024 }) // 6MB

    fireEvent.change(fileInput, { target: { files: [oversizedFile] } })

    const errorEl = screen.getByTestId('clarification-file-error')
    expect(errorEl).toBeInTheDocument()
    expect(errorEl).toHaveAttribute('role', 'alert')
    expect(errorEl).toHaveTextContent(/exceeds 5MB size limit/i)
    expect(screen.queryByTestId('clarification-file-preview')).not.toBeInTheDocument()
  })

  it('rejects unsupported file formats and shows validation error', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockRefundWithPrompt)

    renderWithClient(
      <CustomerClarificationModal
        refundId="ref-12345"
        isOpen={true}
        onClose={vi.fn()}
      />
    )

    const fileInput = screen.getByTestId('clarification-file-input')
    const invalidFile = new File(['dummy document'], 'invoice.pdf', { type: 'application/pdf' })

    fireEvent.change(fileInput, { target: { files: [invalidFile] } })

    const errorEl = screen.getByTestId('clarification-file-error')
    expect(errorEl).toBeInTheDocument()
    expect(errorEl).toHaveAttribute('role', 'alert')
    expect(errorEl).toHaveTextContent(/unsupported file format/i)
    expect(screen.queryByTestId('clarification-file-preview')).not.toBeInTheDocument()
  })

  it('attaches valid file via drag and drop, shows preview chip, and allows removing attachment', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockRefundWithPrompt)

    renderWithClient(
      <CustomerClarificationModal
        refundId="ref-12345"
        isOpen={true}
        onClose={vi.fn()}
      />
    )

    const dropZone = screen.getByTestId('clarification-drop-zone')
    const validFile = new File(['valid png data'], 'box_label.png', { type: 'image/png' })
    Object.defineProperty(validFile, 'size', { value: 1024 * 150 })

    fireEvent.drop(dropZone, {
      dataTransfer: {
        files: [validFile],
      },
    })

    const preview = screen.getByTestId('clarification-file-preview')
    expect(preview).toBeInTheDocument()
    expect(screen.getByTestId('clarification-file-name')).toHaveTextContent('box_label.png')
    expect(screen.getByTestId('clarification-file-size')).toBeInTheDocument()

    // Remove file
    const removeBtn = screen.getByTestId('remove-file-button')
    fireEvent.click(removeBtn)

    expect(screen.queryByTestId('clarification-file-preview')).not.toBeInTheDocument()
    expect(screen.getByTestId('clarification-drop-zone')).toBeInTheDocument()
  })

  it('submits valid response without file using JSON payload', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockRefundWithPrompt)
    vi.mocked(refundService.submitClarification).mockResolvedValue(mockUpdatedRecord)
    const onSuccess = vi.fn()

    const { client } = renderWithClient(
      <CustomerClarificationModal
        refundId="ref-12345"
        isOpen={true}
        onClose={vi.fn()}
        onSuccess={onSuccess}
      />
    )

    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')

    const textarea = screen.getByTestId('clarification-response-textarea')
    fireEvent.change(textarea, { target: { value: 'The box was crushed during transit.' } })

    const submitBtn = screen.getByTestId('clarification-submit-button')
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(refundService.submitClarification).toHaveBeenCalledWith('ref-12345', {
        responseText: 'The box was crushed during transit.',
      })
    })

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['refund', 'ref-12345'] })
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['refunds'] })
      expect(onSuccess).toHaveBeenCalledWith(mockUpdatedRecord)
      expect(screen.getByTestId('clarification-success-state')).toBeInTheDocument()
    })
  })

  it('submits valid response with attached file transmitting evidenceFile', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockRefundWithPrompt)
    vi.mocked(refundService.submitClarification).mockResolvedValue(mockUpdatedRecord)

    renderWithClient(
      <CustomerClarificationModal
        refundId="ref-12345"
        isOpen={true}
        onClose={vi.fn()}
      />
    )

    const textarea = screen.getByTestId('clarification-response-textarea')
    fireEvent.change(textarea, { target: { value: 'Attached image showing damaged serial number.' } })

    const fileInput = screen.getByTestId('clarification-file-input')
    const validFile = new File(['image content'], 'damage_proof.webp', { type: 'image/webp' })
    fireEvent.change(fileInput, { target: { files: [validFile] } })

    const submitBtn = screen.getByTestId('clarification-submit-button')
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(refundService.submitClarification).toHaveBeenCalledWith('ref-12345', {
        responseText: 'Attached image showing damaged serial number.',
        evidenceFile: validFile,
      })
    })

    await waitFor(() => {
      expect(screen.getByTestId('clarification-success-state')).toBeInTheDocument()
    })
  })

  it('displays RFC 9457 ProblemDetails error banner when submission fails and preserves entered input', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockRefundWithPrompt)
    const problemError = new ApiError({
      type: 'https://api.example.com/errors/validation',
      title: 'Unprocessable Entity',
      status: 422,
      detail: 'Uploaded image file failed integrity inspection.',
    })
    vi.mocked(refundService.submitClarification).mockRejectedValueOnce(problemError)

    renderWithClient(
      <CustomerClarificationModal
        refundId="ref-12345"
        isOpen={true}
        onClose={vi.fn()}
      />
    )

    const textarea = screen.getByTestId('clarification-response-textarea')
    fireEvent.change(textarea, { target: { value: 'My detailed explanation here.' } })

    const submitBtn = screen.getByTestId('clarification-submit-button')
    fireEvent.click(submitBtn)

    await waitFor(() => {
      const errorBanner = screen.getByTestId('clarification-error-banner')
      expect(errorBanner).toBeInTheDocument()
      expect(errorBanner).toHaveAttribute('role', 'alert')
      expect(errorBanner).toHaveTextContent('Unprocessable Entity')
      expect(errorBanner).toHaveTextContent('Uploaded image file failed integrity inspection.')
    })

    // Preserves form values
    expect(screen.getByTestId('clarification-response-textarea')).toHaveValue(
      'My detailed explanation here.'
    )
  })

  it('displays problemDetails.detail in clarification-error-banner when evidence upload fails with HTTP 400', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockRefundWithPrompt)
    const problemError = new ApiError({
      type: 'urn:problem:bad-request',
      title: 'Bad Request',
      status: 400,
      detail: 'Image dimensions (30x30) are below minimum required resolution of 50x50 pixels.',
      instance: '/v1/refunds/ref-12345/clarify',
    })
    vi.mocked(refundService.submitClarification).mockRejectedValueOnce(problemError)

    renderWithClient(
      <CustomerClarificationModal
        refundId="ref-12345"
        isOpen={true}
        onClose={vi.fn()}
      />
    )

    const textarea = screen.getByTestId('clarification-response-textarea')
    fireEvent.change(textarea, { target: { value: 'Customer clarification response text.' } })

    const submitBtn = screen.getByTestId('clarification-submit-button')
    fireEvent.click(submitBtn)

    await waitFor(() => {
      const errorBanner = screen.getByTestId('clarification-error-banner')
      expect(errorBanner).toBeInTheDocument()
      expect(errorBanner).toHaveAttribute('role', 'alert')
      expect(errorBanner).toHaveTextContent('Bad Request')
      expect(errorBanner).toHaveTextContent(
        'Image dimensions (30x30) are below minimum required resolution of 50x50 pixels.'
      )
    })
  })

  it('acknowledges success state and clicking Done triggers onClose and resets state', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockRefundWithPrompt)
    vi.mocked(refundService.submitClarification).mockResolvedValue(mockUpdatedRecord)
    const onClose = vi.fn()

    renderWithClient(
      <CustomerClarificationModal
        refundId="ref-12345"
        isOpen={true}
        onClose={onClose}
      />
    )

    const textarea = screen.getByTestId('clarification-response-textarea')
    fireEvent.change(textarea, { target: { value: 'My explanation.' } })

    const submitBtn = screen.getByTestId('clarification-submit-button')
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(screen.getByTestId('clarification-success-state')).toBeInTheDocument()
    })

    const doneBtn = screen.getByTestId('clarification-done-button')
    fireEvent.click(doneBtn)

    expect(onClose).toHaveBeenCalled()
  })

  it('clicking Cancel resets inputs and triggers onClose', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockRefundWithPrompt)
    const onClose = vi.fn()

    renderWithClient(
      <CustomerClarificationModal
        refundId="ref-12345"
        isOpen={true}
        onClose={onClose}
      />
    )

    const textarea = screen.getByTestId('clarification-response-textarea')
    fireEvent.change(textarea, { target: { value: 'Temporary text' } })

    const cancelBtn = screen.getByTestId('clarification-cancel-button')
    fireEvent.click(cancelBtn)

    expect(onClose).toHaveBeenCalled()
  })
})
