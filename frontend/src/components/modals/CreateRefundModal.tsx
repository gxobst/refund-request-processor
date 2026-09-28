import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, UploadCloud, FileText, X } from 'lucide-react'
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
import { cn } from '@/lib/utils'
import type { RefundCreateResponse, ProblemDetails } from '@/types/api'

export interface CreateRefundModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess?: (createdRefund: RefundCreateResponse) => void
  className?: string
}

const ORDER_ID_REGEX = /^ORD-\d{4}$/
const MAX_FILE_SIZE = 5 * 1024 * 1024 // 5,242,880 bytes
const ALLOWED_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']
const ALLOWED_MIME_TYPES = ['image/jpeg', 'image/png', 'image/webp']

function isValidImageType(file: File): boolean {
  if (ALLOWED_MIME_TYPES.includes(file.type)) return true
  const ext = file.name.split('.').pop()?.toLowerCase()
  return Boolean(ext && ALLOWED_EXTENSIONS.includes(ext))
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}

export function CreateRefundModal({
  isOpen,
  onClose,
  onSuccess,
  className,
}: CreateRefundModalProps) {
  const queryClient = useQueryClient()

  const [orderId, setOrderId] = React.useState('')
  const [customerRequestText, setCustomerRequestText] = React.useState('')
  const [selectedFile, setSelectedFile] = React.useState<File | null>(null)
  const [isDragging, setIsDragging] = React.useState(false)

  const [orderIdError, setOrderIdError] = React.useState<string | null>(null)
  const [explanationError, setExplanationError] = React.useState<string | null>(null)
  const [fileError, setFileError] = React.useState<string | null>(null)
  const [mutationError, setMutationError] = React.useState<unknown | null>(null)

  const fileInputRef = React.useRef<HTMLInputElement>(null)

  const resetState = React.useCallback(() => {
    setOrderId('')
    setCustomerRequestText('')
    setSelectedFile(null)
    setIsDragging(false)
    setOrderIdError(null)
    setExplanationError(null)
    setFileError(null)
    setMutationError(null)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }, [])

  // Reset internal state when modal closes
  React.useEffect(() => {
    if (!isOpen) {
      resetState()
    }
  }, [isOpen, resetState])

  const submitMutation = useMutation({
    mutationFn: async (params: refundService.SubmitRefundParams) => {
      return refundService.submitRefund(params)
    },
    onSuccess: async (createdResponse) => {
      await queryClient.invalidateQueries({ queryKey: ['refunds'] })
      onSuccess?.(createdResponse)
      resetState()
      onClose()
    },
    onError: (err) => {
      setMutationError(err)
    },
  })

  const isPending = submitMutation.isPending

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

  const validateFile = (file: File): boolean => {
    if (file.size > MAX_FILE_SIZE) {
      setFileError('File exceeds 5MB size limit')
      setSelectedFile(null)
      return false
    }
    if (!isValidImageType(file)) {
      setFileError('Unsupported file format. Please upload a JPEG, PNG, or WebP image')
      setSelectedFile(null)
      return false
    }
    setFileError(null)
    return true
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0]
      if (validateFile(file)) {
        setSelectedFile(file)
      }
    }
  }

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    if (isPending) return

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0]
      if (validateFile(file)) {
        setSelectedFile(file)
      }
    }
  }

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    if (isPending) return
    setIsDragging(true)
  }

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
  }

  const handleRemoveFile = () => {
    setSelectedFile(null)
    setFileError(null)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleOrderIdBlur = () => {
    const trimmed = orderId.trim()
    if (!trimmed || !ORDER_ID_REGEX.test(trimmed)) {
      setOrderIdError('Order ID must follow the pattern ORD-#### (e.g. ORD-1001)')
    } else {
      setOrderIdError(null)
    }
  }

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault()
    if (isPending) return

    let hasError = false
    const trimmedOrderId = orderId.trim()
    const trimmedExplanation = customerRequestText.trim()

    if (!ORDER_ID_REGEX.test(trimmedOrderId)) {
      setOrderIdError('Order ID must follow the pattern ORD-#### (e.g. ORD-1001)')
      hasError = true
    }

    if (!trimmedExplanation) {
      setExplanationError('Customer explanation is required')
      hasError = true
    }

    if (fileError) {
      hasError = true
    }

    if (hasError) return

    setOrderIdError(null)
    setExplanationError(null)
    setMutationError(null)

    submitMutation.mutate({
      orderId: trimmedOrderId,
      customerRequestText: trimmedExplanation,
      file: selectedFile || null,
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
      title: 'Failed to Submit Refund Request',
      detail:
        (mutationError as Error).message ||
        'An unexpected error occurred while submitting the refund request.',
    }
  }, [mutationError])

  return (
    <Dialog
      isOpen={isOpen}
      onClose={handleClose}
      showCloseButton={!isPending}
      aria-labelledby="create-refund-dialog-title"
      aria-describedby="create-refund-dialog-description"
      className={cn('max-w-lg', className)}
    >
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <DialogHeader>
          <DialogTitle id="create-refund-dialog-title">Submit Refund Request</DialogTitle>
          <DialogDescription id="create-refund-dialog-description">
            Submit a new customer refund request for automated agent evaluation.
          </DialogDescription>
        </DialogHeader>

        {/* RFC 9457 Error Banner */}
        {problemDetails && (
          <div
            role="alert"
            data-testid="create-refund-error-banner"
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

        {/* Order ID Input */}
        <div className="space-y-1.5">
          <label htmlFor="create-order-id" className="text-sm font-medium text-slate-700">
            Order ID (Required)
          </label>
          <Input
            id="create-order-id"
            data-testid="create-order-id-input"
            type="text"
            placeholder="ORD-1001"
            value={orderId}
            onChange={(e) => {
              setOrderId(e.target.value)
              if (orderIdError && ORDER_ID_REGEX.test(e.target.value.trim())) {
                setOrderIdError(null)
              }
            }}
            onBlur={handleOrderIdBlur}
            disabled={isPending}
            hasError={Boolean(orderIdError)}
            aria-describedby={orderIdError ? 'order-id-error' : 'order-id-helper'}
          />
          {orderIdError ? (
            <p
              id="order-id-error"
              data-testid="order-id-error"
              role="alert"
              className="text-xs text-rose-600 font-medium"
            >
              {orderIdError}
            </p>
          ) : (
            <p id="order-id-helper" className="text-xs text-slate-500">
              Must follow pattern ORD-#### (e.g. ORD-1001)
            </p>
          )}
        </div>

        {/* Customer Request Text Textarea */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label
              htmlFor="customer-request-text"
              className="text-sm font-medium text-slate-700"
            >
              Customer Request Text (Required)
            </label>
            <span
              className="text-xs text-slate-500"
              data-testid="character-counter"
              aria-live="polite"
            >
              {customerRequestText.length} characters
            </span>
          </div>
          <Textarea
            id="customer-request-text"
            data-testid="customer-request-textarea"
            rows={4}
            placeholder="Explain the reason for refund request as reported by customer..."
            value={customerRequestText}
            onChange={(e) => {
              setCustomerRequestText(e.target.value)
              if (explanationError && e.target.value.trim()) {
                setExplanationError(null)
              }
            }}
            disabled={isPending}
            hasError={Boolean(explanationError)}
            aria-describedby={explanationError ? 'explanation-error' : undefined}
          />
          {explanationError && (
            <p
              id="explanation-error"
              data-testid="explanation-error"
              role="alert"
              className="text-xs text-rose-600 font-medium"
            >
              {explanationError}
            </p>
          )}
        </div>

        {/* Drag and Drop File Attachment Dropzone */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium text-slate-700">
            Proof / Evidence Attachment (Optional)
          </label>

          <input
            ref={fileInputRef}
            type="file"
            accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
            onChange={handleFileChange}
            disabled={isPending}
            className="hidden"
            data-testid="file-picker-input"
          />

          {!selectedFile ? (
            <div
              data-testid="file-dropzone"
              onClick={() => {
                if (!isPending) {
                  fileInputRef.current?.click()
                }
              }}
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              role="button"
              tabIndex={isPending ? -1 : 0}
              onKeyDown={(e) => {
                if (!isPending && (e.key === 'Enter' || e.key === ' ')) {
                  e.preventDefault()
                  fileInputRef.current?.click()
                }
              }}
              className={cn(
                'flex flex-col items-center justify-center p-4 rounded-lg border-2 border-dashed transition-colors cursor-pointer select-none text-center',
                isDragging
                  ? 'border-sky-500 bg-sky-50'
                  : 'border-slate-300 bg-slate-50/50 hover:bg-slate-50 hover:border-slate-400',
                isPending && 'opacity-50 cursor-not-allowed pointer-events-none'
              )}
            >
              <UploadCloud className="h-7 w-7 text-slate-400 mb-1" />
              <p className="text-xs font-medium text-slate-700">
                Drag and drop image here, or{' '}
                <span className="text-sky-600 hover:underline">browse</span>
              </p>
              <p className="text-[11px] text-slate-400 mt-0.5">
                JPEG, PNG, or WebP up to 5MB
              </p>
            </div>
          ) : (
            <div
              data-testid="selected-file-badge"
              className="flex items-center justify-between p-2.5 rounded-md border border-slate-200 bg-slate-50 text-sm"
            >
              <div className="flex items-center space-x-2 truncate">
                <FileText className="h-4 w-4 text-slate-500 flex-shrink-0" />
                <span
                  className="font-medium text-slate-800 truncate"
                  data-testid="selected-file-name"
                >
                  {selectedFile.name}
                </span>
                <span className="text-xs text-slate-500" data-testid="selected-file-size">
                  ({formatFileSize(selectedFile.size)})
                </span>
              </div>
              <button
                type="button"
                onClick={handleRemoveFile}
                disabled={isPending}
                aria-label="Remove attached file"
                data-testid="remove-file-button"
                className="p-1 rounded text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors disabled:opacity-50"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          )}

          {fileError && (
            <p
              id="file-error"
              data-testid="file-error"
              role="alert"
              className="text-xs text-rose-600 font-medium"
            >
              {fileError}
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
              data-testid="create-refund-cancel-button"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="default"
              isLoading={isPending}
              disabled={isPending}
              data-testid="create-refund-submit-button"
            >
              Submit Refund
            </Button>
          </div>
        </DialogFooter>
      </form>
    </Dialog>
  )
}
