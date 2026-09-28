import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { UserCheck, UserX, AlertCircle } from 'lucide-react'
import * as refundService from '@/services/refundService'
import { isApiError } from '@/services/apiClient'
import {
  Dialog,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/Dialog'
import { Button } from '@/components/ui/Button'
import { Textarea } from '@/components/ui/Textarea'
import { cn } from '@/lib/utils'
import type { RefundRecord, ProblemDetails } from '@/types/api'

export interface ManualOverrideModalProps {
  refundId: string | null
  isOpen: boolean
  onClose: () => void
  currentDecision?: string | null
  orderId?: string | null
  onSuccess?: (updatedRecord: RefundRecord) => void
}

type OverrideDecision = 'approve' | 'deny'

export function ManualOverrideModal({
  refundId,
  isOpen,
  onClose,
  currentDecision,
  orderId,
  onSuccess,
}: ManualOverrideModalProps) {
  const queryClient = useQueryClient()

  const [selectedDecision, setSelectedDecision] = React.useState<OverrideDecision>('approve')
  const [justification, setJustification] = React.useState('')
  const [isConfirmed, setIsConfirmed] = React.useState(false)
  const [validationError, setValidationError] = React.useState<string | null>(null)
  const [confirmationError, setConfirmationError] = React.useState<string | null>(null)
  const [mutationError, setMutationError] = React.useState<unknown | null>(null)

  const resetState = React.useCallback(() => {
    setSelectedDecision('approve')
    setJustification('')
    setIsConfirmed(false)
    setValidationError(null)
    setConfirmationError(null)
    setMutationError(null)
  }, [])

  // Reset internal state whenever modal closes
  React.useEffect(() => {
    if (!isOpen) {
      resetState()
    }
  }, [isOpen, resetState])

  const overrideMutation = useMutation({
    mutationFn: async (payload: refundService.OverrideRefundPayload) => {
      if (!refundId) {
        throw new Error('Refund ID is required to perform an override')
      }
      return refundService.overrideRefundDecision(refundId, payload)
    },
    onSuccess: async (updatedRecord) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['refund', refundId] }),
        queryClient.invalidateQueries({ queryKey: ['refunds'] }),
      ])
      onSuccess?.(updatedRecord)
      resetState()
      onClose()
    },
    onError: (err) => {
      setMutationError(err)
    },
  })

  const isPending = overrideMutation.isPending

  const handleClose = () => {
    if (isPending) return
    resetState()
    onClose()
  }

  const handleCancel = () => {
    if (isPending) return
    resetState()
    onClose()
  }

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault()
    if (isPending) return

    const trimmedReason = justification.trim()
    if (!trimmedReason) {
      setValidationError('Justification reason is required')
      return
    }

    if (!isConfirmed) {
      setConfirmationError('Confirmation is required before submitting override')
      return
    }

    setValidationError(null)
    setConfirmationError(null)
    setMutationError(null)

    overrideMutation.mutate({
      overrideDecision: selectedDecision,
      overrideReason: trimmedReason,
    })
  }

  // Extract RFC 9457 ProblemDetails
  const problemDetails = React.useMemo(() => {
    if (!mutationError) return null
    if (isApiError(mutationError)) {
      return mutationError.problem
    }
    const err = mutationError as Error & { problem?: ProblemDetails }
    if (err.problem) {
      return err.problem
    }
    return {
      title: 'Override Request Failed',
      detail:
        (mutationError as Error).message ||
        'An unexpected error occurred while overriding the decision.',
    }
  }, [mutationError])

  return (
    <Dialog
      isOpen={isOpen}
      onClose={handleClose}
      showCloseButton={!isPending}
      aria-labelledby="override-dialog-title"
      aria-describedby="override-dialog-description"
      className="max-w-lg"
    >
      <form onSubmit={handleSubmit} className="space-y-5" noValidate>
        <DialogHeader>
          <DialogTitle id="override-dialog-title">Manual Decision Override</DialogTitle>
          <DialogDescription id="override-dialog-description" className="space-y-1">
            <span className="block">
              Order ID: <span className="font-semibold text-slate-800">{orderId || 'N/A'}</span>
            </span>
            {currentDecision && (
              <span className="block text-xs text-slate-500">
                Current Decision:{' '}
                <span className="font-medium text-slate-700 capitalize">
                  {currentDecision}
                </span>
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        {/* RFC 9457 Error Banner */}
        {problemDetails && (
          <div
            role="alert"
            data-testid="override-error-banner"
            className="rounded-lg border border-rose-200 bg-rose-50 p-3.5 text-rose-900 flex items-start space-x-2.5"
          >
            <AlertCircle className="h-5 w-5 text-rose-600 flex-shrink-0 mt-0.5" />
            <div className="space-y-0.5">
              <h4 className="text-sm font-semibold text-rose-900">{problemDetails.title}</h4>
              {problemDetails.detail && (
                <p className="text-xs text-rose-700 leading-relaxed">{problemDetails.detail}</p>
              )}
            </div>
          </div>
        )}

        {/* Decision Choice Buttons */}
        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Override Decision
          </label>
          <div className="grid grid-cols-2 gap-3" role="group" aria-label="Decision choice">
            <button
              type="button"
              disabled={isPending}
              aria-pressed={selectedDecision === 'approve'}
              data-testid="decision-choice-approve"
              onClick={() => setSelectedDecision('approve')}
              className={cn(
                'flex items-center justify-center space-x-2 py-2.5 px-4 rounded-lg font-medium text-sm border transition-all select-none',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2',
                'disabled:opacity-50 disabled:cursor-not-allowed',
                selectedDecision === 'approve'
                  ? 'bg-emerald-600 text-white border-emerald-600 shadow-sm ring-2 ring-emerald-500 ring-offset-1'
                  : 'bg-white text-emerald-700 border-emerald-300 hover:bg-emerald-50'
              )}
            >
              <UserCheck className="h-4 w-4" />
              <span>Approve Refund</span>
            </button>

            <button
              type="button"
              disabled={isPending}
              aria-pressed={selectedDecision === 'deny'}
              data-testid="decision-choice-deny"
              onClick={() => setSelectedDecision('deny')}
              className={cn(
                'flex items-center justify-center space-x-2 py-2.5 px-4 rounded-lg font-medium text-sm border transition-all select-none',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500 focus-visible:ring-offset-2',
                'disabled:opacity-50 disabled:cursor-not-allowed',
                selectedDecision === 'deny'
                  ? 'bg-rose-600 text-white border-rose-600 shadow-sm ring-2 ring-rose-500 ring-offset-1'
                  : 'bg-white text-rose-700 border-rose-300 hover:bg-rose-50'
              )}
            >
              <UserX className="h-4 w-4" />
              <span>Deny Refund</span>
            </button>
          </div>
        </div>

        {/* Justification Textarea */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label
              htmlFor="override-justification"
              className="text-sm font-medium text-slate-700"
            >
              Override Justification (Required)
            </label>
            <span
              className="text-xs text-slate-500"
              data-testid="character-counter"
              aria-live="polite"
            >
              {justification.length} characters
            </span>
          </div>
          <Textarea
            id="override-justification"
            data-testid="override-justification-textarea"
            rows={4}
            placeholder="Explain why this decision is being manually overridden..."
            value={justification}
            onChange={(e) => {
              setJustification(e.target.value)
              if (validationError && e.target.value.trim()) {
                setValidationError(null)
              }
            }}
            disabled={isPending}
            hasError={Boolean(validationError)}
            aria-describedby={validationError ? 'justification-error' : undefined}
          />
          {validationError && (
            <p
              id="justification-error"
              data-testid="justification-error"
              role="alert"
              className="text-xs text-rose-600 font-medium"
            >
              {validationError}
            </p>
          )}
        </div>

        {/* Confirmation Guard Checkbox */}
        <div className="space-y-1 pt-1">
          <label
            htmlFor="confirm-override-checkbox"
            className="flex items-center space-x-2 text-sm text-slate-700 cursor-pointer select-none"
          >
            <input
              type="checkbox"
              id="confirm-override-checkbox"
              data-testid="confirm-override-checkbox"
              checked={isConfirmed}
              onChange={(e) => {
                setIsConfirmed(e.target.checked)
                if (confirmationError && e.target.checked) {
                  setConfirmationError(null)
                }
              }}
              disabled={isPending}
              className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-950 focus:ring-offset-1"
            />
            <span className="font-medium text-slate-800">
              I confirm this manual decision override
            </span>
          </label>
          {confirmationError && (
            <p
              id="confirmation-error"
              data-testid="confirmation-error"
              role="alert"
              className="text-xs text-rose-600 font-medium"
            >
              {confirmationError}
            </p>
          )}
        </div>

        {/* Dialog Footer Actions */}
        <DialogFooter className="mt-6">
          <div className="flex items-center justify-end space-x-2 w-full">
            <Button
              type="button"
              variant="outline"
              onClick={handleCancel}
              disabled={isPending}
              data-testid="override-cancel-button"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="default"
              isLoading={isPending}
              disabled={isPending}
              data-testid="override-submit-button"
            >
              Submit Override
            </Button>
          </div>
        </DialogFooter>
      </form>
    </Dialog>
  )
}
