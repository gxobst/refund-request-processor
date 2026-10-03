import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  RefreshCw,
  AlertCircle,
  FileQuestion,
  RotateCcw,
  Download,
  Loader2,
  CheckCircle,
} from 'lucide-react'
import { listRefunds, createBulkExportJob, pollBulkExportJob } from '@/services/refundService'
import {
  serializeToCsv,
  serializeToJson,
  generateExportFilename,
  downloadExportFile,
} from '@/utils/exportUtils'
import { DecisionBadge } from '@/components/badges/DecisionBadge'
import { StatusBadge } from '@/components/badges/StatusBadge'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import type { RefundRecord, RefundStatus, ProblemDetails } from '@/types/api'

export interface RefundQueueTableProps {
  onSelectRefund?: (refundId: string) => void
  initialStatus?: string
  className?: string
  sseConnected?: boolean
}

export type StatusTabId =
  | 'all'
  | 'pending'
  | 'completed'
  | 'escalated'
  | 'awaiting_clarification'

interface StatusTabConfig {
  id: StatusTabId
  label: string
  statusFilter?: RefundStatus
}

const STATUS_TABS: StatusTabConfig[] = [
  { id: 'all', label: 'All' },
  { id: 'pending', label: 'Pending', statusFilter: 'pending' },
  { id: 'completed', label: 'Completed', statusFilter: 'completed' },
  { id: 'escalated', label: 'Escalated', statusFilter: 'escalated' },
  {
    id: 'awaiting_clarification',
    label: 'Awaiting Clarification',
    statusFilter: 'awaiting_clarification',
  },
]

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
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return timestamp
  }
}

function getRefundId(record: RefundRecord): string {
  return record.refundId || (record as Record<string, unknown>).refund_id as string || ''
}

function getOrderId(record: RefundRecord): string {
  return record.orderId || (record as Record<string, unknown>).order_id as string || 'N/A'
}

function getCustomerRequestText(record: RefundRecord): string {
  return (
    record.customerRequestText ||
    (record as Record<string, unknown>).customer_request_text as string ||
    ''
  )
}

function getCreatedAt(record: RefundRecord): string {
  return record.createdAt || (record as Record<string, unknown>).created_at as string || ''
}

function getOrderAmount(record: RefundRecord): number | null | undefined {
  const rec = record as Record<string, unknown>
  if (typeof rec.orderAmount === 'number') return rec.orderAmount
  if (typeof rec.order_amount === 'number') return rec.order_amount
  return null
}

function getCategory(record: RefundRecord): string {
  return record.category || (record as Record<string, unknown>).category as string || 'General'
}

function getDecision(record: RefundRecord): string | null {
  const rec = record as Record<string, unknown>
  const override = (record.overrideDecision || rec.override_decision) as string | undefined
  if (override === 'approve' || override === 'manual_approved') return 'manual_approved'
  if (override === 'deny' || override === 'manual_denied') return 'manual_denied'

  const decision = record.decision || (rec.decision as string)
  if (decision === 'approve') return 'manual_approved'

  return decision || null
}

function getConfidenceScore(record: RefundRecord): number | null | undefined {
  const rec = record as Record<string, unknown>
  return record.confidenceScore ?? (rec.confidence_score as number | undefined)
}

function isEscalated(record: RefundRecord): boolean {
  const status = (record.status || (record as Record<string, unknown>).status as string || '')
    .toLowerCase()
    .replace(/-/g, '_')
  const decision = (getDecision(record) || '').toLowerCase().replace(/-/g, '_')
  return status === 'escalated' || decision === 'escalate'
}

