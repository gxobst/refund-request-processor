import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Info, Send } from 'lucide-react'
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
import { Input } from '@/components/ui/Input'
import { Textarea } from '@/components/ui/Textarea'
import type { RefundRecord, ProblemDetails } from '@/types/api'

export interface RequestProofModalProps {
  refundId: string | null
  isOpen: boolean
  onClose: () => void
  orderId?: string | null
  onSuccess?: (updatedRecord: RefundRecord) => void
}

export function RequestProofModal({
  refundId,
  isOpen,
  onClose,
  orderId,
  onSuccess,
}: RequestProofModalProps) {
  const queryClient = useQueryClient()

  const [customerName, setCustomerName] = React.useState('')
  const [proofPrompt, setProofPrompt] = React.useState('')
  const [validationError, setValidationError] = React.useState<string | null>(null)
  const [mutationError, setMutationError] = React.useState<unknown | null>(null)

  const resetState = React.useCallback(() => {
    setCustomerName('')
    setProofPrompt('')
    setValidationError(null)
    setMutationError(null)
  }, [])

  // Reset internal state whenever modal is closed
  React.useEffect(() => {
    if (!isOpen) {
      resetState()
    }
  }, [isOpen, resetState])

  const requestProofMutation = useMutation({
    mutationFn: async (payload: refundService.RequestReviewerProofPayload) => {
      if (!refundId) {
        throw new Error('Refund ID is required to request customer proof')
      }
      return refundService.requestReviewerProof(refundId, payload)
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

  const isPending = requestProofMutation.isPending

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

    const trimmedPrompt = proofPrompt.trim()
    if (!trimmedPrompt) {
      setValidationError('Inquiry prompt is required')
      return
    }

    setValidationError(null)
    setMutationError(null)

    requestProofMutation.mutate({
      proofPrompt: trimmedPrompt,
      customerName: customerName.trim() || undefined,
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
      title: 'Proof Request Failed',
      detail:
        (mutationError as Error).message ||
        'An unexpected error occurred while submitting the proof request.',
    }
  }, [mutationError])

  return (
    <Dialog
      isOpen={isOpen}
      onClose={handleClose}
      showCloseButton={!isPending}
      aria-labelledby="request-proof-dialog-title"
      aria-describedby="request-proof-dialog-description"
      className="max-w-lg"
    >
      <form onSubmit={handleSubmit} className="space-y-5" noValidate>
        <DialogHeader>
          <DialogTitle id="request-proof-dialog-title">Request Customer Proof</DialogTitle>
          <DialogDescription id="request-proof-dialog-description">
            Order ID: <span className="font-semibold text-slate-800">{orderId || 'N/A'}</span>
          </DialogDescription>
        </DialogHeader>

        {/* RFC 9457 Error Banner */}
        {problemDetails && (
          <div
            role="alert"
            data-testid="request-proof-error-banner"
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

        {/* Informative Guidance Callout */}
        <div
          data-testid="proof-guidance-callout"
          className="rounded-lg border border-sky-200 bg-sky-50 p-3 text-sky-900 flex items-start space-x-2.5 text-xs"
        >
          <Info className="h-4 w-4 text-sky-600 flex-shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="font-semibold text-sky-900">Upload & Workflow Guidance</p>
            <p className="text-sky-700 leading-relaxed">
              Customer uploads support JPEG, PNG, or WebP up to 5MB. Submitting this proof inquiry
              transitions the refund status to{' '}
              <span className="font-medium text-sky-900">awaiting_clarification</span>, sends an
              inquiry email to the customer, and automatically resumes the evaluation workflow upon
              customer response.
            </p>
          </div>
        </div>

        {/* Optional Customer Name Input */}
        <div className="space-y-1.5">
          <label htmlFor="customer-name" className="text-sm font-medium text-slate-700">
            Customer Name (Optional)
          </label>
          <Input
            id="customer-name"
            data-testid="customer-name-input"
            type="text"
            placeholder="e.g. Jane Doe (personalizes customer email greeting)"
            value={customerName}
            onChange={(e) => setCustomerName(e.target.value)}
            disabled={isPending}
          />
        </div>

        {/* Mandatory Proof Inquiry Prompt Textarea */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label htmlFor="proof-inquiry-prompt" className="text-sm font-medium text-slate-700">
              Proof Inquiry Prompt (Required)
            </label>
            <span
              className="text-xs text-slate-500"
              data-testid="character-counter"
              aria-live="polite"
            >
              {proofPrompt.length} characters
            </span>
          </div>
          <Textarea
            id="proof-inquiry-prompt"
            data-testid="proof-inquiry-textarea"
            rows={4}
            placeholder="Describe specifically what additional evidence or photos the customer needs to provide (e.g., clear photo of shipping packaging, damaged component, or tracking slip)..."
            value={proofPrompt}
            onChange={(e) => {
              setProofPrompt(e.target.value)
              if (validationError && e.target.value.trim()) {
                setValidationError(null)
              }
            }}
            disabled={isPending}
            hasError={Boolean(validationError)}
            aria-describedby={validationError ? 'prompt-error' : undefined}
          />
          {validationError && (
            <p
              id="prompt-error"
              data-testid="prompt-error"
              role="alert"
              className="text-xs text-rose-600 font-medium"
            >
              {validationError}
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
              data-testid="request-proof-cancel-button"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="default"
              isLoading={isPending}
              disabled={isPending}
              data-testid="request-proof-submit-button"
            >
              <Send className="h-4 w-4 mr-1.5" />
              Send Request
            </Button>
          </div>
        </DialogFooter>
      </form>
    </Dialog>
  )
}
