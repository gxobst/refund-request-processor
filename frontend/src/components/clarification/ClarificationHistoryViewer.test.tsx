import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ClarificationHistoryViewer } from './ClarificationHistoryViewer'
import type { ClarificationTurn } from '@/types/api'

const mockHistory: ClarificationTurn[] = [
  {
    cycle: 1,
    prompt: 'Please provide a clear photograph of the damaged shipping label.',
    response: 'Here is the photograph of the box label showing the shipping barcode.',
    timestamp: '2026-09-28T10:15:00Z',
    evidenceIds: ['evi_label_001', 'evi_label_002'],
  } as unknown as ClarificationTurn,
  {
    cycle: 2,
    prompt: 'Can you confirm if the inner seal was intact when opened?',
    response: null,
    timestamp: '2026-09-28T11:00:00Z',
    evidenceIds: [],
  } as unknown as ClarificationTurn,
]

const mockSnakeCaseTurn: ClarificationTurn[] = [
  {
    cycle: 1,
    prompt: 'Please upload order invoice.',
    response: 'Invoice attached.',
    timestamp: '2026-09-28T12:00:00Z',
    evidence_ids: ['evi_invoice_99'],
  } as unknown as ClarificationTurn,
]

describe('ClarificationHistoryViewer component', () => {
  it('renders empty state when history is empty array, null, or undefined', () => {
    const { rerender } = render(<ClarificationHistoryViewer history={[]} />)

    expect(screen.getByTestId('clarification-empty-state')).toBeInTheDocument()
    expect(screen.getByText('No clarification history')).toBeInTheDocument()
    expect(
      screen.getByText(/no clarification cycles or customer inquiries recorded/i)
    ).toBeInTheDocument()

    rerender(<ClarificationHistoryViewer history={null} />)
    expect(screen.getByTestId('clarification-empty-state')).toBeInTheDocument()

    rerender(
      <ClarificationHistoryViewer
        history={[]}
        emptyMessage="Custom empty message for history"
      />
    )
    expect(screen.getByText('Custom empty message for history')).toBeInTheDocument()
  })

  it('renders timeline with cycle badges, timestamps, inquiry prompts, and customer responses', () => {
    render(<ClarificationHistoryViewer history={mockHistory} />)

    // Check timeline list
    expect(screen.getByRole('list')).toBeInTheDocument()
    const items = screen.getAllByTestId('clarification-turn-item')
    expect(items.length).toBe(2)

    // Check Cycle badges
    expect(screen.getByText('Cycle 1')).toBeInTheDocument()
    expect(screen.getByText('Cycle 2')).toBeInTheDocument()

    // Check Prompt 1 & Response 1
    expect(
      screen.getByText(/Please provide a clear photograph of the damaged shipping label\./i)
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        /Here is the photograph of the box label showing the shipping barcode\./i
      )
    ).toBeInTheDocument()

    // Check Prompt 2
    expect(
      screen.getByText(/Can you confirm if the inner seal was intact when opened\?/i)
    ).toBeInTheDocument()
  })

  it('renders "Awaiting customer response" indicator when response is null or empty', () => {
    render(<ClarificationHistoryViewer history={mockHistory} />)

    const awaitingIndicators = screen.getAllByTestId('awaiting-response-indicator')
    expect(awaitingIndicators.length).toBe(1)
    expect(awaitingIndicators[0]).toHaveTextContent(/awaiting customer response/i)
  })

  it('renders linked evidence chips and calls onSelectEvidence when clicked', () => {
    const handleSelect = vi.fn()
    render(
      <ClarificationHistoryViewer
        history={mockHistory}
        onSelectEvidence={handleSelect}
      />
    )

    const chips = screen.getAllByTestId('evidence-id-chip')
    expect(chips.length).toBe(2)
    expect(chips[0]).toHaveTextContent('evi_label_001')
    expect(chips[1]).toHaveTextContent('evi_label_002')

    // Click first chip
    fireEvent.click(chips[0])
    expect(handleSelect).toHaveBeenCalledWith('evi_label_001')

    // Click second chip
    fireEvent.click(chips[1])
    expect(handleSelect).toHaveBeenCalledWith('evi_label_002')
  })

  it('safely handles snake_case evidence_ids property in turns', () => {
    const handleSelect = vi.fn()
    render(
      <ClarificationHistoryViewer
        history={mockSnakeCaseTurn}
        onSelectEvidence={handleSelect}
      />
    )

    const chip = screen.getByTestId('evidence-id-chip')
    expect(chip).toHaveTextContent('evi_invoice_99')

    fireEvent.click(chip)
    expect(handleSelect).toHaveBeenCalledWith('evi_invoice_99')
  })

  it('handles null prompt gracefully by rendering subtle notice', () => {
    const historyNoPrompt: ClarificationTurn[] = [
      {
        cycle: 1,
        prompt: null,
        response: 'Direct submission from user.',
        timestamp: '2026-09-28T14:00:00Z',
        evidenceIds: [],
      } as unknown as ClarificationTurn,
    ]

    render(<ClarificationHistoryViewer history={historyNoPrompt} />)

    expect(
      screen.getByTestId('inquiry-prompt-subtle-notice')
    ).toHaveTextContent(/direct customer submission/i)
    expect(screen.getByText('Direct submission from user.')).toBeInTheDocument()
  })
})
