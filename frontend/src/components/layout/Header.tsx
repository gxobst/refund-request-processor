import { ShieldCheck, RefreshCw, Sliders, BarChart3, UserCheck, User } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useUserRole } from '@/context/RoleContext'

export type SystemHealthStatus = 'operational' | 'degraded' | 'offline'

export interface HeaderProps {
  systemHealth?: SystemHealthStatus
  isPolling?: boolean
  pollingIntervalSeconds?: number
  onManualRefresh?: () => void
  isRefreshing?: boolean
  className?: string
  sseConnected?: boolean
  onOpenPolicyRules?: () => void
  onOpenAnalytics?: () => void
}

export function Header({
  systemHealth = 'operational',
  isPolling = false,
  pollingIntervalSeconds = 3,
  onManualRefresh,
  isRefreshing = false,
  className,
  sseConnected = false,
  onOpenPolicyRules,
  onOpenAnalytics,
}: HeaderProps) {
  const healthBadgeConfig: Record<
    SystemHealthStatus,
    { label: string; dotClass: string; textClass: string; bgClass: string; borderClass: string }
  > = {
    operational: {
      label: 'System Operational',
      dotClass: 'bg-emerald-500',
      textClass: 'text-emerald-700',
      bgClass: 'bg-emerald-50',
      borderClass: 'border-emerald-200',
    },
    degraded: {
      label: 'Degraded Performance',
      dotClass: 'bg-amber-500',
      textClass: 'text-amber-800',
      bgClass: 'bg-amber-50',
      borderClass: 'border-amber-200',
    },
    offline: {
      label: 'System Offline',
      dotClass: 'bg-rose-500',
      textClass: 'text-rose-700',
      bgClass: 'bg-rose-50',
      borderClass: 'border-rose-200',
    },
  }

  const currentHealth = healthBadgeConfig[systemHealth]
  const { role, setRole, isSupervisor } = useUserRole()

  const handleToggleRole = () => {
    const nextRole = role === 'supervisor' ? 'agent' : 'supervisor'
    setRole(nextRole)
  }

  return (
    <header
      className={cn(
        'sticky top-0 z-40 w-full border-b border-slate-200 bg-white/95 backdrop-blur-sm',
        className
      )}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
        {/* Branding & Logo */}
        <div className="flex items-center space-x-3">
          <div className="flex items-center justify-center h-8 w-8 rounded-lg bg-slate-900 text-white shadow-sm">
            <ShieldCheck className="h-5 w-5 text-emerald-400" aria-hidden="true" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="font-semibold text-slate-900 tracking-tight text-sm sm:text-base">
                AI Refund Request Processor
              </h1>
              <span className="hidden sm:inline-flex items-center rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-600 border border-slate-200">
                Back Office
              </span>
            </div>
          </div>
        </div>

        {/* Status Indicators & Controls */}
        <div className="flex items-center space-x-3 sm:space-x-4">
          {/* Polling / Live indicator */}
          <div
            data-testid="polling-status"
            className="flex items-center space-x-1.5 text-xs text-slate-600 font-medium"
          >
            {sseConnected ? (
              <>
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
                </span>
                <span className="hidden sm:inline">Live - SSE connected</span>
                <span className="sm:hidden">Live</span>
              </>
            ) : isPolling ? (
              <>
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-sky-500" />
                </span>
                <span className="hidden sm:inline">Live - polling every {pollingIntervalSeconds}s</span>
                <span className="sm:hidden">Live ({pollingIntervalSeconds}s)</span>
              </>
            ) : (
              <>
                <span className="h-2 w-2 rounded-full bg-slate-300" />
                <span className="text-slate-500">Idle</span>
              </>
            )}
          </div>

          {/* System Health Badge */}
          <div
            data-testid="system-health-badge"
            className={cn(
              'inline-flex items-center space-x-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium border',
              currentHealth.bgClass,
              currentHealth.textClass,
              currentHealth.borderClass
            )}
          >
            <span
              className={cn('h-1.5 w-1.5 rounded-full', currentHealth.dotClass)}
              aria-hidden="true"
            />
            <span>{currentHealth.label}</span>
          </div>

          {/* Role Switcher Badge/Button */}
          <button
            type="button"
            onClick={handleToggleRole}
            data-testid="role-switcher"
            aria-label={`Current role: ${isSupervisor ? 'Supervisor' : 'Agent'}. Click to toggle.`}
            className={cn(
              'inline-flex items-center space-x-1.5 px-2.5 py-1 text-xs font-medium rounded-md border shadow-sm transition-colors',
              'focus:outline-none focus:ring-2 focus:ring-slate-400',
              isSupervisor
                ? 'bg-purple-50 text-purple-700 border-purple-200 hover:bg-purple-100'
                : 'bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100'
            )}
          >
            {isSupervisor ? (
              <UserCheck className="h-3.5 w-3.5 text-purple-600" aria-hidden="true" />
            ) : (
              <User className="h-3.5 w-3.5 text-blue-600" aria-hidden="true" />
            )}
            <span>{isSupervisor ? 'Supervisor' : 'Agent'}</span>
          </button>

          {/* Policy Rules Button */}
          {onOpenPolicyRules && (
            <button
              type="button"
              onClick={onOpenPolicyRules}
              data-testid="policy-rules-button"
              aria-label="Policy Rules"
              className={cn(
                'inline-flex items-center space-x-1.5 px-2.5 py-1 text-xs font-medium rounded-md',
                'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 hover:text-slate-900',
                'transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-slate-400'
              )}
            >
              <Sliders className="h-3.5 w-3.5 text-slate-500" aria-hidden="true" />
              <span>Policy Rules</span>
            </button>
          )}

          {/* Analytics Dashboard Button */}
          {onOpenAnalytics && (
            <button
              type="button"
              onClick={onOpenAnalytics}
              data-testid="analytics-button"
              aria-label="Open Analytics Dashboard"
              className={cn(
                'inline-flex items-center space-x-1.5 px-2.5 py-1 text-xs font-medium rounded-md',
                'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 hover:text-slate-900',
                'transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-slate-400'
              )}
            >
              <BarChart3 className="h-3.5 w-3.5 text-slate-500" aria-hidden="true" />
              <span>Analytics</span>
            </button>
          )}

          {/* Optional Manual Refresh Button */}
          {onManualRefresh && (
            <button
              type="button"
              onClick={onManualRefresh}
              disabled={isRefreshing}
              aria-label="Refresh refund queue"
              className={cn(
                'inline-flex items-center justify-center h-8 w-8 rounded-md text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors',
                'focus:outline-none focus:ring-2 focus:ring-slate-400',
                isRefreshing && 'opacity-60 cursor-not-allowed'
              )}
            >
              <RefreshCw
                className={cn('h-4 w-4', isRefreshing && 'animate-spin')}
                aria-hidden="true"
              />
            </button>
          )}
        </div>
      </div>
    </header>
  )
}
