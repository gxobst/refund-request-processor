import * as React from 'react'
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  UserCheck,
  UserX,
  HelpCircle,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Tooltip } from '@/components/ui/Tooltip'

export type DecisionType =
  | 'auto_approve'
  | 'deny'
  | 'escalate'
  | 'manual_approved'
  | 'manual_denied'

export interface DecisionBadgeProps {
  decision?: string | null
  confidenceScore?: number | null
  showConfidence?: boolean
  className?: string
}

interface DecisionConfig {
  label: string
  icon: React.ComponentType<{ className?: string }>
  className: string
}

const decisionConfigs: Record<DecisionType, DecisionConfig> = {
  auto_approve: {
    label: 'Auto Approved',
    icon: CheckCircle2,
    className: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  },
  deny: {
    label: 'Denied',
    icon: XCircle,
    className: 'bg-rose-50 text-rose-700 border-rose-200',
  },
  escalate: {
    label: 'Escalated',
    icon: AlertTriangle,
    className: 'bg-amber-50 text-amber-800 border-amber-200',
  },
  manual_approved: {
    label: 'Manually Approved',
    icon: UserCheck,
    className: 'bg-teal-50 text-teal-700 border-teal-200',
  },
  manual_denied: {
    label: 'Manually Denied',
    icon: UserX,
    className: 'bg-red-50 text-red-700 border-red-200',
  },
}

const fallbackConfig: DecisionConfig = {
  label: 'Pending Review',
  icon: HelpCircle,
  className: 'bg-slate-100 text-slate-600 border-slate-200',
}

function normalizeDecision(raw?: string | null): DecisionType | null {
  if (!raw) return null
  const cleaned = raw.trim().toLowerCase().replace(/-/g, '_')
  if (cleaned in decisionConfigs) {
    return cleaned as DecisionType
  }
  // Common aliases
  if (cleaned === 'approve' || cleaned === 'approved') return 'auto_approve'
  if (cleaned === 'rejected') return 'deny'
  return null
}

function formatConfidenceTooltip(confidenceScore: number): string {
  const percent =
    confidenceScore <= 1.0
      ? Math.round(confidenceScore * 100)
      : Math.round(confidenceScore)
  return `${percent}% confidence`
}

export function DecisionBadge({
  decision,
  confidenceScore,
  showConfidence = true,
  className,
}: DecisionBadgeProps) {
  const normalizedKey = normalizeDecision(decision)
  const config = normalizedKey ? decisionConfigs[normalizedKey] : fallbackConfig
  const Icon = config.icon

  const hasValidConfidence =
    showConfidence &&
    confidenceScore !== null &&
    confidenceScore !== undefined &&
    typeof confidenceScore === 'number' &&
    !isNaN(confidenceScore)

  const badgeContent = (
    <span
      data-testid="decision-badge"
      data-decision={normalizedKey ?? 'unknown'}
      className={cn(
        'inline-flex items-center space-x-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium border select-none transition-colors cursor-default',
        config.className,
        className
      )}
    >
      <Icon className="h-3.5 w-3.5 flex-shrink-0" />
      <span>{config.label}</span>
    </span>
  )

  if (hasValidConfidence) {
    return (
      <Tooltip content={formatConfidenceTooltip(confidenceScore)}>
        {badgeContent}
      </Tooltip>
    )
  }

  return badgeContent
}
