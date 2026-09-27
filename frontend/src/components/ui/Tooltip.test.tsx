import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { Tooltip } from './Tooltip'

describe('Tooltip component', () => {
  it('renders child element and shows tooltip on mouse enter with delay', async () => {
    vi.useFakeTimers()

    render(
      <Tooltip content="Confidence: 94%" delayMs={50}>
        <button type="button">Hover Me</button>
      </Tooltip>
    )

    const button = screen.getByRole('button', { name: /hover me/i })
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()

    // Hover trigger
    fireEvent.mouseEnter(button)

    // Before timer fires
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()

    // Fast forward timer
    act(() => {
      vi.advanceTimersByTime(50)
    })

    const tooltip = screen.getByRole('tooltip')
    expect(tooltip).toBeInTheDocument()
    expect(tooltip).toHaveTextContent('Confidence: 94%')

    // Mouse leave hides tooltip
    fireEvent.mouseLeave(button)
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()

    vi.useRealTimers()
  })

  it('shows on focus and hides on blur', () => {
    render(
      <Tooltip content="Metadata hint" delayMs={0}>
        <button type="button">Focus Me</button>
      </Tooltip>
    )

    const button = screen.getByRole('button', { name: /focus me/i })
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()

    fireEvent.focus(button)
    expect(screen.getByRole('tooltip')).toHaveTextContent('Metadata hint')

    fireEvent.blur(button)
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('hides on Escape key', () => {
    render(
      <Tooltip content="Metadata hint" delayMs={0}>
        <button type="button">Focus Me</button>
      </Tooltip>
    )

    const button = screen.getByRole('button', { name: /focus me/i })
    fireEvent.focus(button)
    expect(screen.getByRole('tooltip')).toBeInTheDocument()

    fireEvent.keyDown(button, { key: 'Escape' })
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })
})
