import * as React from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Sliders,
  Check,
  AlertCircle,
  Loader2,
  Calendar,
  DollarSign,
  Camera,
  Truck,
  History,
  RotateCcw,
  Clock,
  User,
} from 'lucide-react'
import {
  Dialog,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/Dialog'
import { Button } from '@/components/ui/Button'
import {
  fetchPolicies,
  updatePolicy,
  fetchPolicyHistory,
  rollbackPolicy,
  type PolicyRule,
  type UpdatePolicyPayload,
  type PolicyAuditEntry,
} from '@/services/policyService'
import { isApiError } from '@/services/apiClient'
import { cn } from '@/lib/utils'


export interface PolicyRuleViewerModalProps {
  isOpen: boolean
  onClose: () => void
}

const CATEGORY_LABELS: Record<string, string> = {
  damaged: 'Damaged Item',
  wrong_item: 'Wrong Item',
  changed_mind: 'Changed Mind',
  late_delivery: 'Late Delivery',
  missing_item: 'Missing Item',
}

interface CategoryCardProps {
  rule: PolicyRule
  onUpdate: (category: string, payload: UpdatePolicyPayload) => Promise<void>
  isUpdating: boolean
}

function CategoryPolicyCard({ rule, onUpdate, isUpdating }: CategoryCardProps) {
  const [returnWindow, setReturnWindow] = React.useState(String(rule.return_window_days))
  const [maxAmount, setMaxAmount] = React.useState(String(rule.max_refund_amount))
  const [autoApprove, setAutoApprove] = React.useState(String(rule.auto_approve_threshold))
  const [requiresProof, setRequiresProof] = React.useState(rule.requires_proof)

  const [errors, setErrors] = React.useState<{
    returnWindow?: string
    maxAmount?: string
    autoApprove?: string
  }>({})
  const [successMessage, setSuccessMessage] = React.useState<string | null>(null)
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null)

  // Keep local inputs in sync when rule props change from server
  React.useEffect(() => {
    setReturnWindow(String(rule.return_window_days))
    setMaxAmount(String(rule.max_refund_amount))
    setAutoApprove(String(rule.auto_approve_threshold))
    setRequiresProof(rule.requires_proof)
    setErrors({})
  }, [
    rule.return_window_days,
    rule.max_refund_amount,
    rule.auto_approve_threshold,
    rule.requires_proof,
  ])

  const validate = (): boolean => {
    const newErrors: {
      returnWindow?: string
      maxAmount?: string
      autoApprove?: string
    } = {}

    // return_window_days validation
    if (returnWindow.trim() === '') {
      newErrors.returnWindow = 'Return window is required.'
    } else {
      const rw = Number(returnWindow)
      if (isNaN(rw) || !Number.isInteger(rw) || rw <= 0) {
        newErrors.returnWindow = 'Return window must be a positive integer greater than 0.'
      }
    }

    // max_refund_amount validation
    if (maxAmount.trim() === '') {
      newErrors.maxAmount = 'Maximum refund amount is required.'
    } else {
      const ma = Number(maxAmount)
      if (isNaN(ma) || ma < 0) {
        newErrors.maxAmount = 'Maximum refund amount must be a non-negative number.'
      }
    }

    // auto_approve_threshold validation
    if (autoApprove.trim() === '') {
      newErrors.autoApprove = 'Auto-approve threshold is required.'
    } else {
      const aa = Number(autoApprove)
      if (isNaN(aa) || aa < 0) {
        newErrors.autoApprove = 'Auto-approve threshold must be a non-negative number.'
      }
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSuccessMessage(null)
    setErrorMessage(null)

    if (!validate()) {
      return
    }

    try {
      await onUpdate(rule.category, {
        return_window_days: parseInt(returnWindow, 10),
        max_refund_amount: parseFloat(maxAmount),
        auto_approve_threshold: parseFloat(autoApprove),
        requires_proof: requiresProof,
      })
      setSuccessMessage('Policy rules updated successfully.')
      setErrors({})
    } catch (err: unknown) {
      if (isApiError(err)) {
        setErrorMessage(err.problem.detail || err.message)
      } else if (err instanceof Error) {
        setErrorMessage(err.message)
      } else {
        setErrorMessage('Failed to update policy rules.')
      }
    }
  }

  const categoryLabel = CATEGORY_LABELS[rule.category] || rule.category

  return (
    <div
      data-testid={`policy-card-${rule.category}`}
      className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm hover:shadow transition-shadow"
    >
      {/* Category Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3 mb-3">
        <div className="flex items-center space-x-2">
          <span
            data-testid={`category-badge-${rule.category}`}
            className="inline-flex items-center rounded-md bg-slate-900 px-2.5 py-1 text-xs font-semibold text-white tracking-wide uppercase"
          >
            {categoryLabel}
          </span>
          <span className="text-xs text-slate-500 font-mono">({rule.category})</span>
        </div>

        {/* Eligible Delivery Statuses */}
        <div
          data-testid={`policy-eligible-statuses-${rule.category}`}
          className="flex items-center space-x-1 text-xs text-slate-600"
        >
          <Truck className="h-3.5 w-3.5 text-slate-400 mr-1" aria-hidden="true" />
          <span className="text-slate-400 mr-1 font-medium">Eligible:</span>
          {rule.eligible_delivery_statuses.map((st) => (
            <span
              key={st}
              className="inline-flex items-center rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-700 border border-slate-200"
            >
              {st}
            </span>
          ))}
        </div>
      </div>

      {/* Current Values Display Bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4 bg-slate-50 p-2.5 rounded-md border border-slate-100 text-xs">
        <div>
          <span className="text-slate-500 block text-[11px]">Return Window</span>
          <span
            data-testid={`policy-return-window-${rule.category}`}
            className="font-semibold text-slate-900"
          >
            {rule.return_window_days} days
          </span>
        </div>
        <div>
          <span className="text-slate-500 block text-[11px]">Max Refund</span>
          <span
            data-testid={`policy-max-amount-${rule.category}`}
            className="font-semibold text-slate-900"
          >
            ${rule.max_refund_amount.toFixed(2)}
          </span>
        </div>
        <div>
          <span className="text-slate-500 block text-[11px]">Auto-Approve</span>
          <span
            data-testid={`policy-auto-approve-${rule.category}`}
            className="font-semibold text-slate-900"
          >
            ${rule.auto_approve_threshold.toFixed(2)}
          </span>
        </div>
        <div>
          <span className="text-slate-500 block text-[11px]">Proof Required</span>
          <span
            data-testid={`policy-requires-proof-${rule.category}`}
            className={cn(
              'font-semibold inline-flex items-center',
              rule.requires_proof ? 'text-amber-700' : 'text-slate-700'
            )}
          >
            {rule.requires_proof ? 'Yes' : 'No'}
          </span>
        </div>
      </div>

      {/* Optional edit button for test compatibility */}
      <button
        type="button"
        data-testid={`edit-policy-${rule.category}`}
        className="sr-only"
        onClick={() => {
          const el = document.getElementById(`input-return-window-${rule.category}`)
          el?.focus()
        }}
      >
        Edit {categoryLabel}
      </button>

      {/* Editable Form */}
      <form onSubmit={handleSubmit} noValidate className="space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {/* Return Window Input */}
          <div>
            <label
              htmlFor={`input-return-window-${rule.category}`}
              className="block text-xs font-medium text-slate-700 mb-1"
            >
              Return Window (days)
            </label>
            <div className="relative">
              <Calendar className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
              <input
                id={`input-return-window-${rule.category}`}
                data-testid={`input-return-window-${rule.category}`}
                type="number"
                min="1"
                step="1"
                value={returnWindow}
                onChange={(e) => {
                  setReturnWindow(e.target.value)
                  if (errors.returnWindow) setErrors((prev) => ({ ...prev, returnWindow: undefined }))
                }}
                disabled={isUpdating}
                className={cn(
                  'w-full pl-8 pr-2.5 py-1.5 text-xs rounded-md border bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-slate-400',
                  errors.returnWindow ? 'border-rose-300 ring-rose-200' : 'border-slate-300'
                )}
              />
            </div>
            {errors.returnWindow && (
              <p
                data-testid={`error-return-window-${rule.category}`}
                className="mt-1 text-[11px] text-rose-600 font-medium"
              >
                {errors.returnWindow}
              </p>
            )}
          </div>

          {/* Max Refund Amount Input */}
          <div>
            <label
              htmlFor={`input-max-amount-${rule.category}`}
              className="block text-xs font-medium text-slate-700 mb-1"
            >
              Max Refund Amount ($)
            </label>
            <div className="relative">
              <DollarSign className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
              <input
                id={`input-max-amount-${rule.category}`}
                data-testid={`input-max-amount-${rule.category}`}
                type="number"
                min="0"
                step="0.01"
                value={maxAmount}
                onChange={(e) => {
                  setMaxAmount(e.target.value)
                  if (errors.maxAmount) setErrors((prev) => ({ ...prev, maxAmount: undefined }))
                }}
                disabled={isUpdating}
                className={cn(
                  'w-full pl-8 pr-2.5 py-1.5 text-xs rounded-md border bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-slate-400',
                  errors.maxAmount ? 'border-rose-300 ring-rose-200' : 'border-slate-300'
                )}
              />
            </div>
            {errors.maxAmount && (
              <p
                data-testid={`error-max-amount-${rule.category}`}
                className="mt-1 text-[11px] text-rose-600 font-medium"
              >
                {errors.maxAmount}
              </p>
            )}
          </div>

          {/* Auto-Approve Threshold Input */}
          <div>
            <label
              htmlFor={`input-auto-approve-${rule.category}`}
              className="block text-xs font-medium text-slate-700 mb-1"
            >
              Auto-Approve Threshold ($)
            </label>
            <div className="relative">
              <DollarSign className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
              <input
                id={`input-auto-approve-${rule.category}`}
                data-testid={`input-auto-approve-${rule.category}`}
                type="number"
                min="0"
                step="0.01"
                value={autoApprove}
                onChange={(e) => {
                  setAutoApprove(e.target.value)
                  if (errors.autoApprove) setErrors((prev) => ({ ...prev, autoApprove: undefined }))
                }}
                disabled={isUpdating}
                className={cn(
                  'w-full pl-8 pr-2.5 py-1.5 text-xs rounded-md border bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-slate-400',
                  errors.autoApprove ? 'border-rose-300 ring-rose-200' : 'border-slate-300'
                )}
              />
            </div>
            {errors.autoApprove && (
              <p
                data-testid={`error-auto-approve-${rule.category}`}
                className="mt-1 text-[11px] text-rose-600 font-medium"
              >
                {errors.autoApprove}
              </p>
            )}
          </div>
        </div>

        {/* Requires Proof Toggle and Submit Button */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
          <label className="flex items-center space-x-2 text-xs font-medium text-slate-700 cursor-pointer">
            <input
              id={`input-requires-proof-${rule.category}`}
              data-testid={`input-requires-proof-${rule.category}`}
              type="checkbox"
              checked={requiresProof}
              onChange={(e) => setRequiresProof(e.target.checked)}
              disabled={isUpdating}
              className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-400"
            />
            <span className="flex items-center">
              <Camera className="h-3.5 w-3.5 text-slate-400 mr-1" />
              Require customer photo evidence
            </span>
          </label>

          <Button
            type="submit"
            size="sm"
            disabled={isUpdating}
            data-testid={`save-policy-${rule.category}`}
            className="bg-slate-900 text-white hover:bg-slate-800 text-xs px-3 py-1.5"
          >
            {isUpdating ? (
              <>
                <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                Saving...
              </>
            ) : (
              'Save Rules'
            )}
          </Button>
        </div>

        {/* Feedback Alerts */}
        {successMessage && (
          <div
            data-testid={`success-message-${rule.category}`}
            role="status"
            className="flex items-center space-x-1.5 p-2 rounded-md bg-emerald-50 text-emerald-800 border border-emerald-200 text-xs"
          >
            <Check className="h-3.5 w-3.5 text-emerald-600 shrink-0" />
            <span>{successMessage}</span>
          </div>
        )}

        {errorMessage && (
          <div
            data-testid={`error-alert-${rule.category}`}
            role="alert"
            className="flex items-center space-x-1.5 p-2 rounded-md bg-rose-50 text-rose-800 border border-rose-200 text-xs"
          >
            <AlertCircle className="h-3.5 w-3.5 text-rose-600 shrink-0" />
            <span>{errorMessage}</span>
          </div>
        )}
      </form>
    </div>
  )
}

function formatDiffValue(val: unknown): string {
  if (val === undefined || val === null) return 'none'
  if (typeof val === 'boolean') return val ? 'Yes' : 'No'
  if (Array.isArray(val)) return val.join(', ')
  if (typeof val === 'number') return String(val)
  return String(val)
}

export function PolicyRuleViewerModal({ isOpen, onClose }: PolicyRuleViewerModalProps) {
  const queryClient = useQueryClient()

  const [activeTab, setActiveTab] = React.useState<'active' | 'history'>('active')
  const [historyCategory, setHistoryCategory] = React.useState<string>('all')
  const [rollingBackId, setRollingBackId] = React.useState<string | null>(null)

  const {
    data: policies = [],
    isLoading,
    isError,
    error,
  } = useQuery<PolicyRule[]>({
    queryKey: ['policies'],
    queryFn: fetchPolicies,
    enabled: isOpen,
  })

  const {
    data: historyEntries = [],
    isLoading: isHistoryLoading,
    isError: isHistoryError,
    error: historyError,
  } = useQuery<PolicyAuditEntry[]>({
    queryKey: ['policies', 'history', historyCategory],
    queryFn: () =>
      fetchPolicyHistory(historyCategory === 'all' ? undefined : historyCategory),
    enabled: isOpen,
  })

  const [updatingCategory, setUpdatingCategory] = React.useState<string | null>(null)
  const [globalError, setGlobalError] = React.useState<string | null>(null)
  const [globalSuccess, setGlobalSuccess] = React.useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: async ({
      category,
      payload,
    }: {
      category: string
      payload: UpdatePolicyPayload
    }) => {
      return updatePolicy(category, payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['policies'] })
      queryClient.invalidateQueries({ queryKey: ['policies', 'history'] })
      setGlobalSuccess('Policy rule updated successfully.')
      setGlobalError(null)
    },
    onError: (err: unknown) => {
      const msg = isApiError(err)
        ? err.problem.detail || err.message
        : err instanceof Error
        ? err.message
        : 'Failed to update policy'
      setGlobalError(msg)
      setGlobalSuccess(null)
    },
    onSettled: () => {
      setUpdatingCategory(null)
    },
  })

  const rollbackMutation = useMutation({
    mutationFn: async ({
      category,
      auditId,
    }: {
      category: string
      auditId?: string
    }) => {
      return rollbackPolicy(category, auditId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['policies'] })
      queryClient.invalidateQueries({ queryKey: ['policies', 'history'] })
      setGlobalSuccess('Policy restored to previous state successfully.')
      setGlobalError(null)
    },
    onError: (err: unknown) => {
      const msg = isApiError(err)
        ? err.problem.detail || err.message
        : err instanceof Error
        ? err.message
        : 'Failed to rollback policy'
      setGlobalError(msg)
      setGlobalSuccess(null)
    },
    onSettled: () => {
      setRollingBackId(null)
    },
  })

  const handleRollback = async (category: string, auditId: string) => {
    setRollingBackId(auditId)
    setGlobalError(null)
    setGlobalSuccess(null)
    try {
      await rollbackMutation.mutateAsync({ category, auditId })
    } catch {
      // Handled in onError
    }
  }

  const handleUpdate = async (category: string, payload: UpdatePolicyPayload) => {
    setUpdatingCategory(category)
    setGlobalError(null)
    setGlobalSuccess(null)
    await mutation.mutateAsync({ category, payload })
  }

  return (
    <Dialog
      isOpen={isOpen}
      onClose={onClose}
      aria-labelledby="policy-rule-viewer-title"
      className="max-w-4xl max-h-[90vh] overflow-y-auto"
    >
      <div data-testid="policy-rule-viewer-modal" className="space-y-4">
        {/* Modal Header */}
        <DialogHeader>
          <div className="flex items-center space-x-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 text-white shadow-sm">
              <Sliders className="h-4 w-4 text-emerald-400" aria-hidden="true" />
            </div>
            <div>
              <DialogTitle id="policy-rule-viewer-title" className="text-base sm:text-lg">
                Refund Policy Configuration
              </DialogTitle>
              <DialogDescription className="text-xs sm:text-sm text-slate-500">
                Inspect and dynamically update refund policy thresholds across all product categories.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {/* Navigation Tabs */}
        <div className="flex border-b border-slate-200">
          <button
            type="button"
            data-testid="tab-active-policies"
            onClick={() => {
              setActiveTab('active')
              setGlobalError(null)
              setGlobalSuccess(null)
            }}
            className={cn(
              'flex items-center px-4 py-2 text-xs sm:text-sm font-medium border-b-2 -mb-px transition-colors',
              activeTab === 'active'
                ? 'border-slate-900 text-slate-900 font-semibold'
                : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
            )}
          >
            <Sliders className="h-4 w-4 mr-2" />
            Active Policies
          </button>
          <button
            type="button"
            data-testid="tab-policy-history"
            onClick={() => {
              setActiveTab('history')
              setGlobalError(null)
              setGlobalSuccess(null)
            }}
            className={cn(
              'flex items-center px-4 py-2 text-xs sm:text-sm font-medium border-b-2 -mb-px transition-colors',
              activeTab === 'history'
                ? 'border-slate-900 text-slate-900 font-semibold'
                : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
            )}
          >
            <History className="h-4 w-4 mr-2" />
            Version History
          </button>
        </div>

        {/* Global Notifications */}
        {globalSuccess && (
          <div
            data-testid="policy-success-toast"
            role="status"
            className="flex items-center space-x-2 p-2.5 rounded-md bg-emerald-50 text-emerald-800 border border-emerald-200 text-xs"
          >
            <Check className="h-4 w-4 text-emerald-600 shrink-0" />
            <span>{globalSuccess}</span>
          </div>
        )}

        {globalError && (
          <div
            data-testid="policy-error-alert"
            role="alert"
            className="flex items-center space-x-2 p-2.5 rounded-md bg-rose-50 text-rose-800 border border-rose-200 text-xs"
          >
            <AlertCircle className="h-4 w-4 text-rose-600 shrink-0" />
            <span>{globalError}</span>
          </div>
        )}

        {/* Content Body */}
        {activeTab === 'active' ? (
          isLoading ? (
            <div className="flex flex-col items-center justify-center py-12 space-y-3">
              <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
              <p className="text-xs text-slate-500">Loading active refund policies...</p>
            </div>
          ) : isError ? (
            <div
              role="alert"
              data-testid="policy-error-alert"
              className="rounded-lg bg-rose-50 p-4 border border-rose-200 text-rose-800 text-xs flex items-start space-x-2"
            >
              <AlertCircle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold">Failed to load policy rules</p>
                <p className="mt-0.5">
                  {error instanceof Error ? error.message : 'Please check network connectivity.'}
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {policies.map((rule) => (
                <CategoryPolicyCard
                  key={rule.category}
                  rule={rule}
                  onUpdate={handleUpdate}
                  isUpdating={updatingCategory === rule.category}
                />
              ))}
            </div>
          )
        ) : (
          /* Version History Tab */
          <div className="space-y-4">
            {/* Filter bar */}
            <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-50 p-2.5 rounded-lg border border-slate-200">
              <div className="flex items-center space-x-2">
                <label
                  htmlFor="history-category-filter"
                  className="text-xs font-medium text-slate-700"
                >
                  Category Filter:
                </label>
                <select
                  id="history-category-filter"
                  data-testid="history-category-filter"
                  value={historyCategory}
                  onChange={(e) => setHistoryCategory(e.target.value)}
                  className="text-xs rounded-md border border-slate-300 bg-white px-2.5 py-1.5 shadow-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
                >
                  <option value="all">All Categories</option>
                  <option value="damaged">Damaged Item</option>
                  <option value="wrong_item">Wrong Item</option>
                  <option value="changed_mind">Changed Mind</option>
                  <option value="late_delivery">Late Delivery</option>
                  <option value="missing_item">Missing Item</option>
                </select>
              </div>

              <span className="text-xs text-slate-500">
                {historyEntries.length} {historyEntries.length === 1 ? 'change logged' : 'changes logged'}
              </span>
            </div>

            {isHistoryLoading ? (
              <div className="flex flex-col items-center justify-center py-12 space-y-3">
                <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
                <p className="text-xs text-slate-500">Loading policy version history...</p>
              </div>
            ) : isHistoryError ? (
              <div
                role="alert"
                data-testid="policy-error-alert"
                className="rounded-lg bg-rose-50 p-4 border border-rose-200 text-rose-800 text-xs flex items-start space-x-2"
              >
                <AlertCircle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
                <div>
                  <p className="font-semibold">Failed to load policy version history</p>
                  <p className="mt-0.5">
                    {historyError instanceof Error ? historyError.message : 'Please check network connectivity.'}
                  </p>
                </div>
              </div>
            ) : historyEntries.length === 0 ? (
              <div
                data-testid="audit-empty-state"
                className="rounded-lg border border-dashed border-slate-200 p-8 text-center text-xs text-slate-500"
              >
                No policy version history found.
              </div>
            ) : (
              <div data-testid="audit-history-list" className="space-y-3">
                {historyEntries.map((entry) => {
                  const categoryLabel = CATEGORY_LABELS[entry.category] || entry.category
                  const isRollbackPending =
                    rollbackMutation.isPending && rollingBackId === entry.audit_id

                  return (
                    <div
                      key={entry.audit_id}
                      data-testid={`audit-entry-${entry.audit_id}`}
                      className="rounded-lg border border-slate-200 bg-white p-3.5 shadow-sm space-y-2.5"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center space-x-2">
                          <span
                            data-testid={`audit-category-${entry.audit_id}`}
                            className="inline-flex items-center rounded-md bg-slate-900 px-2 py-0.5 text-xs font-semibold text-white tracking-wide uppercase"
                          >
                            {categoryLabel}
                          </span>
                          <span
                            className={cn(
                              'inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium border uppercase tracking-wider',
                              entry.action === 'rollback'
                                ? 'bg-amber-50 text-amber-800 border-amber-200'
                                : 'bg-blue-50 text-blue-800 border-blue-200'
                            )}
                          >
                            {entry.action}
                          </span>
                        </div>

                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={isRollbackPending}
                          data-testid={`rollback-button-${entry.audit_id}`}
                          onClick={() => handleRollback(entry.category, entry.audit_id)}
                          className="text-xs h-7 px-2.5 hover:bg-slate-100 border-slate-300"
                        >
                          {isRollbackPending ? (
                            <>
                              <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                              Rolling back...
                            </>
                          ) : (
                            <>
                              <RotateCcw className="h-3 w-3 mr-1" />
                              Rollback
                            </>
                          )}
                        </Button>
                      </div>

                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
                        <div className="flex items-center space-x-1">
                          <Clock className="h-3.5 w-3.5 text-slate-400" />
                          <span data-testid={`audit-timestamp-${entry.audit_id}`}>
                            {entry.timestamp}
                          </span>
                        </div>
                        <div className="flex items-center space-x-1">
                          <User className="h-3.5 w-3.5 text-slate-400" />
                          <span>Operator:</span>
                          <span
                            data-testid={`audit-operator-${entry.audit_id}`}
                            className="font-medium text-slate-700 font-mono"
                          >
                            {entry.operator_id}
                          </span>
                        </div>
                      </div>

                      {/* Diffs */}
                      <div
                        data-testid={`audit-diffs-${entry.audit_id}`}
                        className="flex flex-wrap gap-1.5 pt-1 text-xs"
                      >
                        {entry.changes && Object.keys(entry.changes).length > 0 ? (
                          Object.entries(entry.changes).map(([field, change]) => {
                            const oldVal =
                              change && typeof change === 'object' && 'old_value' in change
                                ? (change as any).old_value
                                : undefined
                            const newVal =
                              change && typeof change === 'object' && 'new_value' in change
                                ? (change as any).new_value
                                : undefined
                            return (
                              <span
                                key={field}
                                className="inline-flex items-center rounded bg-slate-100 px-2 py-0.5 text-slate-700 border border-slate-200"
                              >
                                <span className="font-medium text-slate-900 mr-1">{field}:</span>
                                <span className="line-through text-slate-400 mr-1">
                                  {formatDiffValue(oldVal)}
                                </span>
                                <span className="text-slate-500 mr-1">→</span>
                                <span className="font-semibold text-emerald-700">
                                  {formatDiffValue(newVal)}
                                </span>
                              </span>
                            )
                          })
                        ) : (
                          <span className="text-slate-400 italic">No threshold differences recorded.</span>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* Modal Footer */}
        <DialogFooter>
          <Button
            variant="outline"
            size="sm"
            onClick={onClose}
            data-testid="close-policy-modal-button"
            className="text-xs"
          >
            Close
          </Button>
        </DialogFooter>
      </div>
    </Dialog>
  )
}

export default PolicyRuleViewerModal
