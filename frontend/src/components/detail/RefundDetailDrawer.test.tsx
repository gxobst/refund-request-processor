import * as React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RefundDetailDrawer } from './RefundDetailDrawer'
import * as refundService from '@/services/refundService'
import type { RefundRecord } from '@/types/api'

vi.mock('@/services/refundService', () => ({
  getRefundById: vi.fn(),
}))

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
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

const mockDetailRecord: RefundRecord = {
  refundId: 'ref-12345',
  orderId: 'ORD-9876',
  customerRequestText: 'Vase arrived shattered into pieces inside shipping box.',
  status: 'completed',
  decision: 'auto_approve',
  confidenceScore: 0.96,
  category: 'damaged',
  reasoning: 'Category damaged meets 30-day window rule. Refund auto-approved.',
  createdAt: '2026-09-28T10:00:00Z',
  updatedAt: '2026-09-28T10:01:00Z',
  matchedPolicyRule: {
    policyName: 'standard_30_day_damaged',
    action: 'auto_approve',
    returnRequired: false,
  },
  approvalEmailText: 'Dear Customer, your refund of $85.50 has been approved.',
  denialEmailText: null,
  clarificationEmailText: null,
} as unknown as RefundRecord

const mockOverriddenRecord: RefundRecord = {
  refundId: 'ref-99999',
  orderId: 'ORD-5555',
  customerRequestText: 'High priority customer inquiry.',
  status: 'escalated',
  decision: 'escalate',
  confidenceScore: 0.45,
  category: 'late_delivery',
  reasoning: 'Order was high amount and exceeded automatic approval threshold.',
  overrideDecision: 'approve',
  overrideReason: 'Approved as a one-time customer courtesy by supervisor.',
  overriddenAt: '2026-09-28T12:00:00Z',
  createdAt: '2026-09-28T11:00:00Z',
  updatedAt: '2026-09-28T12:00:00Z',
  matchedPolicyRule: {
    policyName: 'standard_late_delivery',
    action: 'manual_review',
    returnRequired: false,
  },
  denialEmailText: 'Your refund request has been denied per policy.',
} as unknown as RefundRecord