export function RefundQueueTable({
  onSelectRefund,
  initialStatus = 'all',
  className,
  sseConnected = false,
}: RefundQueueTableProps) {
  const [activeTab, setActiveTab] = React.useState<StatusTabId>(() => {
    const matched = STATUS_TABS.find((t) => t.id === initialStatus || t.statusFilter === initialStatus)
    return matched ? matched.id : 'all'
  })

  // Selected tab configuration
  const currentTabConfig = STATUS_TABS.find((t) => t.id === activeTab) || STATUS_TABS[0]

  // Query refund queue
  const {
    data: refunds = [],
    isLoading,
    isFetching,
    error,
    refetch,
  } = useQuery<RefundRecord[], Error>({
    queryKey: ['refunds', activeTab],
    queryFn: () => {
      const params = currentTabConfig.statusFilter
        ? { status: currentTabConfig.statusFilter }
        : undefined
      return listRefunds(params)
    },
    // Dynamic polling: poll every 3000ms if any item has pending status; disable if SSE active
    refetchInterval: (query) => {
      if (sseConnected) return false
      const dataset = query.state.data
      if (!dataset || dataset.length === 0) return false
      const hasPending = dataset.some((r) => {
        const st = (r.status || (r as Record<string, unknown>).status as string || '')
          .toLowerCase()
          .replace(/-/g, '_')
        return st === 'pending' || st === 'processing'
      })
      return hasPending ? 3000 : false
    },
  })

  // Determine if polling is currently active for the toolbar indicator
  const hasPendingItems = React.useMemo(() => {
    return refunds.some((r) => {
      const st = (r.status || (r as Record<string, unknown>).status as string || '')
        .toLowerCase()
        .replace(/-/g, '_')
      return st === 'pending' || st === 'processing'
    })
  }, [refunds])

  const isPollingActive = !sseConnected && hasPendingItems && !isLoading && !error

  // Extract error message & details if RFC 9457 ProblemDetails
  const problemDetails = React.useMemo(() => {
    if (!error) return null
    const err = error as Error & { problem?: ProblemDetails }
    if (err.problem) {
      return err.problem
    }
    return {
      title: 'Failed to load refund queue',
      detail: error.message || 'An unexpected error occurred while communicating with the server.',
    }
  }, [error])

  // Export dropdown state and click-outside / escape listeners
  const [isExportOpen, setIsExportOpen] = React.useState(false)
  const exportDropdownRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    if (!isExportOpen) return

    const handlePointerDown = (event: MouseEvent | TouchEvent) => {
      if (
        exportDropdownRef.current &&
        !exportDropdownRef.current.contains(event.target as Node)
      ) {
        setIsExportOpen(false)
      }
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsExportOpen(false)
      }
    }

    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isExportOpen])

  const handleExportCsv = () => {
    const statusParam = activeTab === 'all' ? 'all' : (currentTabConfig.statusFilter || activeTab)
    const filename = generateExportFilename('csv', statusParam)
    const content = serializeToCsv(refunds)
    downloadExportFile(content, filename, 'text/csv; charset=utf-8')
    setIsExportOpen(false)
  }

  const handleExportJson = () => {
    const statusParam = activeTab === 'all' ? 'all' : (currentTabConfig.statusFilter || activeTab)
    const filename = generateExportFilename('json', statusParam)
    const content = serializeToJson(refunds)
    downloadExportFile(content, filename, 'application/json')
    setIsExportOpen(false)
  }

  interface BulkExportState {
    status: 'idle' | 'pending' | 'processing' | 'completed' | 'failed'
    jobId?: string
    downloadUrl?: string | null
    error?: string | null
  }

  const [bulkExportState, setBulkExportState] = React.useState<BulkExportState>({ status: 'idle' })

  const handleBulkExport = async (format: 'csv' | 'json' = 'csv') => {
    const statusFilter = activeTab === 'all' ? null : (currentTabConfig.statusFilter || (activeTab as RefundStatus))
    setBulkExportState({ status: 'pending' })
    try {
      const job = await createBulkExportJob({ format, status: statusFilter })
      setBulkExportState({ status: job.status || 'processing', jobId: job.job_id })

      // Poll until completed or failed
      const completedJob = await pollBulkExportJob(job.job_id, 300, 40)
      setBulkExportState({
        status: 'completed',
        jobId: completedJob.job_id,
        downloadUrl: completedJob.download_url,
      })

      // Automatically trigger browser download
      if (completedJob.download_url) {
        const link = document.createElement('a')
        link.href = completedJob.download_url
        link.setAttribute('download', '')
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Bulk export failed.'
      setBulkExportState({ status: 'failed', error: message })
    }
  }


  return (
    <div
      className={cn(
        'rounded-lg border border-slate-200 bg-white shadow-sm overflow-hidden flex flex-col',
        className
      )}
      data-testid="refund-queue-table-container"
    >
      {/* Table Toolbar: Status Filter Tabs & Live Status */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-slate-200 bg-slate-50/50 px-4 py-3 gap-3">
        {/* Filter Tabs */}
        <div
          role="tablist"
          aria-label="Filter refund requests by status"
          className="flex items-center space-x-1 overflow-x-auto no-scrollbar"
        >
          {STATUS_TABS.map((tab) => {
            const isActive = activeTab === tab.id
            return (
              <button
                key={tab.id}
                role="tab"
                type="button"
                id={`tab-${tab.id}`}
                aria-selected={isActive}
                aria-controls="refund-queue-panel"
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  'inline-flex items-center rounded-md px-3 py-1.5 text-xs font-medium transition-all select-none whitespace-nowrap',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400',
                  isActive
                    ? 'bg-slate-900 text-white shadow-sm'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                )}
              >
                <span>{tab.label}</span>
                {isActive && refunds && (
                  <span
                    data-testid={`tab-count-${tab.id}`}
                    className={cn(
                      'ml-1.5 rounded-full px-1.5 py-0.2 text-[10px] font-semibold',
                      isActive ? 'bg-slate-800 text-slate-200' : 'bg-slate-200 text-slate-700'
                    )}
                  >
                    {refunds.length}
                  </span>
                )}
              </button>
            )
          })}
        </div>

        {/* Polling Indicator & Manual Refresh Trigger */}
        <div className="flex items-center space-x-3 self-end sm:self-auto">
          <div
            data-testid="table-polling-indicator"
            className="flex items-center space-x-1.5 text-xs text-slate-600 font-medium"
          >
            {sseConnected ? (
              <>
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
                </span>
                <span className="text-emerald-700 font-semibold">Live - SSE connected</span>
              </>
            ) : isPollingActive ? (
              <>
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-sky-500" />
                </span>
                <span className="text-sky-700 font-semibold">Live - polling every 3s</span>
              </>
            ) : (
              <>
                <span className="h-2 w-2 rounded-full bg-slate-300" />
                <span className="text-slate-500">Idle</span>
              </>
            )}
          </div>

          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
            aria-label="Refresh table"
            className="h-8 px-2 text-slate-600 hover:text-slate-900"
          >
            <RefreshCw
              className={cn('h-3.5 w-3.5 mr-1.5', isFetching && 'animate-spin')}
              aria-hidden="true"
            />
            <span>Refresh</span>
          </Button>

          {/* Bulk Export Button */}
          <Button
            variant="outline"
            size="sm"
            data-testid="bulk-export-button"
            disabled={bulkExportState.status === 'pending' || bulkExportState.status === 'processing'}
            onClick={() => handleBulkExport('csv')}
            className="h-8 px-2.5 text-slate-600 hover:text-slate-900 border-slate-300"
          >
            {bulkExportState.status === 'pending' || bulkExportState.status === 'processing' ? (
              <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" aria-hidden="true" />
            ) : (
              <Download className="h-3.5 w-3.5 mr-1.5" aria-hidden="true" />
            )}
            <span>Bulk Export</span>
          </Button>

          {/* Export Dropdown Trigger & Menu */}
          <div className="relative inline-block text-left" ref={exportDropdownRef}>
            <Button
              variant="outline"
              size="sm"
              data-testid="export-dropdown-button"
              aria-haspopup="true"
              aria-expanded={isExportOpen}
              disabled={refunds.length === 0}
              title={refunds.length === 0 ? 'No refund requests to export' : undefined}
              onClick={() => setIsExportOpen((prev) => !prev)}
              className="h-8 px-2.5 text-slate-600 hover:text-slate-900 border-slate-300"
            >
              <Download className="h-3.5 w-3.5 mr-1.5" aria-hidden="true" />
              <span>Export</span>
            </Button>

            {isExportOpen && (
              <div
                role="menu"
                aria-orientation="vertical"
                aria-labelledby="export-dropdown-button"
                className="absolute right-0 mt-1 w-36 origin-top-right rounded-md bg-white py-1 shadow-lg ring-1 ring-black ring-opacity-5 z-20 focus:outline-none border border-slate-200"
              >
                <button
                  type="button"
                  role="menuitem"
                  data-testid="export-csv-button"
                  onClick={handleExportCsv}
                  className="w-full text-left px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-100 hover:text-slate-900 transition-colors flex items-center"
                >
                  Export as CSV
                </button>
                <button
                  type="button"
                  role="menuitem"
                  data-testid="export-json-button"
                  onClick={handleExportJson}
                  className="w-full text-left px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-100 hover:text-slate-900 transition-colors flex items-center"
                >
                  Export as JSON
                </button>
                <button
                  type="button"
                  role="menuitem"
                  data-testid="menu-bulk-export-button"
                  onClick={() => {
                    setIsExportOpen(false)
                    handleBulkExport('csv')
                  }}
                  className="w-full text-left px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-100 hover:text-slate-900 transition-colors flex items-center border-t border-slate-100 mt-1 pt-1"
                >
                  Bulk Export (Async)
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Bulk Export Status Banner */}
      {bulkExportState.status !== 'idle' && (
        <div
          data-testid="bulk-export-status"
          role={bulkExportState.status === 'failed' ? 'alert' : 'status'}
          className={cn(
            'border-b px-4 py-2.5 text-xs flex items-center justify-between gap-2 transition-colors',
            (bulkExportState.status === 'pending' || bulkExportState.status === 'processing') &&
              'border-sky-200 bg-sky-50 text-sky-800',
            bulkExportState.status === 'completed' &&
              'border-emerald-200 bg-emerald-50 text-emerald-800',
            bulkExportState.status === 'failed' &&
              'border-rose-200 bg-rose-50 text-rose-800'
          )}
        >
          <div className="flex items-center space-x-2">
            {(bulkExportState.status === 'pending' || bulkExportState.status === 'processing') && (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin text-sky-600 flex-shrink-0" />
                <span>Exporting refund requests in background... ({bulkExportState.status})</span>
              </>
            )}
            {bulkExportState.status === 'completed' && (
              <>
                <CheckCircle className="h-3.5 w-3.5 text-emerald-600 flex-shrink-0" />
                <span>Export completed! Download started.</span>
              </>
            )}
            {bulkExportState.status === 'failed' && (
              <>
                <AlertCircle className="h-3.5 w-3.5 text-rose-600 flex-shrink-0" />
                <span>Export failed: {bulkExportState.error}</span>
              </>
            )}
          </div>
          <button
            type="button"
            onClick={() => setBulkExportState({ status: 'idle' })}
            className="text-xs font-medium underline opacity-80 hover:opacity-100 ml-auto"
          >
            Dismiss
          </button>
        </div>
      )}


      {/* Error Alert Banner */}
      {problemDetails && (
        <div
          role="alert"
          data-testid="queue-error-banner"
          className="border-b border-rose-200 bg-rose-50 p-4 text-rose-900 flex items-start justify-between gap-3"
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

      {/* Table Content */}
      <div
        id="refund-queue-panel"
        role="tabpanel"
        aria-labelledby={`tab-${activeTab}`}
        className="overflow-x-auto"
      >
        <table className="w-full text-left border-collapse text-xs">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/80 text-[11px] font-semibold text-slate-500 uppercase tracking-wider select-none">
              <th scope="col" className="py-2.5 px-3 w-28">Order ID</th>
              <th scope="col" className="py-2.5 px-3 min-w-[200px]">Customer Request</th>
              <th scope="col" className="py-2.5 px-3 w-28">Category</th>
              <th scope="col" className="py-2.5 px-3 w-24">Amount</th>
              <th scope="col" className="py-2.5 px-3 w-36">Decision</th>
              <th scope="col" className="py-2.5 px-3 w-32">Status</th>
              <th scope="col" className="py-2.5 px-3 w-32">Timestamp</th>
              <th scope="col" className="py-2.5 px-3 w-28 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {isLoading ? (
              // Loading Skeleton Rows
              Array.from({ length: 5 }).map((_, index) => (
                <tr
                  key={`skeleton-row-${index}`}
                  data-testid="skeleton-row"
                  className="animate-pulse"
                >
                  <td className="py-3 px-3">
                    <div className="h-4 bg-slate-200 rounded w-16" />
                  </td>
                  <td className="py-3 px-3">
                    <div className="h-4 bg-slate-200 rounded w-48" />
                  </td>
                  <td className="py-3 px-3">
                    <div className="h-4 bg-slate-200 rounded w-20" />
                  </td>
                  <td className="py-3 px-3">
                    <div className="h-4 bg-slate-200 rounded w-12" />
                  </td>
                  <td className="py-3 px-3">
                    <div className="h-5 bg-slate-200 rounded-full w-24" />
                  </td>
                  <td className="py-3 px-3">
                    <div className="h-5 bg-slate-200 rounded-full w-20" />
                  </td>
                  <td className="py-3 px-3">
                    <div className="h-4 bg-slate-200 rounded w-24" />
                  </td>
                  <td className="py-3 px-3 text-right">
                    <div className="h-7 bg-slate-200 rounded w-16 ml-auto" />
                  </td>
                </tr>
              ))
            ) : refunds.length === 0 ? (
              // Empty State
              <tr>
                <td colSpan={8} className="py-12 text-center">
                  <div
                    data-testid="empty-state"
                    className="flex flex-col items-center justify-center space-y-2 text-slate-500"
                  >
                    <FileQuestion className="h-8 w-8 text-slate-400 stroke-1" />
                    <p className="text-sm font-medium text-slate-700">
                      No refund requests found in this view
                    </p>
                    <p className="text-xs text-slate-400">
                      Incoming requests will appear here in realtime.
                    </p>
                  </div>
                </td>
              </tr>
            ) : (
              // Table Rows
              refunds.map((record) => {
                const refundId = getRefundId(record)
                const orderId = getOrderId(record)
                const customerText = getCustomerRequestText(record)
                const category = getCategory(record)
                const amount = getOrderAmount(record)
                const decision = getDecision(record)
                const confidence = getConfidenceScore(record)
                const createdAt = getCreatedAt(record)
                const escalated = isEscalated(record)

                return (
                  <tr
                    key={refundId || orderId}
                    data-testid="refund-row"
                    data-refund-id={refundId}
                    className={cn(
                      'transition-colors hover:bg-slate-50/70',
                      escalated &&
                        'bg-amber-50/40 hover:bg-amber-50/60 border-l-4 border-l-amber-400'
                    )}
                  >
                    {/* Order ID */}
                    <td className="py-2.5 px-3 font-mono text-xs font-semibold text-slate-900 whitespace-nowrap">
                      {orderId}
                    </td>

                    {/* Customer Request Preview */}
                    <td className="py-2.5 px-3 max-w-xs text-slate-600">
                      <p className="truncate text-xs" title={customerText}>
                        {customerText || <span className="text-slate-400 italic">No description</span>}
                      </p>
                    </td>

                    {/* Category */}
                    <td className="py-2.5 px-3 whitespace-nowrap">
                      <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium bg-slate-100 text-slate-700 border border-slate-200 capitalize">
                        {category.replace(/_/g, ' ')}
                      </span>
                    </td>

                    {/* Order Amount */}
                    <td className="py-2.5 px-3 font-medium text-slate-900 whitespace-nowrap">
                      {formatCurrency(amount)}
                    </td>

                    {/* Decision Badge */}
                    <td className="py-2.5 px-3 whitespace-nowrap">
                      <DecisionBadge
                        decision={decision}
                        confidenceScore={confidence}
                      />
                    </td>

                    {/* Status Badge */}
                    <td className="py-2.5 px-3 whitespace-nowrap">
                      <StatusBadge status={record.status} />
                    </td>

                    {/* Timestamp */}
                    <td className="py-2.5 px-3 text-slate-500 whitespace-nowrap">
                      {formatTimestamp(createdAt)}
                    </td>

                    {/* Action Button */}
                    <td className="py-2.5 px-3 text-right whitespace-nowrap">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => onSelectRefund?.(refundId)}
                        className="h-7 px-2.5 text-xs text-slate-700 hover:text-slate-900"
                        aria-label={`Review order ${orderId}`}
                      >
                        Review / Inspect
                      </Button>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
