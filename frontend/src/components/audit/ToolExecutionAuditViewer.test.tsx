import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import {
  ToolExecutionAuditViewer,
  formatDuration,
} from './ToolExecutionAuditViewer'
import type { ToolCallAudit } from '@/types/api'

const mockToolCalls: ToolCallAudit[] = [
  {
    toolName: 'query_carrier_tracking',
    inputArgs: { trackingNumber: 'TRK-987654' },
    rawOutput: { status: 'delivered', deliveryTimestamp: '2026-09-20T10:30:00Z' },
    durationSeconds: 0.42,
    timestamp: '2026-09-28T10:10:02Z',
  } as unknown as ToolCallAudit,
  {
    toolName: 'query_payment_transaction',
    inputArgs: { chargeId: 'ch_3N123' },
    rawOutput: { status: 'succeeded', amount: 8550 },
    durationSeconds: 1.25,
    timestamp: '2026-09-28T10:10:05Z',
  } as unknown as ToolCallAudit,
  {
    toolName: 'query_external_inventory',
    inputArgs: { sku: 'SKU-99' },
    rawOutput: { error: 'Warehouse service unreachable', status: 'error' },
    durationSeconds: 0.05,
    timestamp: '2026-09-28T10:10:08Z',
  } as unknown as ToolCallAudit,
]

const mockSnakeCaseCalls: ToolCallAudit[] = [
  {
    tool_name: 'query_carrier_tracking',
    tool_input: { tracking_number: 'TRK-SNAKE-1' },
    tool_output: { status: 'delivered' },
    duration_seconds: 0.35,
    timestamp: '2026-09-28T11:00:00Z',
  } as unknown as ToolCallAudit,
]

describe('formatDuration helper', () => {
  it('formats milliseconds and seconds properly', () => {
    expect(formatDuration(null)).toBeNull()
    expect(formatDuration(undefined)).toBeNull()
    expect(formatDuration(0.42)).toBe('420ms')
    expect(formatDuration(0.05)).toBe('50ms')
    expect(formatDuration(1.25)).toBe('1.25s')
    expect(formatDuration(3)).toBe('3.00s')
  })
})

describe('ToolExecutionAuditViewer component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders empty state when toolCalls is empty array or null', () => {
    const { rerender } = render(<ToolExecutionAuditViewer toolCalls={[]} />)

    expect(screen.getByTestId('tool-audit-empty-state')).toBeInTheDocument()
    expect(screen.getByText('No external tools executed')).toBeInTheDocument()
    expect(
      screen.getByText(
        /no external tool verifications or carrier queries were triggered/i
      )
    ).toBeInTheDocument()

    rerender(<ToolExecutionAuditViewer toolCalls={null} />)
    expect(screen.getByTestId('tool-audit-empty-state')).toBeInTheDocument()

    rerender(
      <ToolExecutionAuditViewer
        toolCalls={[]}
        emptyMessage="Custom empty audit message"
      />
    )
    expect(screen.getByText('Custom empty audit message')).toBeInTheDocument()
  })

  it('renders carrier tracking, payment transaction, and fallback tool badges with icons', () => {
    render(<ToolExecutionAuditViewer toolCalls={mockToolCalls} />)

    const cards = screen.getAllByTestId('tool-call-card')
    expect(cards.length).toBe(3)

    // Carrier tracking badge
    expect(screen.getByTestId('tool-badge-carrier')).toBeInTheDocument()
    expect(screen.getByText('query_carrier_tracking')).toBeInTheDocument()

    // Payment transaction badge
    expect(screen.getByTestId('tool-badge-payment')).toBeInTheDocument()
    expect(screen.getByText('query_payment_transaction')).toBeInTheDocument()

    // Fallback badge
    expect(screen.getByTestId('tool-badge-fallback')).toBeInTheDocument()
    expect(screen.getByText('query_external_inventory')).toBeInTheDocument()
  })

  it('displays duration metrics and timestamps accurately', () => {
    render(<ToolExecutionAuditViewer toolCalls={mockToolCalls} />)

    // Duration badges
    expect(screen.getByText('420ms')).toBeInTheDocument()
    expect(screen.getByText('1.25s')).toBeInTheDocument()
    expect(screen.getByText('50ms')).toBeInTheDocument()

    // Timestamps
    const timestamps = screen.getAllByTestId('tool-timestamp')
    expect(timestamps.length).toBe(3)
  })

  it('toggles collapsible Input Arguments and Output Results panels', () => {
    render(<ToolExecutionAuditViewer toolCalls={[mockToolCalls[0]]} />)

    // Initially both panels are open
    expect(screen.getByTestId('inputs-content')).toBeInTheDocument()
    expect(screen.getByTestId('outputs-content')).toBeInTheDocument()

    // Collapse inputs
    const toggleInputsBtn = screen.getByTestId('toggle-inputs-button')
    fireEvent.click(toggleInputsBtn)
    expect(screen.queryByTestId('inputs-content')).not.toBeInTheDocument()

    // Expand inputs again
    fireEvent.click(toggleInputsBtn)
    expect(screen.getByTestId('inputs-content')).toBeInTheDocument()

    // Collapse outputs
    const toggleOutputsBtn = screen.getByTestId('toggle-outputs-button')
    fireEvent.click(toggleOutputsBtn)
    expect(screen.queryByTestId('outputs-content')).not.toBeInTheDocument()
  })

  it('renders error badge and highlights output when rawOutput reports an error', () => {
    render(<ToolExecutionAuditViewer toolCalls={mockToolCalls} />)

    // Check error badge
    const errorBadge = screen.getByTestId('tool-error-badge')
    expect(errorBadge).toBeInTheDocument()
    expect(errorBadge).toHaveTextContent('Execution Error')
    expect(errorBadge).toHaveClass('bg-rose-50')

    // Check error message inside code block
    expect(
      screen.getByText(/Warehouse service unreachable/i)
    ).toBeInTheDocument()
  })

  it('normalizes snake_case tool call properties safely', () => {
    render(<ToolExecutionAuditViewer toolCalls={mockSnakeCaseCalls} />)

    expect(screen.getByTestId('tool-badge-carrier')).toBeInTheDocument()
    expect(screen.getByText('350ms')).toBeInTheDocument()
    expect(screen.getByText(/TRK-SNAKE-1/i)).toBeInTheDocument()
  })

  it('copies JSON string to clipboard when clicking Copy JSON button', async () => {
    vi.useFakeTimers()

    // Mock clipboard API
    const writeTextMock = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    })

    render(<ToolExecutionAuditViewer toolCalls={[mockToolCalls[0]]} />)

    const copyButtons = screen.getAllByTestId('copy-json-button')
    expect(copyButtons.length).toBeGreaterThanOrEqual(1)

    // Click Copy JSON
    await act(async () => {
      fireEvent.click(copyButtons[0])
    })

    expect(writeTextMock).toHaveBeenCalledWith(
      JSON.stringify(mockToolCalls[0].inputArgs, null, 2)
    )

    // Verify feedback
    expect(copyButtons[0]).toHaveTextContent('Copied!')

    // Fast forward timer to verify feedback resets
    act(() => {
      vi.advanceTimersByTime(2000)
    })

    expect(copyButtons[0]).toHaveTextContent('Copy JSON')

    vi.useRealTimers()
  })
})