describe('RefundDetailDrawer component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does not render content when isOpen is false', () => {
    renderWithClient(
      <RefundDetailDrawer refundId="ref-12345" isOpen={false} onClose={vi.fn()} />
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByTestId('detail-refund-id')).not.toBeInTheDocument()
  })

  it('renders drawer and calls onClose on Escape key, close button, and backdrop click', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockDetailRecord)
    const handleClose = vi.fn()

    renderWithClient(
      <RefundDetailDrawer refundId="ref-12345" isOpen={true} onClose={handleClose} />
    )

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })

    // 1. Escape key
    fireEvent.keyDown(document, { key: 'Escape', code: 'Escape' })
    expect(handleClose).toHaveBeenCalledTimes(1)

    // 2. Close button
    const closeBtn = screen.getByTestId('drawer-close-button')
    fireEvent.click(closeBtn)
    expect(handleClose).toHaveBeenCalledTimes(2)

    // 3. Backdrop click
    const backdrop = screen.getByTestId('drawer-backdrop')
    fireEvent.click(backdrop)
    expect(handleClose).toHaveBeenCalledTimes(3)
  })

  it('renders loading skeleton while query is resolving', () => {
    vi.mocked(refundService.getRefundById).mockReturnValue(new Promise(() => {}))

    renderWithClient(
      <RefundDetailDrawer refundId="ref-12345" isOpen={true} onClose={vi.fn()} />
    )

    expect(screen.getByTestId('detail-loading-skeleton')).toBeInTheDocument()
  })

  it('renders all inspection sections: header, intake, classification, policy check, reasoning, and email previews', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockDetailRecord)

    renderWithClient(
      <RefundDetailDrawer refundId="ref-12345" isOpen={true} onClose={vi.fn()}>
        <div data-testid="test-child-slot">Evidence Gallery Extension</div>
      </RefundDetailDrawer>
    )

    await waitFor(() => {
      expect(screen.getByTestId('detail-refund-id')).toHaveTextContent('ref-12345')
      expect(screen.getByText(/Order ORD-9876/i)).toBeInTheDocument()
    })

    // Header badges
    expect(screen.getAllByText('Completed').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('Auto Approved')).toBeInTheDocument()

    // Customer Intake
    expect(screen.getByTestId('section-customer-intake')).toBeInTheDocument()
    expect(
      screen.getByText(/Vase arrived shattered into pieces inside shipping box/i)
    ).toBeInTheDocument()

    // Classification
    expect(screen.getByTestId('section-classification')).toBeInTheDocument()
    expect(screen.getByText('damaged')).toBeInTheDocument()
    expect(screen.getByText('96%')).toBeInTheDocument()

    // Policy Rule Validation
    expect(screen.getByTestId('section-policy-check')).toBeInTheDocument()
    expect(screen.getByText('standard_30_day_damaged')).toBeInTheDocument()

    // Decision Reasoning Callout
    expect(screen.getByTestId('section-decision-reasoning')).toBeInTheDocument()
    expect(
      screen.getByText(/Category damaged meets 30-day window rule\. Refund auto-approved\./i)
    ).toBeInTheDocument()

    // Customer Email Drafts
    expect(screen.getByTestId('section-email-previews')).toBeInTheDocument()
    expect(
      screen.getByText(/Dear Customer, your refund of \$85\.50 has been approved\./i)
    ).toBeInTheDocument()

    // Child slot rendered
    expect(screen.getByTestId('test-child-slot')).toBeInTheDocument()
    expect(screen.getByText('Evidence Gallery Extension')).toBeInTheDocument()
  })

  it('renders supervisor override banner when override decision details are present', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockOverriddenRecord)

    renderWithClient(
      <RefundDetailDrawer refundId="ref-99999" isOpen={true} onClose={vi.fn()} />
    )

    await waitFor(() => {
      expect(screen.getByTestId('supervisor-override-banner')).toBeInTheDocument()
    })

    expect(screen.getByText(/Supervisor Decision Override/i)).toBeInTheDocument()
    expect(screen.getByText(/Overridden to:/i)).toBeInTheDocument()
    expect(
      screen.getByText(/Approved as a one-time customer courtesy by supervisor/i)
    ).toBeInTheDocument()
  })

  it('switches email draft tabs and renders placeholder when draft is missing', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockDetailRecord)

    renderWithClient(
      <RefundDetailDrawer refundId="ref-12345" isOpen={true} onClose={vi.fn()} />
    )

    await waitFor(() => {
      expect(
        screen.getByText(/Dear Customer, your refund of \$85\.50 has been approved\./i)
      ).toBeInTheDocument()
    })

    // Click Denial Draft tab
    const denialTab = screen.getByRole('button', { name: /denial draft/i })
    fireEvent.click(denialTab)

    expect(
      screen.getByText(/no email generated for this workflow state/i)
    ).toBeInTheDocument()

    // Click Clarification Draft tab
    const clarifyTab = screen.getByRole('button', { name: /clarification draft/i })
    fireEvent.click(clarifyTab)

    expect(
      screen.getByText(/no email generated for this workflow state/i)
    ).toBeInTheDocument()
  })

  it('triggers onTriggerOverride and onTriggerRequestProof callbacks when action buttons are clicked', async () => {
    vi.mocked(refundService.getRefundById).mockResolvedValue(mockOverriddenRecord)
    const handleOverride = vi.fn()
    const handleRequestProof = vi.fn()

    renderWithClient(
      <RefundDetailDrawer
        refundId="ref-99999"
        isOpen={true}
        onClose={vi.fn()}
        onTriggerOverride={handleOverride}
        onTriggerRequestProof={handleRequestProof}
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('supervisor-override-banner')).toBeInTheDocument()
    })

    // Click Manual Override
    const overrideBtn = screen.getByRole('button', { name: /manual override/i })
    fireEvent.click(overrideBtn)
    expect(handleOverride).toHaveBeenCalledWith('ref-99999')

    // Click Request Proof (enabled because status is escalated)
    const proofBtn = screen.getByRole('button', { name: /request proof/i })
    expect(proofBtn).not.toBeDisabled()
    fireEvent.click(proofBtn)
    expect(handleRequestProof).toHaveBeenCalledWith('ref-99999')
  })

  it('renders RFC 9457 error banner and calls refetch when retry is clicked', async () => {
    const errorWithProblem = Object.assign(new Error('Record not found'), {
      problem: {
        title: 'Refund Not Found',
        detail: 'The requested refund record ref-error was not found in the database.',
      },
    })

    vi.mocked(refundService.getRefundById).mockRejectedValueOnce(errorWithProblem)

    renderWithClient(
      <RefundDetailDrawer refundId="ref-error" isOpen={true} onClose={vi.fn()} />
    )

    await waitFor(() => {
      expect(screen.getByTestId('detail-error-banner')).toBeInTheDocument()
    })

    expect(screen.getByText('Refund Not Found')).toBeInTheDocument()
    expect(
      screen.getByText(
        'The requested refund record ref-error was not found in the database.'
      )
    ).toBeInTheDocument()

    // Test retry button
    vi.mocked(refundService.getRefundById).mockResolvedValueOnce(mockDetailRecord)
    const retryBtn = screen.getByRole('button', { name: /retry/i })
    fireEvent.click(retryBtn)

    await waitFor(() => {
      expect(screen.getByTestId('detail-refund-id')).toHaveTextContent('ref-12345')
    })
    expect(screen.queryByTestId('detail-error-banner')).not.toBeInTheDocument()
  })

  it('renders Submit Clarification button when status is awaiting_clarification and triggers onTriggerClarify', async () => {
    const mockAwaitingClarification: RefundRecord = {
      ...mockDetailRecord,
      refundId: 'ref-clarify-77',
      status: 'awaiting_clarification',
      decision: 'escalate',
    } as unknown as RefundRecord

    vi.mocked(refundService.getRefundById).mockResolvedValue(mockAwaitingClarification)
    const handleClarify = vi.fn()

    renderWithClient(
      <RefundDetailDrawer
        refundId="ref-clarify-77"
        isOpen={true}
        onClose={vi.fn()}
        onTriggerClarify={handleClarify}
      />
    )

    await waitFor(() => {
      const clarifyBtn = screen.getByTestId('drawer-clarify-button')
      expect(clarifyBtn).toBeInTheDocument()
      expect(clarifyBtn).not.toBeDisabled()
    })

    const clarifyBtn = screen.getByTestId('drawer-clarify-button')
    fireEvent.click(clarifyBtn)
    expect(handleClarify).toHaveBeenCalledWith('ref-clarify-77')
  })
})
