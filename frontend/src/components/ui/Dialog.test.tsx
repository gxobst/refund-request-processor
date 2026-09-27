import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import {
  Dialog,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from './Dialog'
import { Button } from './Button'

describe('Dialog component', () => {
  it('does not render content when isOpen is false', () => {
    render(
      <Dialog isOpen={false} onClose={vi.fn()}>
        <div>Dialog Content</div>
      </Dialog>
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByText('Dialog Content')).not.toBeInTheDocument()
  })

  it('renders content with header, title, description, and footer when open', () => {
    render(
      <Dialog isOpen={true} onClose={vi.fn()}>
        <DialogHeader>
          <DialogTitle>Confirm Decision Override</DialogTitle>
          <DialogDescription>Are you sure you want to approve this refund?</DialogDescription>
        </DialogHeader>
        <div>Body Content Here</div>
        <DialogFooter>
          <Button variant="outline">Cancel</Button>
          <Button variant="destructive">Confirm Override</Button>
        </DialogFooter>
      </Dialog>
    )

    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeInTheDocument()
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByText('Confirm Decision Override')).toBeInTheDocument()
    expect(screen.getByText('Are you sure you want to approve this refund?')).toBeInTheDocument()
    expect(screen.getByText('Body Content Here')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /confirm override/i })).toBeInTheDocument()
  })

  it('calls onClose when clicking close button', () => {
    const handleClose = vi.fn()
    render(
      <Dialog isOpen={true} onClose={handleClose}>
        <div>Dialog Content</div>
      </Dialog>
    )

    const closeButton = screen.getByRole('button', { name: /close/i })
    fireEvent.click(closeButton)
    expect(handleClose).toHaveBeenCalledTimes(1)
  })

  it('calls onClose when clicking backdrop overlay', () => {
    const handleClose = vi.fn()
    render(
      <Dialog isOpen={true} onClose={handleClose}>
        <div>Dialog Content</div>
      </Dialog>
    )

    const backdrop = screen.getByTestId('dialog-backdrop')
    fireEvent.click(backdrop)
    expect(handleClose).toHaveBeenCalledTimes(1)
  })

  it('calls onClose when pressing Escape key', () => {
    const handleClose = vi.fn()
    render(
      <Dialog isOpen={true} onClose={handleClose}>
        <div>Dialog Content</div>
      </Dialog>
    )

    fireEvent.keyDown(document, { key: 'Escape', code: 'Escape' })
    expect(handleClose).toHaveBeenCalledTimes(1)
  })

  it('traps focus inside the dialog when tabbing', () => {
    render(
      <Dialog isOpen={true} onClose={vi.fn()}>
        <button id="first-btn" type="button">First Action</button>
        <button id="second-btn" type="button">Second Action</button>
      </Dialog>
    )

    const closeButton = screen.getByRole('button', { name: /close/i })
    const firstBtn = screen.getByRole('button', { name: /first action/i })
    const secondBtn = screen.getByRole('button', { name: /second action/i })

    expect(firstBtn).toBeInTheDocument()
    // First focusable element should receive focus on open (the close button)
    expect(document.activeElement).toBe(closeButton)

    // Focus last button and press Tab -> wraps to first focusable element
    secondBtn.focus()
    expect(document.activeElement).toBe(secondBtn)
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: false })
    expect(document.activeElement).toBe(closeButton)

    // Press Shift+Tab on first element -> wraps to last focusable element
    closeButton.focus()
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(secondBtn)
  })
})
