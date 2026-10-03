import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  RotateCcw,
  UserCheck,
  ShieldCheck,
  Sparkles,
  ShoppingBag,
  Mail,
  FileText,
  AlertTriangle,
  HelpCircle,
  Lock,
} from 'lucide-react'
import { useUserRole } from '@/context/RoleContext'
import { getRefundById } from '@/services/refundService'
import {
  Drawer,
  DrawerHeader,
  DrawerTitle,
  DrawerContent,
  DrawerFooter,
} from '@/components/ui/Drawer'
import { Button } from '@/components/ui/Button'
import { DecisionBadge } from '@/components/badges/DecisionBadge'
import { StatusBadge } from '@/components/badges/StatusBadge'
import { cn } from '@/lib/utils'
import { CustomerClarificationModal } from '@/components/modals/CustomerClarificationModal'
import type { RefundRecord, ProblemDetails } from '@/types/api'

export interface RefundDetailDrawerProps {
  refundId: string | null
  isOpen: boolean
  onClose: () => void
  onTriggerOverride?: (refundId: string) => void
  onTriggerRequestProof?: (refundId: string) => void
  onTriggerClarify?: (refundId: string) => void
  children?: React.ReactNode
}

type EmailTabType = 'approval' | 'denial' | 'clarification'

function formatCurrency(amount?: number | null): string {
  if (amount === null || amount === undefined || isNaN(Number(amount))) return 'N/A'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
  }).format(Number(amount))
}

function formatTimestamp(timestamp?: string | null): string {
  if (!timestamp) return 'N/A'
  try {
    const d = new Date(timestamp)
    if (isNaN(d.getTime())) return timestamp
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return timestamp
  }
}

