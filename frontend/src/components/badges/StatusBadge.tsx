import * as React from 'react'
import {
  Clock,
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
} from 'lucide-react'
import { cn } from '@/lib/utils'

export type RefundStatusType =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'escalated'
  | 'awaiting_clarification'

export interface StatusBadgeProps {
  status?: string | null
  className?: string
}

interface StatusConfig {
  label: string
  icon: React.ComponentType<{ className?: string }>
  className: string
}

const statusConfigs: Record<RefundStatusType, StatusConfig> = {
  pending: {
    label: 'Pending',
    icon: Clock,
    className: 'bg-sky-50 text-sky-700 border-sky-200',
  },
  processing: {
    label: 'Pending',
    icon: Clock,
    className: 'bg-sky-50 text-sky-700 border-sky-200',
  },
  completed: {
    label: 'Completed',
    icon: CheckCircle2,
    className: 'bg-slate-100 text-slate-700 border-slate-300',
  },
  escalated: {
    label: 'Escalated',
    icon: AlertTriangle,
    className: 'bg-amber-50 text-amber-800 border-amber-200',
  },
  awaiting_clarification: {
    label: 'Awaiting Clarification',
    icon: HelpCircle,
    className: 'bg-purple-50 text-purple-700 border-purple-200',
  },
}

const fallbackStatusConfig: StatusConfig = {
  label: 'Unknown',
  icon: HelpCircle,
  className: 'bg-slate-100 text-slate-500 border-slate-200',
}

function normalizeStatus(raw?: string | null): RefundStatusType | null {
  if (!raw) return null
  const cleaned = raw.trim().toLowerCase().replace(/-/g, '_')
  if (cleaned in statusConfigs) {
    return cleaned as RefundStatusType
  }
  return null
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const normalizedKey = normalizeStatus(status)
  const config = normalizedKey ? statusConfigs[normalizedKey] : fallbackStatusConfig
  const Icon = config.icon

  return (
    <span
      data-testid="status-badge"
      data-status={normalizedKey ?? 'unknown'}
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
}
