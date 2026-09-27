import * as React from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface DrawerProps {
  isOpen: boolean
  onClose: () => void
  children: React.ReactNode
  className?: string
  widthClassName?: string
  showCloseButton?: boolean
  'aria-labelledby'?: string
  'aria-describedby'?: string
}

export function Drawer({
  isOpen,
  onClose,
  children,
  className,
  widthClassName = 'max-w-2xl',
  showCloseButton = true,
  'aria-labelledby': ariaLabelledBy,
  'aria-describedby': ariaDescribedBy,
}: DrawerProps) {
  const drawerRef = React.useRef<HTMLDivElement>(null)
  const previousActiveElement = React.useRef<HTMLElement | null>(null)

  React.useEffect(() => {
    if (!isOpen) return

    previousActiveElement.current = document.activeElement as HTMLElement
    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const getFocusableElements = (): HTMLElement[] => {
      if (!drawerRef.current) return []
      const focusableSelector =
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      return Array.from(
        drawerRef.current.querySelectorAll<HTMLElement>(focusableSelector)
      ).filter(
        (el) => !el.hasAttribute('disabled') && el.getAttribute('aria-hidden') !== 'true'
      )
    }

    const focusable = getFocusableElements()
    if (focusable.length > 0) {
      focusable[0].focus()
    } else if (drawerRef.current) {
      drawerRef.current.focus()
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
        return
      }

      if (event.key === 'Tab') {
        const focusableElements = getFocusableElements()
        if (focusableElements.length === 0) {
          event.preventDefault()
          return
        }

        const firstElement = focusableElements[0]
        const lastElement = focusableElements[focusableElements.length - 1]

        if (event.shiftKey) {
          if (document.activeElement === firstElement) {
            event.preventDefault()
            lastElement.focus()
          }
        } else {
          if (document.activeElement === lastElement) {
            event.preventDefault()
            firstElement.focus()
          }
        }
      }
    }

    document.addEventListener('keydown', handleKeyDown)

    return () => {
      document.body.style.overflow = originalOverflow
      document.removeEventListener('keydown', handleKeyDown)
      if (previousActiveElement.current?.focus) {
        previousActiveElement.current.focus()
      }
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  const content = (
    <div
      className="fixed inset-0 z-50 overflow-hidden"
      role="presentation"
    >
      {/* Backdrop overlay */}
      <div
        data-testid="drawer-backdrop"
        aria-hidden="true"
        onClick={onClose}
        className="fixed inset-0 bg-slate-900/50 backdrop-blur-sm transition-opacity animate-in fade-in duration-200"
      />

      <div className="fixed inset-y-0 right-0 flex max-w-full pl-10 pointer-events-none">
        <div
          ref={drawerRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={ariaLabelledBy}
          aria-describedby={ariaDescribedBy}
          tabIndex={-1}
          className={cn(
            'pointer-events-auto relative w-screen bg-white shadow-2xl flex flex-col h-full border-l border-slate-200 outline-none',
            'animate-in slide-in-from-right duration-300 ease-in-out',
            widthClassName,
            className
          )}
        >
          {showCloseButton && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close drawer"
              data-testid="drawer-close-button"
              className="absolute right-4 top-4 z-10 rounded-md p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-slate-400"
            >
              <X className="h-5 w-5" />
              <span className="sr-only">Close drawer</span>
            </button>
          )}
          {children}
        </div>
      </div>
    </div>
  )

  if (typeof document !== 'undefined') {
    return createPortal(content, document.body)
  }

  return content
}

export const DrawerHeader = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      'flex flex-col space-y-1.5 p-6 border-b border-slate-200 bg-white pr-14',
      className
    )}
    {...props}
  />
))
DrawerHeader.displayName = 'DrawerHeader'

export const DrawerTitle = React.forwardRef<
  HTMLHeadingElement,
  React.HTMLAttributes<HTMLHeadingElement>
>(({ className, ...props }, ref) => (
  <h2
    ref={ref}
    className={cn(
      'text-lg font-semibold leading-tight text-slate-900',
      className
    )}
    {...props}
  />
))
DrawerTitle.displayName = 'DrawerTitle'

export const DrawerDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <p
    ref={ref}
    className={cn('text-sm text-slate-500', className)}
    {...props}
  />
))
DrawerDescription.displayName = 'DrawerDescription'

export const DrawerContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn('flex-1 overflow-y-auto p-6 space-y-6', className)}
    {...props}
  />
))
DrawerContent.displayName = 'DrawerContent'

export const DrawerFooter = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      'border-t border-slate-200 p-4 bg-slate-50 flex items-center justify-end space-x-3',
      className
    )}
    {...props}
  />
))
DrawerFooter.displayName = 'DrawerFooter'
