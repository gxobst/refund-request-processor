import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Info,
  Send,
  UploadCloud,
  X,
} from 'lucide-react'
import * as refundService from '@/services/refundService'
import { validateImageDimensions, compressImage } from '@/utils/imageUtils'
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

export interface CustomerClarificationModalProps {
  refundId: string | null
  isOpen: boolean
  onClose: () => void
  onSuccess?: (updatedRecord: RefundRecord) => void
}

const MAX_FILE_SIZE = 5 * 1024 * 1024 // 5MB
const ALLOWED_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']
const ALLOWED_MIME_TYPES = ['image/jpeg', 'image/png', 'image/webp']

function isValidImageType(file: File): boolean {
  if (ALLOWED_MIME_TYPES.includes(file.type.toLowerCase())) return true
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

export function CustomerClarificationModal({
  refundId,
  isOpen,
  onClose,
  onSuccess,
}: CustomerClarificationModalProps) {
  const queryClient = useQueryClient()

  const [responseText, setResponseText] = React.useState('')
  const [selectedFile, setSelectedFile] = React.useState<File | null>(null)
  const [isDragging, setIsDragging] = React.useState(false)
  const [responseError, setResponseError] = React.useState<string | null>(null)
  const [fileError, setFileError] = React.useState<string | null>(null)
  const [dimensionError, setDimensionError] = React.useState<string | null>(null)
  const [imageInfo, setImageInfo] = React.useState<{ width: number; height: number; size: number } | null>(null)
  const [isValidatingImage, setIsValidatingImage] = React.useState(false)
  const [mutationError, setMutationError] = React.useState<unknown | null>(null)
  const [isSubmitted, setIsSubmitted] = React.useState(false)

  const fileInputRef = React.useRef<HTMLInputElement>(null)

  // Fetch refund details to display order ID and inquiry prompt
  const {
    data: refund,
    isLoading: isRefundLoading,
  } = useQuery<RefundRecord, Error>({
    queryKey: ['refund', refundId],
    queryFn: () => refundService.getRefundById(refundId!),
    enabled: isOpen && Boolean(refundId),
  })

  const resetState = React.useCallback(() => {
    setResponseText('')
    setSelectedFile(null)
    setIsDragging(false)
    setResponseError(null)
    setFileError(null)
    setDimensionError(null)
    setImageInfo(null)
    setIsValidatingImage(false)
    setMutationError(null)
    setIsSubmitted(false)
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
    mutationFn: async (payload: refundService.SubmitClarificationPayload) => {
      if (!refundId) {
        throw new Error('Refund ID is required to submit clarification')
      }
      return refundService.submitClarification(refundId, payload)
    },
    onSuccess: async (updatedRecord) => {
      setIsSubmitted(true)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['refund', refundId] }),
        queryClient.invalidateQueries({ queryKey: ['refunds'] }),
      ])
      onSuccess?.(updatedRecord)
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

  const handleDone = () => {
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

  const processSelectedFile = async (file: File) => {
    setFileError(null)
    setDimensionError(null)
    setImageInfo(null)

    if (!validateFile(file)) {
      return
    }

    // Fallback for legacy environments where URL.createObjectURL is not available
    if (typeof window !== 'undefined' && typeof window.URL?.createObjectURL !== 'function') {
      setSelectedFile(file)
      return
    }

    setIsValidatingImage(true)
    try {
      const dimensionResult = await validateImageDimensions(file)
      if (!dimensionResult.valid) {
        setSelectedFile(null)
        setImageInfo(null)
        setDimensionError(
          dimensionResult.error ||
            'Unable to decode image dimensions. Please verify the file is a valid image.'
        )
        if (fileInputRef.current) {
          fileInputRef.current.value = ''
        }
        return
      }

      const compressed = await compressImage(file)
      setSelectedFile(compressed)
      setImageInfo({
        width: dimensionResult.width,
        height: dimensionResult.height,
        size: compressed.size,
      })
      setDimensionError(null)
    } catch {
      setSelectedFile(null)
      setImageInfo(null)
      setDimensionError('Unable to decode image dimensions. Please verify the file is a valid image.')
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    } finally {
      setIsValidatingImage(false)
    }
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0]
      void processSelectedFile(file)
    }
  }

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    if (isPending) return

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0]
      void processSelectedFile(file)
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
    setDimensionError(null)
    setImageInfo(null)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault()
    if (isPending || isValidatingImage) return

    const trimmedResponse = responseText.trim()
    if (!trimmedResponse) {
      setResponseError('Clarification response is required')
      return
    }

    if (fileError || dimensionError) {
      return
    }

    setResponseError(null)
    setMutationError(null)

    if (selectedFile) {
      submitMutation.mutate({
        responseText: trimmedResponse,
        evidenceFile: selectedFile,
      })
    } else {
      submitMutation.mutate({
        responseText: trimmedResponse,
      })
    }
  }

  // Extract Order ID and Agent's Inquiry Prompt
  const rec = (refund || {}) as Record<string, unknown>
  const orderId = refund?.orderId || (rec.order_id as string) || (isRefundLoading ? 'Loading...' : 'N/A')

  const inquiryPrompt = React.useMemo(() => {
    // 1. Try clarificationHistory
    const turns = refund?.clarificationHistory || (rec.clarification_history as any[]) || []
    if (Array.isArray(turns) && turns.length > 0) {
      for (let i = turns.length - 1; i >= 0; i--) {
        const turn = turns[i]
        const p = turn?.prompt ?? turn?.inquiry_prompt ?? (turn as any)?.clarification_prompt
        if (p && typeof p === 'string' && p.trim()) {
          return p.trim()
        }
      }
    }

    // 2. Try clarificationEmailText
    const email = refund?.clarificationEmailText ?? (rec.clarification_email_text as string) ?? null
    if (email && typeof email === 'string' && email.trim()) {
      return email.trim()
    }

    // 3. Try direct clarificationPrompt
    const prompt = refund?.clarificationPrompt ?? (rec.clarification_prompt as string) ?? null
    if (prompt && typeof prompt === 'string' && prompt.trim()) {
      return prompt.trim()
    }

    return null
  }, [refund, rec])

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
      title: 'Submission Failed',
      detail:
        (mutationError as Error).message ||
        'An unexpected error occurred while submitting clarification.',
    }
  }, [mutationError])

  return (
    <Dialog
      isOpen={isOpen}
      onClose={handleClose}
      showCloseButton={!isPending}
      aria-labelledby="customer-clarification-dialog-title"
      aria-describedby="customer-clarification-dialog-description"
      className="max-w-lg"
    >
      <DialogHeader>
        <DialogTitle id="customer-clarification-dialog-title">
          Customer Clarification Portal
        </DialogTitle>
        <DialogDescription id="customer-clarification-dialog-description">
          Order ID: <span data-testid="clarification-order-id" className="font-semibold text-slate-800">{orderId}</span>
        </DialogDescription>
      </DialogHeader>

      {isSubmitted ? (
        <div data-testid="clarification-success-state" className="space-y-4 py-4 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
            <CheckCircle2 className="h-6 w-6" />
          </div>
          <div className="space-y-1">
            <h3 className="text-base font-semibold text-slate-900">
              Clarification Submitted Successfully
            </h3>
            <p className="text-sm text-slate-600 max-w-sm mx-auto leading-relaxed">
              Thank you for providing the requested clarification. Your response and evidence have been received and the automated refund evaluation workflow has resumed.
            </p>
          </div>
          <DialogFooter className="mt-6 sm:justify-center">
            <Button
              type="button"
              variant="default"
              onClick={handleDone}
              data-testid="clarification-done-button"
              className="bg-slate-900 text-white hover:bg-slate-800"
            >
              Done
            </Button>
          </DialogFooter>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-5" noValidate>
          {/* RFC 9457 Error Banner */}
          {problemDetails && (
            <div
              role="alert"
              data-testid="clarification-error-banner"
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

          {/* Inquiry Prompt Display or Fallback Guidance */}
          {inquiryPrompt ? (
            <div className="rounded-lg border border-sky-100 bg-sky-50/70 p-3.5 space-y-1">
              <p className="text-xs font-semibold text-sky-900 uppercase tracking-wide">
                Agent Inquiry / Request
              </p>
              <p
                data-testid="clarification-inquiry-prompt"
                className="text-sm text-slate-800 leading-relaxed font-medium"
              >
                {inquiryPrompt}
              </p>
            </div>
          ) : (
            <div
              data-testid="clarification-fallback-guidance"
              className="rounded-lg border border-slate-200 bg-slate-50 p-3.5 space-y-1"
            >
              <p className="text-xs font-semibold text-slate-700 uppercase tracking-wide">
                Clarification Guidance
              </p>
              <p className="text-sm text-slate-600 leading-relaxed">
                Additional information or proof has been requested for this refund request. Please provide clarification below to proceed.
              </p>
            </div>
          )}

          {/* Informational Guidance Callout */}
          <div
            data-testid="clarification-guidance-callout"
            className="rounded-lg border border-sky-200 bg-sky-50 p-3 text-sky-900 flex items-start space-x-2.5 text-xs"
          >
            <Info className="h-4 w-4 text-sky-600 flex-shrink-0 mt-0.5" />
            <div className="space-y-1">
              <p className="font-semibold text-sky-900">Clarification & Evidence Guidelines</p>
              <p className="text-sky-700 leading-relaxed">
                Accepted file formats: JPEG, PNG, or WebP up to 5MB. Providing detailed explanation and photos helps expedite your refund review.
              </p>
            </div>
          </div>

          {/* Clarification Response Textarea */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label htmlFor="clarification-response-textarea" className="text-sm font-medium text-slate-700">
                Your Explanation / Response <span className="text-rose-500">*</span>
              </label>
              <span
                className="text-xs text-slate-500"
                data-testid="clarification-character-counter"
                aria-live="polite"
              >
                {responseText.length} characters
              </span>
            </div>
            <Textarea
              id="clarification-response-textarea"
              data-testid="clarification-response-textarea"
              rows={4}
              placeholder="Describe additional details or context regarding your refund request..."
              value={responseText}
              onChange={(e) => {
                setResponseText(e.target.value)
                if (responseError && e.target.value.trim()) {
                  setResponseError(null)
                }
              }}
              disabled={isPending}
              hasError={Boolean(responseError)}
              aria-describedby={responseError ? 'clarification-response-error' : undefined}
            />
            {responseError && (
              <p
                id="clarification-response-error"
                data-testid="clarification-response-error"
                role="alert"
                className="text-xs text-rose-600 font-medium"
              >
                {responseError}
              </p>
            )}
          </div>

          {/* Drag & Drop File Upload Input */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-slate-700">
              Evidence Image (Optional)
            </label>

            {dimensionError && (
              <div
                role="alert"
                data-testid="evidence-dimension-error"
                className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-rose-900 flex items-start space-x-2 text-xs"
              >
                <AlertCircle className="h-4 w-4 text-rose-600 flex-shrink-0 mt-0.5" />
                <span className="font-medium">{dimensionError}</span>
              </div>
            )}

            <input
              ref={fileInputRef}
              type="file"
              accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
              onChange={handleFileChange}
              disabled={isPending || isValidatingImage}
              className="hidden"
              data-testid="clarification-file-input"
            />

            {!selectedFile ? (
              <div
                data-testid="clarification-drop-zone"
                onClick={() => {
                  if (!isPending && !isValidatingImage) {
                    fileInputRef.current?.click()
                  }
                }}
                onDrop={handleDrop}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                role="button"
                tabIndex={isPending || isValidatingImage ? -1 : 0}
                onKeyDown={(e) => {
                  if (!isPending && !isValidatingImage && (e.key === 'Enter' || e.key === ' ')) {
                    e.preventDefault()
                    fileInputRef.current?.click()
                  }
                }}
                className={cn(
                  'flex flex-col items-center justify-center p-4 rounded-lg border-2 border-dashed transition-colors cursor-pointer select-none text-center',
                  isDragging
                    ? 'border-sky-500 bg-sky-50'
                    : 'border-slate-300 bg-slate-50/50 hover:bg-slate-50 hover:border-slate-400',
                  (isPending || isValidatingImage) && 'opacity-50 cursor-not-allowed pointer-events-none'
                )}
              >
                <UploadCloud className="h-7 w-7 text-slate-400 mb-1" />
                <p className="text-xs font-medium text-slate-700">
                  {isValidatingImage ? (
                    'Validating and compressing image...'
                  ) : (
                    <>
                      Drag and drop evidence image here, or{' '}
                      <span className="text-sky-600 hover:underline">browse</span>
                    </>
                  )}
                </p>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  JPEG, PNG, or WebP up to 5MB
                </p>
              </div>
            ) : (
              <div
                data-testid="clarification-file-preview"
                className="flex items-center justify-between p-2.5 rounded-md border border-slate-200 bg-slate-50 text-sm"
              >
                <div className="flex items-center space-x-2 truncate">
                  <FileText className="h-4 w-4 text-slate-500 flex-shrink-0" />
                  <span
                    className="font-medium text-slate-800 truncate"
                    data-testid="clarification-file-name"
                  >
                    {selectedFile.name}
                  </span>
                  <span
                    className="text-xs text-slate-500"
                    data-testid="clarification-file-size"
                  >
                    ({formatFileSize(selectedFile.size)})
                  </span>
                  {imageInfo && (
                    <span
                      data-testid="evidence-compressed-badge"
                      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200"
                    >
                      {imageInfo.width}x{imageInfo.height} ({formatFileSize(selectedFile.size)})
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={handleRemoveFile}
                  disabled={isPending || isValidatingImage}
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
                id="clarification-file-error"
                data-testid="clarification-file-error"
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
                data-testid="clarification-cancel-button"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="default"
                isLoading={isPending}
                disabled={isPending || isValidatingImage}
                data-testid="clarification-submit-button"
                className="bg-slate-900 text-white hover:bg-slate-800"
              >
                <Send className="h-4 w-4 mr-1.5" />
                Submit Clarification
              </Button>
            </div>
          </DialogFooter>
        </form>
      )}
    </Dialog>
  )
}
