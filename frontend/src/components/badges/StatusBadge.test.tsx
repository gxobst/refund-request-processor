import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatusBadge } from './StatusBadge'

describe('StatusBadge component', () => {
  it('renders pending status with Pending label and sky styling', () => {
    render(<StatusBadge status="pending" />)
    const badge = screen.getByTestId('status-badge')
    expect(badge).toHaveTextContent('Pending')
    expect(badge).toHaveClass('bg-sky-50')
    expect(badge).toHaveClass('text-sky-700')
    expect(badge).toHaveClass('border-sky-200')
  })

  it('renders processing status with Pending label and sky styling', () => {
    render(<StatusBadge status="processing" />)
    const badge = screen.getByTestId('status-badge')
    expect(badge).toHaveTextContent('Pending')
    expect(badge).toHaveClass('bg-sky-50')
    expect(badge).toHaveClass('text-sky-700')
  })

  it('renders completed status with Completed label and slate styling', () => {
    render(<StatusBadge status="completed" />)
    const badge = screen.getByTestId('status-badge')
    expect(badge).toHaveTextContent('Completed')
    expect(badge).toHaveClass('bg-slate-100')
    expect(badge).toHaveClass('text-slate-700')
    expect(badge).toHaveClass('border-slate-300')
  })

  it('renders escalated status with Escalated label and amber styling', () => {
    render(<StatusBadge status="escalated" />)
    const badge = screen.getByTestId('status-badge')
    expect(badge).toHaveTextContent('Escalated')
    expect(badge).toHaveClass('bg-amber-50')
    expect(badge).toHaveClass('text-amber-800')
    expect(badge).toHaveClass('border-amber-200')
  })

  it('renders awaiting_clarification status with Awaiting Clarification and purple styling', () => {
    render(<StatusBadge status="awaiting_clarification" />)
    const badge = screen.getByTestId('status-badge')
    expect(badge).toHaveTextContent('Awaiting Clarification')
    expect(badge).toHaveClass('bg-purple-50')
    expect(badge).toHaveClass('text-purple-700')
    expect(badge).toHaveClass('border-purple-200')
  })

  it('handles case-insensitivity and hyphenated/underscored status strings gracefully', () => {
    const { rerender } = render(<StatusBadge status="AWAITING_CLARIFICATION" />)
    let badge = screen.getByTestId('status-badge')
    expect(badge).toHaveTextContent('Awaiting Clarification')
    expect(badge).toHaveClass('bg-purple-50')

    rerender(<StatusBadge status="awaiting-clarification" />)
    badge = screen.getByTestId('status-badge')
    expect(badge).toHaveTextContent('Awaiting Clarification')

    rerender(<StatusBadge status="PENDING" />)
    badge = screen.getByTestId('status-badge')
    expect(badge).toHaveTextContent('Pending')
  })

  it('renders fallback neutral badge for null, undefined, empty, or unknown status strings', () => {
    const { rerender } = render(<StatusBadge status={null} />)
    let badge = screen.getByTestId('status-badge')
    expect(badge).toHaveTextContent('Unknown')
    expect(badge).toHaveClass('bg-slate-100')
    expect(badge).toHaveClass('text-slate-500')
    expect(badge).toHaveClass('border-slate-200')

    rerender(<StatusBadge status={undefined} />)
    badge = screen.getByTestId('status-badge')
    expect(badge).toHaveTextContent('Unknown')

    rerender(<StatusBadge status="" />)
    badge = screen.getByTestId('status-badge')
    expect(badge).toHaveTextContent('Unknown')

    rerender(<StatusBadge status="unrecognized_status" />)
    badge = screen.getByTestId('status-badge')
    expect(badge).toHaveTextContent('Unknown')
  })
})
