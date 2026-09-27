import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Textarea } from './Textarea'

describe('Textarea component', () => {
  it('renders textarea with placeholder', () => {
    render(<Textarea placeholder="Explain reason for manual override..." />)
    const textarea = screen.getByPlaceholderText('Explain reason for manual override...')
    expect(textarea).toBeInTheDocument()
    expect(textarea).toHaveClass('border-slate-300')
  })

  it('handles value changes', () => {
    const handleChange = vi.fn()
    render(<Textarea placeholder="Reason" onChange={handleChange} />)

    const textarea = screen.getByPlaceholderText('Reason')
    fireEvent.change(textarea, { target: { value: 'Customer provided photo proof' } })
    expect(handleChange).toHaveBeenCalledTimes(1)
  })

  it('renders error state border and aria-invalid', () => {
    render(<Textarea placeholder="Reason" hasError={true} />)
    const textarea = screen.getByPlaceholderText('Reason')
    expect(textarea).toHaveAttribute('aria-invalid', 'true')
    expect(textarea).toHaveClass('border-rose-500')
  })

  it('renders disabled state', () => {
    render(<Textarea placeholder="Reason" disabled />)
    const textarea = screen.getByPlaceholderText('Reason')
    expect(textarea).toBeDisabled()
  })
})
