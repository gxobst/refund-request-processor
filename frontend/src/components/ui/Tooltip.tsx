import * as React from 'react'
import { cn } from '@/lib/utils'

export type TooltipPosition = 'top' | 'bottom' | 'left' | 'right'

export interface TooltipProps {
  content: React.ReactNode
  children: React.ReactElement
  position?: TooltipPosition
  delayMs?: number
  className?: string
}

let tooltipCounter = 0

export function Tooltip({
  content,
  children,
  position = 'top',
  delayMs = 100,
  className,
}: TooltipProps) {
  const [isVisible, setIsVisible] = React.useState(false)
  const timerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const [tooltipId] = React.useState(() => `tooltip-${++tooltipCounter}`)

  const showTooltip = React.useCallback(() => {
    if (delayMs > 0) {
      timerRef.current = setTimeout(() => {
        setIsVisible(true)
      }, delayMs)
    } else {
      setIsVisible(true)
    }
  }, [delayMs])

  const hideTooltip = React.useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    setIsVisible(false)
  }, [])

  React.useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current)
      }
    }
  }, [])

  const positionClasses: Record<TooltipPosition, string> = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-1.5',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-1.5',
    left: 'right-full top-1/2 -translate-y-1/2 mr-1.5',
    right: 'left-full top-1/2 -translate-y-1/2 ml-1.5',
  }

  // Clone child to attach mouse, focus, and accessibility handlers
  const child = React.cloneElement(children, {
    'aria-describedby': isVisible ? tooltipId : undefined,
    onMouseEnter: (e: React.MouseEvent) => {
      showTooltip()
      children.props.onMouseEnter?.(e)
    },
    onMouseLeave: (e: React.MouseEvent) => {
      hideTooltip()
      children.props.onMouseLeave?.(e)
    },
    onFocus: (e: React.FocusEvent) => {
      showTooltip()
      children.props.onFocus?.(e)
    },
    onBlur: (e: React.FocusEvent) => {
      hideTooltip()
      children.props.onBlur?.(e)
    },
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        hideTooltip()
      }
      children.props.onKeyDown?.(e)
    },
  })

  return (
    <span className="relative inline-flex items-center">
      {child}
      {isVisible && content && (
        <span
          id={tooltipId}
          role="tooltip"
          className={cn(
            'absolute z-50 pointer-events-none whitespace-nowrap rounded bg-slate-900 px-2 py-1 text-xs font-normal text-white shadow-md animate-in fade-in zoom-in-95 duration-100',
            positionClasses[position],
            className
          )}
        >
          {content}
        </span>
      )}
    </span>
  )
}
