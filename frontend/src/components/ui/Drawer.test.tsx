import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import {
  Drawer,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
  DrawerContent,
  DrawerFooter,
} from './Drawer'
import { Button } from './Button'

describe('Drawer component', () => {
  it('does not render content when isOpen is false', () => {
    render(
      <Drawer isOpen={false} onClose={vi.fn()}>
        <div>Drawer Body</div>
      </Drawer>
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByText('Drawer Body')).not.toBeInTheDocument()
  })

  it('renders slide-over container with header, content, and footer when open', () => {
    render(
      <Drawer isOpen={true} onClose={vi.fn()}>
        <DrawerHeader>
          <DrawerTitle>Refund Request #REF-12345</DrawerTitle>
          <DrawerDescription>Multi-agent evaluation trace & details</DrawerDescription>
        </DrawerHeader>
        <DrawerContent>
          <div>Inspection content details</div>
        </DrawerContent>
        <DrawerFooter>
          <Button variant="outline">Close</Button>
          <Button variant="success">Approve Refund</Button>
        </DrawerFooter>
      </Drawer>
    )

    const drawer = screen.getByRole('dialog')
    expect(drawer).toBeInTheDocument()
    expect(drawer).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByText('Refund Request #REF-12345')).toBeInTheDocument()
    expect(screen.getByText('Multi-agent evaluation trace & details')).toBeInTheDocument()
    expect(screen.getByText('Inspection content details')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /approve refund/i })).toBeInTheDocument()
  })

  it('calls onClose when clicking close button', () => {
    const handleClose = vi.fn()
    render(
      <Drawer isOpen={true} onClose={handleClose}>
        <div>Drawer Body</div>
      </Drawer>
    )

    const closeBtn = screen.getByTestId('drawer-close-button')
    fireEvent.click(closeBtn)
    expect(handleClose).toHaveBeenCalledTimes(1)
  })

  it('calls onClose when clicking backdrop overlay', () => {
    const handleClose = vi.fn()
    render(
      <Drawer isOpen={true} onClose={handleClose}>
        <div>Drawer Body</div>
      </Drawer>
    )

    const backdrop = screen.getByTestId('drawer-backdrop')
    fireEvent.click(backdrop)
    expect(handleClose).toHaveBeenCalledTimes(1)
  })

  it('calls onClose when pressing Escape key', () => {
    const handleClose = vi.fn()
    render(
      <Drawer isOpen={true} onClose={handleClose}>
        <div>Drawer Body</div>
      </Drawer>
    )

    fireEvent.keyDown(document, { key: 'Escape', code: 'Escape' })
    expect(handleClose).toHaveBeenCalledTimes(1)
  })

  it('traps focus inside the drawer when tabbing', () => {
    render(
      <Drawer isOpen={true} onClose={vi.fn()}>
        <button id="first-action" type="button">First Action</button>
        <button id="second-action" type="button">Second Action</button>
      </Drawer>
    )

    const closeButton = screen.getByTestId('drawer-close-button')
    const firstBtn = screen.getByRole('button', { name: /first action/i })
    const secondBtn = screen.getByRole('button', { name: /second action/i })

    expect(firstBtn).toBeInTheDocument()
    // Initial focus on the close button
    expect(document.activeElement).toBe(closeButton)

    // Tab from last element wraps to first
    secondBtn.focus()
    expect(document.activeElement).toBe(secondBtn)
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: false })
    expect(document.activeElement).toBe(closeButton)

    // Shift-Tab from first element wraps to last
    closeButton.focus()
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(secondBtn)
  })
})