export function RefundDetailDrawer({
  refundId,
  isOpen,
  onClose,
  onTriggerOverride,
  onTriggerRequestProof,
  onTriggerClarify,
  children,
}: RefundDetailDrawerProps) {
  const [activeEmailTab, setActiveEmailTab] = React.useState<EmailTabType>('approval')
  const [isInternalClarifyOpen, setIsInternalClarifyOpen] = React.useState(false)
  const { role } = useUserRole()

  const {
    data: refund,
    isLoading,
    error,
    refetch,
  } = useQuery<RefundRecord, Error>({
    queryKey: ['refund', refundId],
    queryFn: () => getRefundById(refundId!),
    enabled: isOpen && Boolean(refundId),
  })

  // Normalize fields supporting both camelCase and snake_case backend payloads
  const rec = (refund || {}) as Record<string, unknown>
  const effectiveRefundId = refund?.refundId || (rec.refund_id as string) || refundId || ''
  const orderId = refund?.orderId || (rec.order_id as string) || 'N/A'
  const customerRequestText =
    refund?.customerRequestText || (rec.customer_request_text as string) || ''
  const status = refund?.status || (rec.status as string) || 'pending'
  const decision = refund?.decision || (rec.decision as string) || null
  const confidenceScore =
    refund?.confidenceScore !== undefined
      ? refund.confidenceScore
      : (rec.confidence_score as number | undefined)
  const category = refund?.category || (rec.category as string) || 'General'
  const reasoning = refund?.reasoning || (rec.reasoning as string) || ''
  const orderAmount =
    typeof rec.orderAmount === 'number'
      ? rec.orderAmount
      : typeof rec.order_amount === 'number'
      ? rec.order_amount
      : null
  const deliveryStatus =
    (rec.deliveryStatus as string) || (rec.delivery_status as string) || 'Delivered'

  // Override & Escalation fields
  const escalationTier =
    refund?.escalationTier ||
    (rec.escalation_tier as string) ||
    (rec.escalationTier as string) ||
    null
  const overrideDecision =
    refund?.overrideDecision || (rec.override_decision as string) || null
  const overrideReason =
    refund?.overrideReason || (rec.override_reason as string) || null
  const overriddenAt =
    refund?.overriddenAt || (rec.overridden_at as string) || null

  // Matched policy rule
  const matchedRule = (refund?.matchedPolicyRule ||
    rec.matched_policy_rule ||
    {}) as Record<string, unknown>
  const policyName = (matchedRule.policyName || matchedRule.policy_name || 'Standard Policy') as string
  const policyAction = (matchedRule.action || matchedRule.policy_action || decision || 'auto_approve') as string
  const returnRequired =
    typeof matchedRule.returnRequired === 'boolean'
      ? matchedRule.returnRequired
      : typeof matchedRule.return_required === 'boolean'
      ? matchedRule.return_required
      : false

  // Email draft fields
  const approvalEmailText =
    refund?.approvalEmailText || (rec.approval_email_text as string) || null
  const denialEmailText =
    refund?.denialEmailText || (rec.denial_email_text as string) || null
  const clarificationEmailText =
    refund?.clarificationEmailText || (rec.clarification_email_text as string) || null

  // Dynamic state for action triggers
  const isEscalatedOrAmbiguous =
    status === 'escalated' ||
    decision === 'escalate' ||
    policyAction === 'ambiguous' ||
    policyAction === 'manual_review' ||
    status === 'awaiting_clarification'

  // Extract RFC 9457 error details
  const problemDetails = React.useMemo(() => {
    if (!error) return null
    const err = error as Error & { problem?: ProblemDetails }
    if (err.problem) {
      return err.problem
    }
    return {
      title: 'Failed to load refund details',
      detail: error.message || 'Unable to retrieve evaluation records from the server.',
    }
  }, [error])

  // Get active email text
  const currentEmailContent = React.useMemo(() => {
    switch (activeEmailTab) {
      case 'approval':
        return approvalEmailText
      case 'denial':
        return denialEmailText
      case 'clarification':
        return clarificationEmailText
      default:
        return null
    }
  }, [activeEmailTab, approvalEmailText, denialEmailText, clarificationEmailText])

  const handleClarifyClick = () => {
    if (onTriggerClarify) {
      onTriggerClarify(effectiveRefundId)
    } else {
      setIsInternalClarifyOpen(true)
    }
  }

  return (
    <Drawer
      isOpen={isOpen}
      onClose={onClose}
      widthClassName="max-w-2xl w-full"
      aria-labelledby="refund-detail-title"
      aria-describedby="refund-detail-description"
    >
      {/* Header */}
      <DrawerHeader>
        <div className="flex flex-col space-y-2">
          <div className="flex items-center space-x-2">
            <span className="text-xs font-mono font-medium text-slate-500 uppercase tracking-wider">
              Refund Request
            </span>
            <span
              id="refund-detail-title"
              data-testid="detail-refund-id"
              className="text-sm font-mono font-bold text-slate-900 bg-slate-100 px-2 py-0.5 rounded border border-slate-200"
            >
              {effectiveRefundId || 'Loading...'}
            </span>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
            <DrawerTitle id="refund-detail-description" className="text-base font-semibold text-slate-900">
              Order {orderId}
            </DrawerTitle>
            <div className="flex items-center space-x-2">
              <StatusBadge status={status} />
              {escalationTier && (
                <span
                  data-testid="escalation-tier-badge"
                  className={cn(
                    "inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wider",
                    escalationTier === 'senior_manager'
                      ? "bg-purple-100 text-purple-800 border border-purple-200"
                      : "bg-blue-100 text-blue-800 border border-blue-200"
                  )}
                >
                  Escalation: {escalationTier === 'senior_manager' ? 'Senior Manager' : 'Supervisor'}
                </span>
              )}
              <DecisionBadge
                decision={overrideDecision || decision}
                confidenceScore={confidenceScore}
              />
            </div>
          </div>
        </div>
      </DrawerHeader>

      {/* Main Scrollable Content */}
      <DrawerContent className="p-6 space-y-6">
        {/* Loading Skeleton */}
        {isLoading && (
          <div data-testid="detail-loading-skeleton" className="space-y-6 animate-pulse">
            <div className="h-24 bg-slate-200 rounded-lg" />
            <div className="h-20 bg-slate-200 rounded-lg" />
            <div className="h-28 bg-slate-200 rounded-lg" />
            <div className="h-32 bg-slate-200 rounded-lg" />
          </div>
        )}

        {/* Error Banner */}
        {problemDetails && !isLoading && (
          <div
            role="alert"
            data-testid="detail-error-banner"
            className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-rose-900 flex items-start justify-between gap-3"
          >
            <div className="flex items-start space-x-3">
              <AlertCircle className="h-5 w-5 text-rose-600 flex-shrink-0 mt-0.5" />
              <div>
                <h4 className="text-sm font-semibold">{problemDetails.title}</h4>
                <p className="text-xs text-rose-700 mt-0.5">{problemDetails.detail}</p>
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetch()}
              className="border-rose-300 text-rose-700 hover:bg-rose-100 flex-shrink-0"
            >
              <RotateCcw className="h-3.5 w-3.5 mr-1" />
              Retry
            </Button>
          </div>
        )}

        {/* Loaded Content */}
        {!isLoading && !problemDetails && refund && (
          <>
            {/* Supervisor Override Banner (when overridden) */}
            {overrideDecision && (
              <div
                data-testid="supervisor-override-banner"
                className="rounded-lg border border-teal-200 bg-teal-50/80 p-4 text-teal-900 space-y-2 shadow-sm"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <UserCheck className="h-4 w-4 text-teal-600" />
                    <span className="text-xs font-bold uppercase tracking-wider text-teal-800">
                      Supervisor Decision Override
                    </span>
                  </div>
                  <span className="text-[11px] font-medium text-teal-700">
                    {formatTimestamp(overriddenAt)}
                  </span>
                </div>
                <div className="text-sm font-semibold">
                  Overridden to: <span className="capitalize">{overrideDecision}</span>
                </div>
                {overrideReason && (
                  <p className="text-xs text-teal-800 bg-white/80 rounded p-2 border border-teal-200">
                    <span className="font-semibold">Justification: </span>
                    {overrideReason}
                  </p>
                )}
              </div>
            )}

            {/* Customer Intake Section */}
            <section
              data-testid="section-customer-intake"
              className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm space-y-3"
            >
              <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                <div className="flex items-center space-x-2 text-slate-800 font-semibold text-sm">
                  <ShoppingBag className="h-4 w-4 text-slate-500" />
                  <span>Customer Request & Order Intake</span>
                </div>
                <span className="text-xs font-semibold text-slate-900">
                  {formatCurrency(orderAmount)}
                </span>
              </div>

              <div className="space-y-1">
                <span className="text-xs font-medium text-slate-500 uppercase tracking-wide">
                  Customer Explanation
                </span>
                <p className="text-xs text-slate-800 bg-slate-50 rounded-md p-3 border border-slate-100 leading-relaxed whitespace-pre-wrap">
                  {customerRequestText || (
                    <span className="text-slate-400 italic">No explanation provided</span>
                  )}
                </p>
              </div>

              <div className="flex items-center justify-between text-xs pt-1 text-slate-600">
                <span>
                  Delivery Status:{' '}
                  <span className="font-medium text-slate-800 capitalize">
                    {deliveryStatus}
                  </span>
                </span>
                <span>
                  Order ID: <span className="font-mono font-medium">{orderId}</span>
                </span>
              </div>
            </section>

            {/* Classification Section */}
            <section
              data-testid="section-classification"
              className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm space-y-3"
            >
              <div className="flex items-center space-x-2 text-slate-800 font-semibold text-sm border-b border-slate-100 pb-2">
                <Sparkles className="h-4 w-4 text-sky-600" />
                <span>Classification & Confidence</span>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <span className="text-xs text-slate-500">Detected Category</span>
                  <div className="flex items-center space-x-2">
                    <span className="inline-flex items-center rounded-md px-2.5 py-1 text-xs font-semibold bg-sky-50 text-sky-800 border border-sky-200 capitalize">
                      {category.replace(/_/g, ' ')}
                    </span>
                  </div>
                </div>

                <div className="space-y-1">
                  <span className="text-xs text-slate-500">Model Confidence</span>
                  <div className="flex items-center space-x-2">
                    <span className="text-sm font-bold text-slate-900">
                      {confidenceScore !== null && confidenceScore !== undefined
                        ? `${Math.round(confidenceScore * 100)}%`
                        : 'N/A'}
                    </span>
                    <span className="text-[11px] text-slate-500">
                      {confidenceScore !== null && confidenceScore !== undefined && confidenceScore >= 0.85
                        ? '(High confidence)'
                        : confidenceScore !== null && confidenceScore !== undefined && confidenceScore >= 0.6
                        ? '(Medium confidence)'
                        : '(Requires review)'}
                    </span>
                  </div>
                </div>
              </div>
            </section>

            {/* Policy Check Section */}
            <section
              data-testid="section-policy-check"
              className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm space-y-3"
            >
              <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                <div className="flex items-center space-x-2 text-slate-800 font-semibold text-sm">
                  <ShieldCheck className="h-4 w-4 text-emerald-600" />
                  <span>Policy Rule Validation</span>
                </div>
                <span className="text-xs font-medium text-slate-500">
                  Rule: <span className="font-mono text-slate-700">{policyName}</span>
                </span>
              </div>

              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="p-2 rounded bg-slate-50 border border-slate-100">
                  <span className="text-slate-500 block">Prescribed Action:</span>
                  <span className="font-semibold text-slate-800 capitalize">
                    {policyAction.replace(/_/g, ' ')}
                  </span>
                </div>
                <div className="p-2 rounded bg-slate-50 border border-slate-100">
                  <span className="text-slate-500 block">Return Required:</span>
                  <span className="font-semibold text-slate-800">
                    {returnRequired ? 'Yes' : 'No'}
                  </span>
                </div>
              </div>

              {/* Passed / Failed rules summary */}
              <div className="space-y-1 pt-1">
                <div className="text-xs font-medium text-slate-600">Rule Criteria Evaluation:</div>
                <div className="flex flex-col space-y-1 text-xs">
                  <div className="flex items-center space-x-1.5 text-emerald-700">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                    <span>Item eligible under 30-day policy window</span>
                  </div>
                  <div className="flex items-center space-x-1.5 text-slate-700">
                    <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />
                    <span>Category: {category.replace(/_/g, ' ')} matches policy rules</span>
                  </div>
                </div>
              </div>
            </section>

            {/* Decision & Reasoning Section */}
            <section
              data-testid="section-decision-reasoning"
              className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm space-y-3"
            >
              <div className="flex items-center space-x-2 text-slate-800 font-semibold text-sm border-b border-slate-100 pb-2">
                <FileText className="h-4 w-4 text-slate-600" />
                <span>Decision & Synthesized Reasoning</span>
              </div>

              <div className="rounded-md border border-slate-200 bg-slate-50 p-4">
                <p className="text-xs text-slate-800 leading-relaxed whitespace-pre-wrap">
                  {reasoning || (
                    <span className="text-slate-400 italic">
                      No synthesized explanation available for this request.
                    </span>
                  )}
                </p>
              </div>
            </section>

            {/* Customer Email Previews Section */}
            <section
              data-testid="section-email-previews"
              className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm space-y-3"
            >
              <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                <div className="flex items-center space-x-2 text-slate-800 font-semibold text-sm">
                  <Mail className="h-4 w-4 text-slate-600" />
                  <span>Customer Email Drafts</span>
                </div>
              </div>

              {/* Segmented Tab Controls */}
              <div className="flex items-center space-x-1 bg-slate-100 p-1 rounded-md text-xs">
                <button
                  type="button"
                  onClick={() => setActiveEmailTab('approval')}
                  className={cn(
                    'flex-1 py-1 px-2 rounded font-medium transition-colors',
                    activeEmailTab === 'approval'
                      ? 'bg-white text-slate-900 shadow-sm'
                      : 'text-slate-600 hover:text-slate-900'
                  )}
                >
                  Approval Draft
                </button>
                <button
                  type="button"
                  onClick={() => setActiveEmailTab('denial')}
                  className={cn(
                    'flex-1 py-1 px-2 rounded font-medium transition-colors',
                    activeEmailTab === 'denial'
                      ? 'bg-white text-slate-900 shadow-sm'
                      : 'text-slate-600 hover:text-slate-900'
                  )}
                >
                  Denial Draft
                </button>
                <button
                  type="button"
                  onClick={() => setActiveEmailTab('clarification')}
                  className={cn(
                    'flex-1 py-1 px-2 rounded font-medium transition-colors',
                    activeEmailTab === 'clarification'
                      ? 'bg-white text-slate-900 shadow-sm'
                      : 'text-slate-600 hover:text-slate-900'
                  )}
                >
                  Clarification Draft
                </button>
              </div>

              {/* Email Content Box */}
              <div
                data-testid="email-draft-container"
                className="rounded-md border border-slate-200 bg-slate-50 p-3 min-h-[90px]"
              >
                {currentEmailContent ? (
                  <p className="font-mono text-xs text-slate-800 whitespace-pre-wrap leading-relaxed">
                    {currentEmailContent}
                  </p>
                ) : (
                  <p className="text-xs text-slate-400 italic">
                    No email generated for this workflow state
                  </p>
                )}
              </div>
            </section>

            {/* Child Slots Container (Evidence Gallery, Clarification History, Tool Execution Audit) */}
            {children && (
              <div data-testid="detail-drawer-children-slot" className="space-y-6 pt-2">
                {children}
              </div>
            )}
          </>
        )}
      </DrawerContent>

      {/* Drawer Action Bar / Footer */}
      <DrawerFooter>
        <div className="flex items-center justify-between w-full">
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            className="text-slate-600 hover:text-slate-900"
          >
            Close
          </Button>

          <div className="flex items-center space-x-2">
            {/* Submit Clarification Button (when awaiting_clarification) */}
            {status === 'awaiting_clarification' && (
              <Button
                variant="outline"
                size="sm"
                data-testid="drawer-clarify-button"
                disabled={!effectiveRefundId}
                onClick={handleClarifyClick}
                className="border-sky-300 text-sky-800 hover:bg-sky-50"
              >
                <HelpCircle className="h-3.5 w-3.5 mr-1 text-sky-600" />
                Submit Clarification
              </Button>
            )}

            {/* Request Proof Button (enabled when escalated or ambiguous) */}
            <Button
              variant="outline"
              size="sm"
              disabled={!isEscalatedOrAmbiguous || !effectiveRefundId}
              onClick={() => onTriggerRequestProof?.(effectiveRefundId)}
              className={cn(
                'border-amber-300 text-amber-800 hover:bg-amber-50',
                !isEscalatedOrAmbiguous && 'opacity-40 cursor-not-allowed'
              )}
            >
              <HelpCircle className="h-3.5 w-3.5 mr-1 text-amber-600" />
              Request Proof
            </Button>

            {/* Manual Override Button */}
            {role === 'agent' ? (
              <Button
                variant="default"
                size="sm"
                disabled
                title="Supervisor role required to manual override"
                data-testid="override-button-disabled"
                className="bg-slate-300 text-slate-500 cursor-not-allowed"
              >
                <Lock className="h-3.5 w-3.5 mr-1 text-slate-400" />
                Manual Override
              </Button>
            ) : (
              <Button
                variant="default"
                size="sm"
                disabled={!effectiveRefundId}
                data-testid="override-action-button"
                onClick={() => onTriggerOverride?.(effectiveRefundId)}
                className="bg-slate-900 text-white hover:bg-slate-800"
              >
                <AlertTriangle className="h-3.5 w-3.5 mr-1 text-amber-400" />
                Manual Override
              </Button>
            )}
          </div>
        </div>
      </DrawerFooter>

      {!onTriggerClarify && (
        <CustomerClarificationModal
          refundId={effectiveRefundId}
          isOpen={isInternalClarifyOpen}
          onClose={() => setIsInternalClarifyOpen(false)}
        />
      )}
    </Drawer>
  )
}
