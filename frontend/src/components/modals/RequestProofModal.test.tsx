import * as React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RequestProofModal } from './RequestProofModal'
import * as refundService from '@/services/refundService'
import { ApiError } from '@/services/apiClient'
import type { RefundRecord } from '@/types/api'

vi.mock('@/services/refundService', () => ({
  requestReviewerProof: vi.fn(),
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

const mockUpdatedRecord: RefundRecord = {
  refundId: 'ref-12345',
  orderId: 'ORD-9876',
  customerRequestText: 'Item missing accessories',
  status: 'awaiting_clarification',
  decision: 'escalate',
  confidenceScore: 0.5,
  category: 'missing_items',
  reasoning: 'Customer asked to supply photo of packaging and packing slip',
  createdAt: '2026-09-28T10:00:00Z',
  updatedAt: '2026-09-28T10:05:00Z',
} as unknown as RefundRecord

describe('RequestProofModal component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders modal dialog when isOpen is true and does not render when false', () => {
    const { rerender } = renderWithClient(
      <RequestProofModal
        refundId="ref-12345"
        orderId="ORD-9876"
        isOpen={false}
        onClose={vi.fn()}
      />
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    rerender(
      <QueryClientProvider client={createTestQueryClient()}>
        <RequestProofModal
          refundId="ref-12345"
          orderId="ORD-9876"
          isOpen={true}
          onClose={vi.fn()}
        />
      </QueryClientProvider>
    )

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('Request Customer Proof')).toBeInTheDocument()
    expect(screen.getByText('ORD-9876')).toBeInTheDocument()
  })

  it('renders informative guidance callout notifying reviewers of upload formats and workflow transition', () => {
    renderWithClient(
      <RequestProofModal
        refundId="ref-12345"
        orderId="ORD-9876"
        isOpen={true}
        onClose={vi.fn()}
      />
    )

    const callout = screen.getByTestId('proof-guidance-callout')
    expect(callout).toBeInTheDocument()
    expect(callout).toHaveTextContent(/JPEG, PNG, or WebP up to 5MB/i)
    expect(callout).toHaveTextContent(/awaiting_clarification/i)
    expect(callout).toHaveTextContent(/automatically resumes/i)
  })

  it('blocks submission and displays inline validation error when prompt is empty or whitespace only', () => {
    renderWithClient(
      <RequestProofModal
        refundId="ref-12345"
        isOpen={true}
        onClose={vi.fn()}
      />
    )

    const submitBtn = screen.getByRole('button', { name: /send request/i })

    // Empty submission
    fireEvent.click(submitBtn)
    expect(screen.getByTestId('prompt-error')).toHaveTextContent('Inquiry prompt is required')
    expect(refundService.requestReviewerProof).not.toHaveBeenCalled()

    // Whitespace only
    const textarea = screen.getByLabelText(/proof inquiry prompt/i)
    fireEvent.change(textarea, { target: { value: '   \n \t  ' } })
    fireEvent.click(submitBtn)

    expect(screen.getByTestId('prompt-error')).toHaveTextContent('Inquiry prompt is required')
    expect(refundService.requestReviewerProof).not.toHaveBeenCalled()

    // Typing non-whitespace clears validation error
    fireEvent.change(textarea, { target: { value: 'Please provide packaging photos.' } })
    expect(screen.queryByTestId('prompt-error')).not.toBeInTheDocument()
  })

  it('submits mutation without optional customer name, invalidates cache queries, invokes onSuccess, and closes modal', async () => {
    const onClose = vi.fn()
    const onSuccess = vi.fn()
    vi.mocked(refundService.requestReviewerProof).mockResolvedValueOnce(mockUpdatedRecord)

    const { client } = renderWithClient(
      <RequestProofModal
        refundId="ref-12345"
        orderId="ORD-9876"
        isOpen={true}
        onClose={onClose}
        onSuccess={onSuccess}
      />
    )

    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')

    const textarea = screen.getByLabelText(/proof inquiry prompt/i)
    fireEvent.change(textarea, {
      target: { value: 'Please upload a photo of the damaged parcel shipping label.' },
    })

    const submitBtn = screen.getByRole('button', { name: /send request/i })
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(refundService.requestReviewerProof).toHaveBeenCalledWith('ref-12345', {
        proofPrompt: 'Please upload a photo of the damaged parcel shipping label.',
        customerName: undefined,
      })
    })

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['refund', 'ref-12345'] })
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['refunds'] })
      expect(onSuccess).toHaveBeenCalledWith(mockUpdatedRecord)
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('submits mutation with optional customer name provided and trimmed', async () => {
    const onClose = vi.fn()
    const onSuccess = vi.fn()
    vi.mocked(refundService.requestReviewerProof).mockResolvedValueOnce(mockUpdatedRecord)

    renderWithClient(
      <RequestProofModal
        refundId="ref-12345"
        orderId="ORD-9876"
        isOpen={true}
        onClose={onClose}
        onSuccess={onSuccess}
      />
    )

    const nameInput = screen.getByLabelText(/customer name/i)
    fireEvent.change(nameInput, { target: { value: '  John Smith  ' } })

    const textarea = screen.getByLabelText(/proof inquiry prompt/i)
    fireEvent.change(textarea, {
      target: { value: 'Please provide proof of the shipping invoice.' },
    })

    const submitBtn = screen.getByRole('button', { name: /send request/i })
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(refundService.requestReviewerProof).toHaveBeenCalledWith('ref-12345', {
        proofPrompt: 'Please provide proof of the shipping invoice.',
        customerName: 'John Smith',
      })
    })
  })

  it('disables controls and displays loading spinner during in-flight mutation', async () => {
    let resolvePromise!: (val: RefundRecord) => void
    const pendingPromise = new Promise<RefundRecord>((resolve) => {
      resolvePromise = resolve
    })
    vi.mocked(refundService.requestReviewerProof).mockReturnValueOnce(pendingPromise)

    const onClose = vi.fn()

    renderWithClient(
      <RequestProofModal
        refundId="ref-12345"
        isOpen={true}
        onClose={onClose}
      />
    )

    const nameInput = screen.getByLabelText(/customer name/i)
    const textarea = screen.getByLabelText(/proof inquiry prompt/i)
    fireEvent.change(nameInput, { target: { value: 'Alice' } })
    fireEvent.change(textarea, { target: { value: 'Please upload photos' } })

    const submitBtn = screen.getByRole('button', { name: /send request/i })
    fireEvent.click(submitBtn)

    // While pending:
    await waitFor(() => {
      expect(submitBtn).toBeDisabled()
    })
    expect(screen.getByTestId('button-spinner')).toBeInTheDocument()

    const cancelBtn = screen.getByRole('button', { name: /cancel/i })
    expect(nameInput).toBeDisabled()
    expect(textarea).toBeDisabled()
    expect(cancelBtn).toBeDisabled()

    // Escape key should NOT close the modal while pending
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).not.toHaveBeenCalled()

    // Backdrop click should NOT close the modal while pending
    const backdrop = screen.getByTestId('dialog-backdrop')
    fireEvent.click(backdrop)
    expect(onClose).not.toHaveBeenCalled()

    // Resolve mutation
    resolvePromise(mockUpdatedRecord)

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('displays RFC 9457 ProblemDetails alert banner on mutation failure without closing modal or clearing inputs', async () => {
    const onClose = vi.fn()
    const apiError = new ApiError({
      type: 'https://api.refund-processor.local/problems/invalid-state',
      status: 400,
      title: 'Invalid State Transition',
      detail: 'Refund is not in an escalated status that allows requesting reviewer proof.',
    })
    vi.mocked(refundService.requestReviewerProof).mockRejectedValueOnce(apiError)

    renderWithClient(
      <RequestProofModal
        refundId="ref-12345"
        isOpen={true}
        onClose={onClose}
      />
    )

    const nameInput = screen.getByLabelText(/customer name/i)
    const textarea = screen.getByLabelText(/proof inquiry prompt/i)
    fireEvent.change(nameInput, { target: { value: 'Alice' } })
    fireEvent.change(textarea, { target: { value: 'Detailed proof inquiry' } })

    fireEvent.click(screen.getByRole('button', { name: /send request/i }))

    await waitFor(() => {
      expect(screen.getByTestId('request-proof-error-banner')).toBeInTheDocument()
    })

    expect(screen.getByText('Invalid State Transition')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Refund is not in an escalated status that allows requesting reviewer proof.'
      )
    ).toBeInTheDocument()

    // Modal did not close and inputs were preserved
    expect(onClose).not.toHaveBeenCalled()
    expect(nameInput).toHaveValue('Alice')
    expect(textarea).toHaveValue('Detailed proof inquiry')
  })

  it('closes cleanly and resets input values when clicking Cancel or pressing Escape when idle', () => {
    const onClose = vi.fn()

    const { rerender } = renderWithClient(
      <RequestProofModal
        refundId="ref-12345"
        isOpen={true}
        onClose={onClose}
      />
    )

    const nameInput = screen.getByLabelText(/customer name/i)
    const textarea = screen.getByLabelText(/proof inquiry prompt/i)
    fireEvent.change(nameInput, { target: { value: 'Temp Name' } })
    fireEvent.change(textarea, { target: { value: 'Temp inquiry' } })

    // Click cancel
    const cancelBtn = screen.getByRole('button', { name: /cancel/i })
    fireEvent.click(cancelBtn)
    expect(onClose).toHaveBeenCalledTimes(1)

    // Reopen modal - verify reset
    rerender(
      <QueryClientProvider client={createTestQueryClient()}>
        <RequestProofModal
          refundId="ref-12345"
          isOpen={true}
          onClose={onClose}
        />
      </QueryClientProvider>
    )

    expect(screen.getByLabelText(/customer name/i)).toHaveValue('')
    expect(screen.getByLabelText(/proof inquiry prompt/i)).toHaveValue('')

    // Press Escape key when idle
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(2)
  })
})
