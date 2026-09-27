import * as React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RefundQueueTable } from './RefundQueueTable'
import * as refundService from '@/services/refundService'
import type { RefundRecord } from '@/types/api'

vi.mock('@/services/refundService', () => ({
  listRefunds: vi.fn(),
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

const mockRefunds: RefundRecord[] = [
  {
    refundId: 'ref-001',
    orderId: 'ORD-1001',
    customerRequestText: 'The package arrived broken and damaged.',
    status: 'completed',
    decision: 'auto_approve',
    confidenceScore: 0.95,
    category: 'damaged',
    orderAmount: 49.99,
    createdAt: '2026-09-28T10:00:00Z',
    updatedAt: '2026-09-28T10:01:00Z',
  } as unknown as RefundRecord,
  {
    refundId: 'ref-002',
    orderId: 'ORD-1002',
    customerRequestText: 'High value electronics missing from box.',
    status: 'escalated',
    decision: 'escalate',
    confidenceScore: 0.42,
    category: 'missing_item',
    orderAmount: 450.0,
    createdAt: '2026-09-28T11:00:00Z',
    updatedAt: '2026-09-28T11:05:00Z',
  } as unknown as RefundRecord,
]

const mockPendingRefunds: RefundRecord[] = [
  {
    refundId: 'ref-003',
    orderId: 'ORD-1003',
    customerRequestText: 'Still evaluating my refund request.',
    status: 'pending',
    decision: null,
    category: 'changed_mind',
    orderAmount: 89.0,
    createdAt: '2026-09-28T12:00:00Z',
    updatedAt: '2026-09-28T12:00:10Z',
  } as unknown as RefundRecord,
]

describe('RefundQueueTable component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders skeleton rows during query loading state', () => {
    vi.mocked(refundService.listRefunds).mockReturnValue(new Promise(() => {}))

    renderWithClient(<RefundQueueTable />)

    const skeletons = screen.getAllByTestId('skeleton-row')
    expect(skeletons.length).toBeGreaterThanOrEqual(1)
  })

  it('renders column data, badges, and warm highlight for escalated rows', async () => {
    vi.mocked(refundService.listRefunds).mockResolvedValue(mockRefunds)

    renderWithClient(<RefundQueueTable />)

    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
      expect(screen.getByText('ORD-1002')).toBeInTheDocument()
    })

    // Check customer request previews
    expect(
      screen.getByText(/the package arrived broken and damaged/i)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/high value electronics missing from box/i)
    ).toBeInTheDocument()

    // Check categories
    expect(screen.getByText('damaged')).toBeInTheDocument()
    expect(screen.getByText('missing item')).toBeInTheDocument()

    // Check currency formatting
    expect(screen.getByText('$49.99')).toBeInTheDocument()
    expect(screen.getByText('$450.00')).toBeInTheDocument()

    // Check badges
    expect(screen.getByText('Auto Approved')).toBeInTheDocument()
    const completedElements = screen.getAllByText('Completed')
    expect(completedElements.length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Escalated').length).toBeGreaterThanOrEqual(1)

    // Check escalated row styling (border-l-amber-400 / bg-amber-50/40)
    const rows = screen.getAllByTestId('refund-row')
    expect(rows[1]).toHaveClass('border-l-amber-400')
    expect(rows[1]).toHaveClass('bg-amber-50/40')
  })

  it('displays Live polling indicator when dataset contains pending items', async () => {
    vi.mocked(refundService.listRefunds).mockResolvedValue(mockPendingRefunds)

    renderWithClient(<RefundQueueTable />)

    await waitFor(() => {
      expect(screen.getByText('ORD-1003')).toBeInTheDocument()
    })

    const pollingIndicator = screen.getByTestId('table-polling-indicator')
    expect(pollingIndicator).toHaveTextContent(/live - polling every 3s/i)
  })

  it('displays Idle polling indicator when all dataset items are terminal', async () => {
    vi.mocked(refundService.listRefunds).mockResolvedValue(mockRefunds)

    renderWithClient(<RefundQueueTable />)

    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
    })

    const pollingIndicator = screen.getByTestId('table-polling-indicator')
    expect(pollingIndicator).toHaveTextContent(/idle/i)
  })

  it('filters query by status when clicking status tabs', async () => {
    vi.mocked(refundService.listRefunds).mockResolvedValue([])

    renderWithClient(<RefundQueueTable />)

    await waitFor(() => {
      expect(refundService.listRefunds).toHaveBeenCalledWith(undefined)
    })

    // Click Pending tab
    const pendingTab = screen.getByRole('tab', { name: /pending/i })
    fireEvent.click(pendingTab)

    await waitFor(() => {
      expect(refundService.listRefunds).toHaveBeenCalledWith({ status: 'pending' })
    })

    // Click Escalated tab
    const escalatedTab = screen.getByRole('tab', { name: /escalated/i })
    fireEvent.click(escalatedTab)

    await waitFor(() => {
      expect(refundService.listRefunds).toHaveBeenCalledWith({ status: 'escalated' })
    })

    // Click Awaiting Clarification tab
    const clarifyTab = screen.getByRole('tab', { name: /awaiting clarification/i })
    fireEvent.click(clarifyTab)

    await waitFor(() => {
      expect(refundService.listRefunds).toHaveBeenCalledWith({
        status: 'awaiting_clarification',
      })
    })

    // Click Completed tab
    const completedTab = screen.getByRole('tab', { name: /completed/i })
    fireEvent.click(completedTab)

    await waitFor(() => {
      expect(refundService.listRefunds).toHaveBeenCalledWith({
        status: 'completed',
      })
    })
  })

  it('renders accessible error banner with ProblemDetails and calls refetch on retry', async () => {
    const errorWithProblem = Object.assign(new Error('Backend connection failed'), {
      problem: {
        title: 'Service Unavailable',
        detail: 'Database cluster is currently experiencing failover.',
      },
    })

    vi.mocked(refundService.listRefunds).mockRejectedValueOnce(errorWithProblem)

    renderWithClient(<RefundQueueTable />)

    await waitFor(() => {
      expect(screen.getByTestId('queue-error-banner')).toBeInTheDocument()
    })

    expect(screen.getByText('Service Unavailable')).toBeInTheDocument()
    expect(
      screen.getByText('Database cluster is currently experiencing failover.')
    ).toBeInTheDocument()

    // Test retry button
    vi.mocked(refundService.listRefunds).mockResolvedValueOnce(mockRefunds)
    const retryBtn = screen.getByRole('button', { name: /retry/i })
    fireEvent.click(retryBtn)

    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('queue-error-banner')).not.toBeInTheDocument()
  })

  it('invokes onSelectRefund when clicking Review / Inspect button', async () => {
    vi.mocked(refundService.listRefunds).mockResolvedValue(mockRefunds)
    const handleSelect = vi.fn()

    renderWithClient(<RefundQueueTable onSelectRefund={handleSelect} />)

    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
    })

    const reviewButtons = screen.getAllByRole('button', { name: /review order/i })
    fireEvent.click(reviewButtons[0])

    expect(handleSelect).toHaveBeenCalledWith('ref-001')
  })

  it('renders descriptive empty state when dataset is empty', async () => {
    vi.mocked(refundService.listRefunds).mockResolvedValue([])

    renderWithClient(<RefundQueueTable />)

    await waitFor(() => {
      expect(screen.getByTestId('empty-state')).toBeInTheDocument()
    })

    expect(
      screen.getByText(/no refund requests found in this view/i)
    ).toBeInTheDocument()
  })
})
