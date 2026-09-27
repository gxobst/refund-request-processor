import * as React from 'react'
import { cn } from '@/lib/utils'

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  hasError?: boolean
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, hasError = false, disabled, ...props }, ref) => {
    return (
      <textarea
        ref={ref}
        disabled={disabled}
        aria-invalid={hasError ? 'true' : undefined}
        className={cn(
          'flex min-h-[80px] w-full rounded-md border bg-white px-3 py-2 text-sm shadow-sm transition-colors',
          'placeholder:text-slate-400',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-1',
          'disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-slate-50',
          hasError
            ? 'border-rose-500 text-rose-900 focus-visible:ring-rose-500'
            : 'border-slate-300 text-slate-900 focus-visible:ring-slate-950',
          className
        )}
        {...props}
      />
    )
  }
)

Textarea.displayName = 'Textarea'
