import { useQuery } from '@tanstack/react-query'
import {
  BarChart3,
  RefreshCw,
  AlertCircle,
  Loader2,
  TrendingUp,
  CheckCircle2,
  AlertTriangle,
  Clock,
  Layers,
  FileQuestion,
  HelpCircle,
} from 'lucide-react'
import {
  Dialog,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/Dialog'
import { Button } from '@/components/ui/Button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card'
import { fetchAnalyticsMetrics, type AnalyticsMetrics } from '@/services/analyticsService'
import { cn } from '@/lib/utils'

export interface AnalyticsDashboardModalProps {
  isOpen: boolean
  onClose: () => void
}

const CATEGORY_NAMES: Record<string, string> = {
  damaged: 'Damaged Item',
  wrong_item: 'Wrong Item',
  changed_mind: 'Changed Mind',
  late_delivery: 'Late Delivery',
  missing_item: 'Missing Item',
  unclassified: 'Unclassified',
}

export function AnalyticsDashboardModal({ isOpen, onClose }: AnalyticsDashboardModalProps) {
  const {
    data: metrics,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery<AnalyticsMetrics>({
    queryKey: ['analytics', 'metrics'],
    queryFn: fetchAnalyticsMetrics,
    enabled: isOpen,
    staleTime: 5000,
  })

  const total = metrics?.total_requests || 0

  const formatPercent = (val: number | undefined): string => {
    if (val === undefined || isNaN(val)) return '0.0%'
    return `${(val * 100).toFixed(1)}%`
  }

  const calcPercent = (count: number, denom: number): string => {
    if (!denom || denom === 0) return '0.0%'
    return `${((count / denom) * 100).toFixed(1)}%`
  }

  return (
    <Dialog
      isOpen={isOpen}
      onClose={onClose}
      aria-labelledby="analytics-dashboard-title"
      className="max-w-4xl max-h-[90vh] overflow-y-auto"
    >
      <div data-testid="analytics-dashboard-modal" className="space-y-6">
        {/* Modal Header */}
        <DialogHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 text-white shadow-sm">
                <BarChart3 className="h-4 w-4 text-emerald-400" aria-hidden="true" />
              </div>
              <div>
                <DialogTitle id="analytics-dashboard-title" className="text-base sm:text-lg">
                  Operational Analytics & AI Metrics
                </DialogTitle>
                <DialogDescription className="text-xs sm:text-sm text-slate-500">
                  Real-time operational visibility into refund volume, decision outcomes, and AI confidence.
                </DialogDescription>
              </div>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => refetch()}
              disabled={isFetching}
              data-testid="analytics-refresh-button"
              aria-label="Refresh analytics metrics"
              className="flex items-center space-x-1.5 text-xs text-slate-600 hover:text-slate-900"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', isFetching && 'animate-spin')} />
              <span>Refresh</span>
            </Button>
          </div>
        </DialogHeader>

        {/* Loading State */}
        {isLoading && (
          <div
            data-testid="analytics-loading"
            className="flex flex-col items-center justify-center py-16 space-y-3"
          >
            <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
            <p className="text-xs text-slate-500">Loading analytics and performance metrics...</p>
          </div>
        )}

        {/* Error State */}
        {isError && (
          <div
            role="alert"
            data-testid="analytics-error"
            className="rounded-lg bg-rose-50 p-4 border border-rose-200 text-rose-800 text-xs space-y-3"
          >
            <div className="flex items-start space-x-2">
              <AlertCircle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold text-rose-900">Failed to load analytics metrics</p>
                <p className="mt-0.5">
                  {error instanceof Error ? error.message : 'Please check your connection and retry.'}
                </p>
              </div>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => refetch()}
              className="text-xs text-rose-800 border-rose-300 hover:bg-rose-100"
            >
              Retry
            </Button>
          </div>
        )}

        {/* Empty State */}
        {!isLoading && !isError && metrics && metrics.total_requests === 0 && (
          <div
            data-testid="analytics-empty"
            className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center"
          >
            <FileQuestion className="mx-auto h-10 w-10 text-slate-400" />
            <h3 className="mt-2 text-sm font-semibold text-slate-900">No Analytics Data Available</h3>
            <p className="mt-1 text-xs text-slate-500">
              No refund requests have been submitted yet. Once requests are processed, operational KPIs and AI metrics will appear here.
            </p>
          </div>
        )}

        {/* Populated Data Dashboard */}
        {!isLoading && !isError && metrics && metrics.total_requests > 0 && (
          <div className="space-y-6">
            {/* KPI Cards Row */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
              {/* Total Volume */}
              <Card data-testid="kpi-total-volume" className="border-slate-200 shadow-sm">
                <CardHeader className="p-3 sm:p-4 pb-1">
                  <CardTitle className="text-xs font-medium text-slate-500 flex items-center justify-between">
                    <span>Total Volume</span>
                    <Layers className="h-4 w-4 text-slate-400" />
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-3 sm:p-4 pt-1">
                  <div className="text-xl sm:text-2xl font-bold text-slate-900">
                    {metrics.total_requests}
                  </div>
                  <p className="text-[11px] text-slate-500 mt-0.5">Total refund requests</p>
                </CardContent>
              </Card>

              {/* Auto-Approval Rate */}
              <Card data-testid="kpi-auto-approval-rate" className="border-slate-200 shadow-sm">
                <CardHeader className="p-3 sm:p-4 pb-1">
                  <CardTitle className="text-xs font-medium text-slate-500 flex items-center justify-between">
                    <span>Auto-Approval Rate</span>
                    <TrendingUp className="h-4 w-4 text-emerald-500" />
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-3 sm:p-4 pt-1">
                  <div className="text-xl sm:text-2xl font-bold text-emerald-600">
                    {formatPercent(metrics.auto_approval_rate)}
                  </div>
                  <p className="text-[11px] text-slate-500 mt-0.5">Automated approvals</p>
                </CardContent>
              </Card>

              {/* Supervisor Override Rate */}
              <Card data-testid="kpi-override-rate" className="border-slate-200 shadow-sm">
                <CardHeader className="p-3 sm:p-4 pb-1">
                  <CardTitle className="text-xs font-medium text-slate-500 flex items-center justify-between">
                    <span>Supervisor Override Rate</span>
                    <AlertTriangle className="h-4 w-4 text-amber-500" />
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-3 sm:p-4 pt-1">
                  <div className="text-xl sm:text-2xl font-bold text-amber-600">
                    {formatPercent(metrics.override_rate)}
                  </div>
                  <p className="text-[11px] text-slate-500 mt-0.5">Of completed requests</p>
                </CardContent>
              </Card>

              {/* Average AI Confidence */}
              <Card data-testid="kpi-average-confidence" className="border-slate-200 shadow-sm">
                <CardHeader className="p-3 sm:p-4 pb-1">
                  <CardTitle className="text-xs font-medium text-slate-500 flex items-center justify-between">
                    <span>Average AI Confidence</span>
                    <CheckCircle2 className="h-4 w-4 text-sky-500" />
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-3 sm:p-4 pt-1">
                  <div className="text-xl sm:text-2xl font-bold text-sky-600">
                    {formatPercent(metrics.average_confidence)}
                  </div>
                  <p className="text-[11px] text-slate-500 mt-0.5">Model confidence score</p>
                </CardContent>
              </Card>
            </div>

            {/* Decision Distribution Breakdown */}
            <div
              data-testid="decision-distribution"
              className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm space-y-4"
            >
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-900">Decision Distribution</h3>
                <span className="text-xs text-slate-500">Based on {total} requests</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* Auto-Approve */}
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs">
                    <span className="font-medium text-slate-700 flex items-center">
                      <span className="h-2 w-2 rounded-full bg-emerald-500 mr-1.5" />
                      Auto-Approve
                    </span>
                    <span className="text-slate-500">
                      {metrics.decision_breakdown.auto_approve} (
                      {calcPercent(metrics.decision_breakdown.auto_approve, total)})
                    </span>
                  </div>
                  <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-emerald-500 h-2 rounded-full transition-all"
                      style={{
                        width: calcPercent(metrics.decision_breakdown.auto_approve, total),
                      }}
                    />
                  </div>
                </div>

                {/* Deny */}
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs">
                    <span className="font-medium text-slate-700 flex items-center">
                      <span className="h-2 w-2 rounded-full bg-rose-500 mr-1.5" />
                      Deny
                    </span>
                    <span className="text-slate-500">
                      {metrics.decision_breakdown.deny} (
                      {calcPercent(metrics.decision_breakdown.deny, total)})
                    </span>
                  </div>
                  <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-rose-500 h-2 rounded-full transition-all"
                      style={{
                        width: calcPercent(metrics.decision_breakdown.deny, total),
                      }}
                    />
                  </div>
                </div>

                {/* Escalate */}
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs">
                    <span className="font-medium text-slate-700 flex items-center">
                      <span className="h-2 w-2 rounded-full bg-amber-500 mr-1.5" />
                      Escalate
                    </span>
                    <span className="text-slate-500">
                      {metrics.decision_breakdown.escalate} (
                      {calcPercent(metrics.decision_breakdown.escalate, total)})
                    </span>
                  </div>
                  <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-amber-500 h-2 rounded-full transition-all"
                      style={{
                        width: calcPercent(metrics.decision_breakdown.escalate, total),
                      }}
                    />
                  </div>
                </div>

                {/* Pending */}
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs">
                    <span className="font-medium text-slate-700 flex items-center">
                      <span className="h-2 w-2 rounded-full bg-sky-500 mr-1.5" />
                      Pending
                    </span>
                    <span className="text-slate-500">
                      {metrics.decision_breakdown.pending} (
                      {calcPercent(metrics.decision_breakdown.pending, total)})
                    </span>
                  </div>
                  <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-sky-500 h-2 rounded-full transition-all"
                      style={{
                        width: calcPercent(metrics.decision_breakdown.pending, total),
                      }}
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* Status Breakdown Section */}
            <div
              data-testid="status-distribution"
              className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm space-y-4"
            >
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-900">Status Breakdown</h3>
                <span className="text-xs text-slate-500">Workflow pipeline states</span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="rounded-md border border-slate-100 bg-slate-50/70 p-3 text-center">
                  <Clock className="h-4 w-4 mx-auto text-sky-500 mb-1" />
                  <span className="text-xs text-slate-500 block">Pending</span>
                  <span className="text-lg font-bold text-slate-800">
                    {metrics.status_breakdown.pending}
                  </span>
                </div>
                <div className="rounded-md border border-slate-100 bg-slate-50/70 p-3 text-center">
                  <CheckCircle2 className="h-4 w-4 mx-auto text-emerald-500 mb-1" />
                  <span className="text-xs text-slate-500 block">Completed</span>
                  <span className="text-lg font-bold text-slate-800">
                    {metrics.status_breakdown.completed}
                  </span>
                </div>
                <div className="rounded-md border border-slate-100 bg-slate-50/70 p-3 text-center">
                  <AlertTriangle className="h-4 w-4 mx-auto text-amber-500 mb-1" />
                  <span className="text-xs text-slate-500 block">Escalated</span>
                  <span className="text-lg font-bold text-slate-800">
                    {metrics.status_breakdown.escalated}
                  </span>
                </div>
                <div className="rounded-md border border-slate-100 bg-slate-50/70 p-3 text-center">
                  <HelpCircle className="h-4 w-4 mx-auto text-purple-500 mb-1" />
                  <span className="text-xs text-slate-500 block">Awaiting Clarification</span>
                  <span className="text-lg font-bold text-slate-800">
                    {metrics.status_breakdown.awaiting_clarification}
                  </span>
                </div>
              </div>
            </div>

            {/* Product Category Breakdown Section */}
            <div
              data-testid="category-distribution"
              className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm space-y-4"
            >
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-900">Category Distribution</h3>
                <span className="text-xs text-slate-500">Classification volume by category</span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {Object.entries(metrics.category_breakdown).length === 0 ? (
                  <p className="text-xs text-slate-500 col-span-full">No category breakdown data.</p>
                ) : (
                  Object.entries(metrics.category_breakdown).map(([catKey, count]) => {
                    const label = CATEGORY_NAMES[catKey] || catKey
                    return (
                      <div
                        key={catKey}
                        className="flex items-center justify-between rounded-md border border-slate-100 bg-slate-50/50 px-3 py-2 text-xs"
                      >
                        <span className="font-medium text-slate-700 truncate mr-2">{label}</span>
                        <span className="font-semibold text-slate-900 bg-white px-2 py-0.5 rounded border border-slate-200">
                          {count}
                        </span>
                      </div>
                    )
                  })
                )}
              </div>
            </div>
          </div>
        )}

        {/* Modal Footer */}
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onClose}
            data-testid="analytics-close-button"
          >
            Close
          </Button>
        </DialogFooter>
      </div>
    </Dialog>
  )
}
