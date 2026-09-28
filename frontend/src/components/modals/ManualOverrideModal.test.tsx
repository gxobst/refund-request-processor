import * as React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ManualOverrideModal } from './ManualOverrideModal'
import * as refundService from '@/services/refundService'
import { ApiError } from '@/services/apiClient'
import type { RefundRecord } from '@/types/api'

vi.mock('@/services/refundService', () => ({
  overrideRefundDecision: vi.fn(),
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
  customerRequestText: 'Item damaged during transport',
  status: 'completed',
  decision: 'approve',
  confidenceScore: 0.95,
  category: 'damaged',
  reasoning: 'Operator override applied',
  createdAt: '2026-09-28T10:00:00Z',
  updatedAt: '2026-09-28T10:05:00Z',
  overrideDecision: 'approve',
  overrideReason: 'Damaged item confirmed by customer photos.',
  overriddenAt: '2026-09-28T10:05:00Z',
} as unknown as RefundRecord

describe('ManualOverrideModal component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders modal dialog when isOpen is true and does not render when false', () => {
    const { rerender } = renderWithClient(
      <ManualOverrideModal
        refundId="ref-12345"
        orderId="ORD-9876"
        currentDecision="escalate"
        isOpen={false}
        onClose={vi.fn()}
      />
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    rerender(
      <QueryClientProvider client={createTestQueryClient()}>
        <ManualOverrideModal
          refundId="ref-12345"
          orderId="ORD-9876"
          currentDecision="escalate"
          isOpen={true}
          onClose={vi.fn()}
        />
      </QueryClientProvider>
    )

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('Manual Decision Override')).toBeInTheDocument()
    expect(screen.getByText('ORD-9876')).toBeInTheDocument()
    expect(screen.getByText('escalate')).toBeInTheDocument()
  })

  it('renders decision choice buttons and character counter', () => {
    renderWithClient(
      <ManualOverrideModal
        refundId="ref-12345"
        orderId="ORD-9876"
        isOpen={true}
        onClose={vi.fn()}
      />
    )

    const approveBtn = screen.getByRole('button', { name: /approve refund/i })
    const denyBtn = screen.getByRole('button', { name: /deny refund/i })
    expect(approveBtn).toBeInTheDocument()
    expect(denyBtn).toBeInTheDocument()

    // Default decision is approve
    expect(approveBtn).toHaveAttribute('aria-pressed', 'true')
    expect(denyBtn).toHaveAttribute('aria-pressed', 'false')

    // Click Deny Refund to switch choice
    fireEvent.click(denyBtn)
    expect(approveBtn).toHaveAttribute('aria-pressed', 'false')
    expect(denyBtn).toHaveAttribute('aria-pressed', 'true')

    // Character counter updates as user types
    const counter = screen.getByTestId('character-counter')
    expect(counter).toHaveTextContent('0 characters')

    const textarea = screen.getByLabelText(/override justification/i)
    fireEvent.change(textarea, { target: { value: 'Valid supervisor rationale' } })
    expect(counter).toHaveTextContent('26 characters')
  })

  it('blocks submission and displays inline validation error when justification is empty or whitespace only', () => {
    renderWithClient(
      <ManualOverrideModal
        refundId="ref-12345"
        isOpen={true}
        onClose={vi.fn()}
      />
    )

    const submitBtn = screen.getByRole('button', { name: /submit override/i })
    const checkbox = screen.getByLabelText(/i confirm this manual decision override/i)
    fireEvent.click(checkbox)

    // Attempt submission with empty justification
    fireEvent.click(submitBtn)
    expect(screen.getByTestId('justification-error')).toHaveTextContent(
      'Justification reason is required'
    )
    expect(refundService.overrideRefundDecision).not.toHaveBeenCalled()

    // Attempt submission with whitespace only
    const textarea = screen.getByLabelText(/override justification/i)
    fireEvent.change(textarea, { target: { value: '     \n  \t  ' } })
    fireEvent.click(submitBtn)

    expect(screen.getByTestId('justification-error')).toHaveTextContent(
      'Justification reason is required'
    )
    expect(refundService.overrideRefundDecision).not.toHaveBeenCalled()

    // Typing non-whitespace clears the validation error
    fireEvent.change(textarea, { target: { value: 'Valid reason' } })
    expect(screen.queryByTestId('justification-error')).not.toBeInTheDocument()
  })

  it('blocks submission if confirmation guard checkbox is not checked', async () => {
    renderWithClient(
      <ManualOverrideModal
        refundId="ref-12345"
        isOpen={true}
        onClose={vi.fn()}
      />
    )

    const textarea = screen.getByLabelText(/override justification/i)
    fireEvent.change(textarea, { target: { value: 'Exception approved due to VIP status' } })

    const submitBtn = screen.getByRole('button', { name: /submit override/i })
    fireEvent.click(submitBtn)

    expect(refundService.overrideRefundDecision).not.toHaveBeenCalled()
    expect(screen.getByTestId('confirmation-error')).toHaveTextContent(
      'Confirmation is required before submitting override'
    )

    // Checking the confirmation box and submitting proceeds
    vi.mocked(refundService.overrideRefundDecision).mockResolvedValueOnce(mockUpdatedRecord)
    const checkbox = screen.getByLabelText(/i confirm this manual decision override/i)
    fireEvent.click(checkbox)
    expect(screen.queryByTestId('confirmation-error')).not.toBeInTheDocument()

    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(refundService.overrideRefundDecision).toHaveBeenCalledTimes(1)
    })
  })

  it('submits mutation with correct payload, invalidates cache queries, invokes onSuccess, and closes modal', async () => {
    const onClose = vi.fn()
    const onSuccess = vi.fn()
    vi.mocked(refundService.overrideRefundDecision).mockResolvedValueOnce(mockUpdatedRecord)

    const { client } = renderWithClient(
      <ManualOverrideModal
        refundId="ref-12345"
        orderId="ORD-9876"
        currentDecision="escalate"
        isOpen={true}
        onClose={onClose}
        onSuccess={onSuccess}
      />
    )

    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')

    // Choose Deny
    fireEvent.click(screen.getByRole('button', { name: /deny refund/i }))

    // Enter justification
    const textarea = screen.getByLabelText(/override justification/i)
    fireEvent.change(textarea, {
      target: { value: 'Fraud indicators present on recipient address. Denying request.' },
    })

    // Check confirmation guard
    fireEvent.click(screen.getByLabelText(/i confirm this manual decision override/i))

    // Submit
    fireEvent.click(screen.getByRole('button', { name: /submit override/i }))

    await waitFor(() => {
      expect(refundService.overrideRefundDecision).toHaveBeenCalledWith('ref-12345', {
        overrideDecision: 'deny',
        overrideReason: 'Fraud indicators present on recipient address. Denying request.',
      })
    })

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['refund', 'ref-12345'] })
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['refunds'] })
      expect(onSuccess).toHaveBeenCalledWith(mockUpdatedRecord)
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('disables controls and displays loading spinner during in-flight mutation', async () => {
    let resolvePromise!: (val: RefundRecord) => void
    const pendingPromise = new Promise<RefundRecord>((resolve) => {
      resolvePromise = resolve
    })
    vi.mocked(refundService.overrideRefundDecision).mockReturnValueOnce(pendingPromise)

    const onClose = vi.fn()

    renderWithClient(
      <ManualOverrideModal
        refundId="ref-12345"
        isOpen={true}
        onClose={onClose}
      />
    )

    const textarea = screen.getByLabelText(/override justification/i)
    fireEvent.change(textarea, { target: { value: 'Overriding policy decision' } })
    fireEvent.click(screen.getByLabelText(/i confirm this manual decision override/i))

    const submitBtn = screen.getByRole('button', { name: /submit override/i })
    fireEvent.click(submitBtn)

    // While mutation is pending:
    await waitFor(() => {
      expect(submitBtn).toBeDisabled()
    })
    expect(screen.getByTestId('button-spinner')).toBeInTheDocument()

    const approveBtn = screen.getByRole('button', { name: /approve refund/i })
    const denyBtn = screen.getByRole('button', { name: /deny refund/i })
    const cancelBtn = screen.getByRole('button', { name: /cancel/i })
    const checkbox = screen.getByLabelText(/i confirm this manual decision override/i)

    expect(approveBtn).toBeDisabled()
    expect(denyBtn).toBeDisabled()
    expect(textarea).toBeDisabled()
    expect(checkbox).toBeDisabled()
    expect(cancelBtn).toBeDisabled()

    // Escape key should NOT close the modal while pending
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).not.toHaveBeenCalled()

    // Backdrop click should NOT close the modal while pending
    const backdrop = screen.getByTestId('dialog-backdrop')
    fireEvent.click(backdrop)
    expect(onClose).not.toHaveBeenCalled()

    // Resolve the mutation
    resolvePromise(mockUpdatedRecord)

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('displays RFC 9457 ProblemDetails alert banner on mutation failure without closing modal or clearing inputs', async () => {
    const onClose = vi.fn()
    const apiError = new ApiError({
      type: 'https://api.refund-processor.local/problems/conflict',
      status: 409,
      title: 'Conflict: Refund Already Resolved',
      detail: 'This refund request has already been finalized by another reviewer.',
    })
    vi.mocked(refundService.overrideRefundDecision).mockRejectedValueOnce(apiError)

    renderWithClient(
      <ManualOverrideModal
        refundId="ref-12345"
        isOpen={true}
        onClose={onClose}
      />
    )

    const textarea = screen.getByLabelText(/override justification/i)
    fireEvent.change(textarea, { target: { value: 'Critical supervisor justification' } })
    fireEvent.click(screen.getByLabelText(/i confirm this manual decision override/i))

    fireEvent.click(screen.getByRole('button', { name: /submit override/i }))

    await waitFor(() => {
      expect(screen.getByTestId('override-error-banner')).toBeInTheDocument()
    })

    expect(screen.getByText('Conflict: Refund Already Resolved')).toBeInTheDocument()
    expect(
      screen.getByText('This refund request has already been finalized by another reviewer.')
    ).toBeInTheDocument()

    // Modal did not close and input was not wiped
    expect(onClose).not.toHaveBeenCalled()
    expect(textarea).toHaveValue('Critical supervisor justification')
  })

  it('closes cleanly and resets inputs when clicking Cancel or pressing Escape when idle', () => {
    const onClose = vi.fn()

    const { rerender } = renderWithClient(
      <ManualOverrideModal
        refundId="ref-12345"
        isOpen={true}
        onClose={onClose}
      />
    )

    const textarea = screen.getByLabelText(/override justification/i)
    fireEvent.change(textarea, { target: { value: 'Unsaved note' } })
    fireEvent.click(screen.getByLabelText(/i confirm this manual decision override/i))

    // Click cancel button
    const cancelBtn = screen.getByRole('button', { name: /cancel/i })
    fireEvent.click(cancelBtn)
    expect(onClose).toHaveBeenCalledTimes(1)

    // Reopen modal - verify fields were reset
    rerender(
      <QueryClientProvider client={createTestQueryClient()}>
        <ManualOverrideModal
          refundId="ref-12345"
          isOpen={true}
          onClose={onClose}
        />
      </QueryClientProvider>
    )

    expect(screen.getByLabelText(/override justification/i)).toHaveValue('')
    expect(screen.getByLabelText(/i confirm this manual decision override/i)).not.toBeChecked()

    // Press Escape key when idle
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(2)
  })
})
