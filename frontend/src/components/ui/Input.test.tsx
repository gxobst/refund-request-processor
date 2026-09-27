import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Input } from './Input'

describe('Input component', () => {
  it('renders input with default placeholder and value', () => {
    render(<Input placeholder="Search orders..." />)
    const input = screen.getByPlaceholderText('Search orders...')
    expect(input).toBeInTheDocument()
    expect(input).toHaveClass('border-slate-300')
  })

  it('handles typing and onChange events', () => {
    const handleChange = vi.fn()
    render(<Input placeholder="Enter refund ID" onChange={handleChange} />)

    const input = screen.getByPlaceholderText('Enter refund ID')
    fireEvent.change(input, { target: { value: 'REF-999' } })
    expect(handleChange).toHaveBeenCalledTimes(1)
  })

  it('renders error state border and aria-invalid', () => {
    render(<Input placeholder="Order ID" hasError={true} />)
    const input = screen.getByPlaceholderText('Order ID')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveClass('border-rose-500')
  })

  it('renders disabled state correctly', () => {
    render(<Input placeholder="Disabled" disabled />)
    const input = screen.getByPlaceholderText('Disabled')
    expect(input).toBeDisabled()
  })
})
