import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { DecisionBadge } from './DecisionBadge'

describe('DecisionBadge component', () => {
  it('renders auto_approve decision with Auto Approved and emerald styling', () => {
    render(<DecisionBadge decision="auto_approve" />)
    const badge = screen.getByTestId('decision-badge')
    expect(badge).toHaveTextContent('Auto Approved')
    expect(badge).toHaveClass('bg-emerald-50')
    expect(badge).toHaveClass('text-emerald-700')
    expect(badge).toHaveClass('border-emerald-200')
  })

  it('renders deny decision with Denied and rose styling', () => {
    render(<DecisionBadge decision="deny" />)
    const badge = screen.getByTestId('decision-badge')
    expect(badge).toHaveTextContent('Denied')
    expect(badge).toHaveClass('bg-rose-50')
    expect(badge).toHaveClass('text-rose-700')
    expect(badge).toHaveClass('border-rose-200')
  })

  it('renders escalate decision with Escalated and amber styling', () => {
    render(<DecisionBadge decision="escalate" />)
    const badge = screen.getByTestId('decision-badge')
    expect(badge).toHaveTextContent('Escalated')
    expect(badge).toHaveClass('bg-amber-50')
    expect(badge).toHaveClass('text-amber-800')
    expect(badge).toHaveClass('border-amber-200')
  })

  it('renders manual_approved decision with Manually Approved and teal styling', () => {
    render(<DecisionBadge decision="manual_approved" />)
    const badge = screen.getByTestId('decision-badge')
    expect(badge).toHaveTextContent('Manually Approved')
    expect(badge).toHaveClass('bg-teal-50')
    expect(badge).toHaveClass('text-teal-700')
    expect(badge).toHaveClass('border-teal-200')
  })

  it('renders manual_denied decision with Manually Denied and red styling', () => {
    render(<DecisionBadge decision="manual_denied" />)
    const badge = screen.getByTestId('decision-badge')
    expect(badge).toHaveTextContent('Manually Denied')
    expect(badge).toHaveClass('bg-red-50')
    expect(badge).toHaveClass('text-red-700')
    expect(badge).toHaveClass('border-red-200')
  })

  it('handles case-insensitivity and hyphens/underscores gracefully', () => {
    const { rerender } = render(<DecisionBadge decision="AUTO_APPROVE" />)
    let badge = screen.getByTestId('decision-badge')
    expect(badge).toHaveTextContent('Auto Approved')
    expect(badge).toHaveClass('bg-emerald-50')

    rerender(<DecisionBadge decision="manual-approved" />)
    badge = screen.getByTestId('decision-badge')
    expect(badge).toHaveTextContent('Manually Approved')
    expect(badge).toHaveClass('bg-teal-50')

    rerender(<DecisionBadge decision="DENY" />)
    badge = screen.getByTestId('decision-badge')
    expect(badge).toHaveTextContent('Denied')
  })

  it('renders graceful fallback badge for null, undefined, empty, or unknown decisions', () => {
    const { rerender } = render(<DecisionBadge decision={null} />)
    let badge = screen.getByTestId('decision-badge')
    expect(badge).toHaveTextContent('Pending Review')
    expect(badge).toHaveClass('bg-slate-100')
    expect(badge).toHaveClass('text-slate-600')
    expect(badge).toHaveClass('border-slate-200')

    rerender(<DecisionBadge decision={undefined} />)
    badge = screen.getByTestId('decision-badge')
    expect(badge).toHaveTextContent('Pending Review')

    rerender(<DecisionBadge decision="" />)
    badge = screen.getByTestId('decision-badge')
    expect(badge).toHaveTextContent('Pending Review')

    rerender(<DecisionBadge decision="completely_unknown" />)
    badge = screen.getByTestId('decision-badge')
    expect(badge).toHaveTextContent('Pending Review')
  })

  it('integrates with Tooltip to display formatted confidence percentage on hover', () => {
    vi.useFakeTimers()

    render(<DecisionBadge decision="auto_approve" confidenceScore={0.94} />)
    const badge = screen.getByTestId('decision-badge')

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()

    // Hover badge
    fireEvent.mouseEnter(badge)

    act(() => {
      vi.advanceTimersByTime(150)
    })

    const tooltip = screen.getByRole('tooltip')
    expect(tooltip).toBeInTheDocument()
    expect(tooltip).toHaveTextContent('94% confidence')

    vi.useRealTimers()
  })

  it('correctly rounds confidence scores: 1.0 -> 100%, 0.0 -> 0%', () => {
    vi.useFakeTimers()

    const { rerender } = render(
      <DecisionBadge decision="auto_approve" confidenceScore={1.0} />
    )
    let badge = screen.getByTestId('decision-badge')
    fireEvent.mouseEnter(badge)
    act(() => {
      vi.advanceTimersByTime(150)
    })
    expect(screen.getByRole('tooltip')).toHaveTextContent('100% confidence')

    fireEvent.mouseLeave(badge)

    rerender(<DecisionBadge decision="auto_approve" confidenceScore={0.0} />)
    badge = screen.getByTestId('decision-badge')
    fireEvent.mouseEnter(badge)
    act(() => {
      vi.advanceTimersByTime(150)
    })
    expect(screen.getByRole('tooltip')).toHaveTextContent('0% confidence')

    vi.useRealTimers()
  })

  it('suppresses confidence tooltip when confidenceScore is null or undefined without errors', () => {
    render(<DecisionBadge decision="auto_approve" confidenceScore={null} />)
    const badge = screen.getByTestId('decision-badge')
    fireEvent.mouseEnter(badge)
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('suppresses confidence tooltip when showConfidence is false', () => {
    render(
      <DecisionBadge
        decision="auto_approve"
        confidenceScore={0.95}
        showConfidence={false}
      />
    )
    const badge = screen.getByTestId('decision-badge')
    fireEvent.mouseEnter(badge)
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })
})
