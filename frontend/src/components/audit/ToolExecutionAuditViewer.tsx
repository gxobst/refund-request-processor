import * as React from 'react'
import {
  ShieldCheck,
  Truck,
  CreditCard,
  Terminal,
  Clock,
  ChevronDown,
  ChevronRight,
  Copy,
  Check,
  AlertCircle,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ToolCallAudit } from '@/types/api'

export interface ToolExecutionAuditViewerProps {
  toolCalls?: ToolCallAudit[] | null
  emptyMessage?: string
  className?: string
}

interface NormalizedToolCall {
  toolName: string
  inputArgs: Record<string, unknown>
  rawOutput: Record<string, unknown>
  durationSeconds?: number | null
  timestamp: string
}

export function formatDuration(seconds?: number | null): string | null {
  if (seconds === null || seconds === undefined || isNaN(seconds)) return null
  if (seconds < 1) {
    return `${Math.round(seconds * 1000)}ms`
  }
  return `${seconds.toFixed(2)}s`
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
      second: '2-digit',
    })
  } catch {
    return timestamp
  }
}

function normalizeToolCall(item: ToolCallAudit): NormalizedToolCall {
  const rec = item as Record<string, unknown>
  const toolName = (rec.toolName as string) || (rec.tool_name as string) || 'unknown_tool'
  const inputArgs =
    (rec.inputArgs as Record<string, unknown>) ||
    (rec.input_args as Record<string, unknown>) ||
    (rec.tool_input as Record<string, unknown>) ||
    {}
  const rawOutput =
    (rec.rawOutput as Record<string, unknown>) ||
    (rec.raw_output as Record<string, unknown>) ||
    (rec.tool_output as Record<string, unknown>) ||
    {}
  const durationSeconds =
    typeof rec.durationSeconds === 'number'
      ? rec.durationSeconds
      : typeof rec.duration_seconds === 'number'
      ? rec.duration_seconds
      : null
  const timestamp = (rec.timestamp as string) || ''

  return {
    toolName,
    inputArgs,
    rawOutput,
    durationSeconds,
    timestamp,
  }
}

function hasOutputError(rawOutput: Record<string, unknown>): boolean {
  if (!rawOutput || typeof rawOutput !== 'object') return false
  if ('error' in rawOutput && Boolean(rawOutput.error)) return true
  if (rawOutput.status === 'error' || rawOutput.status === 'failed') return true
  return false
}

interface JsonCodeBlockProps {
  data: Record<string, unknown>
  title: string
  isError?: boolean
}

function JsonCodeBlock({ data, title, isError = false }: JsonCodeBlockProps) {
  const [copied, setCopied] = React.useState(false)
  const jsonString = React.useMemo(() => JSON.stringify(data, null, 2), [data])

  const handleCopy = async () => {
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(jsonString)
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      }
    } catch {
      // Fallback
    }
  }

  return (
    <div
      data-testid="json-code-block"
      className={cn(
        'relative rounded-md border font-mono text-xs overflow-hidden',
        isError ? 'border-rose-300 bg-rose-50/20' : 'border-slate-200 bg-slate-900 text-slate-100'
      )}
    >
      <div
        className={cn(
          'flex items-center justify-between px-3 py-1.5 border-b text-[11px] font-sans',
          isError
            ? 'border-rose-200 bg-rose-100/70 text-rose-800'
            : 'border-slate-800 bg-slate-950 text-slate-400'
        )}
      >
        <span className="font-semibold">{title}</span>
        <button
          type="button"
          onClick={handleCopy}
          aria-label={`Copy ${title} JSON`}
          data-testid="copy-json-button"
          className={cn(
            'inline-flex items-center space-x-1 rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors',
            isError
              ? 'hover:bg-rose-200 text-rose-800'
              : 'hover:bg-slate-800 text-slate-300 hover:text-white'
          )}
        >
          {copied ? (
            <>
              <Check className="h-3 w-3 text-emerald-400" />
              <span>Copied!</span>
            </>
          ) : (
            <>
              <Copy className="h-3 w-3" />
              <span>Copy JSON</span>
            </>
          )}
        </button>
      </div>
      <pre className="p-3 overflow-x-auto max-h-60 leading-relaxed">
        <code className={cn(isError ? 'text-rose-900' : 'text-slate-100')}>
          {jsonString}
        </code>
      </pre>
    </div>
  )
}

function ToolCard({ tool }: { tool: NormalizedToolCall }) {
  const [showInputs, setShowInputs] = React.useState(true)
  const [showOutputs, setShowOutputs] = React.useState(true)

  const isCarrier = tool.toolName === 'query_carrier_tracking'
  const isPayment = tool.toolName === 'query_payment_transaction'
  const isError = hasOutputError(tool.rawOutput)
  const durationText = formatDuration(tool.durationSeconds)

  return (
    <div
      data-testid="tool-call-card"
      data-tool-name={tool.toolName}
      className="rounded-lg border border-slate-200 bg-white shadow-sm overflow-hidden space-y-3 p-4 transition-all"
    >
      {/* Header: Tool Identity, Status, Duration & Timestamp */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
        <div className="flex items-center space-x-2">
          {/* Tool Identity Badge */}
          {isCarrier ? (
            <span
              data-testid="tool-badge-carrier"
              className="inline-flex items-center space-x-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold border bg-blue-50 text-blue-700 border-blue-200"
            >
              <Truck className="h-3.5 w-3.5" />
              <span>query_carrier_tracking</span>
            </span>
          ) : isPayment ? (
            <span
              data-testid="tool-badge-payment"
              className="inline-flex items-center space-x-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold border bg-emerald-50 text-emerald-700 border-emerald-200"
            >
              <CreditCard className="h-3.5 w-3.5" />
              <span>query_payment_transaction</span>
            </span>
          ) : (
            <span
              data-testid="tool-badge-fallback"
              className="inline-flex items-center space-x-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold border bg-slate-100 text-slate-700 border-slate-200"
            >
              <Terminal className="h-3.5 w-3.5" />
              <span>{tool.toolName}</span>
            </span>
          )}

          {/* Error Status Badge */}
          {isError && (
            <span
              data-testid="tool-error-badge"
              className="inline-flex items-center space-x-1 rounded-full px-2 py-0.5 text-[11px] font-semibold border bg-rose-50 text-rose-700 border-rose-200"
            >
              <AlertCircle className="h-3 w-3" />
              <span>Execution Error</span>
            </span>
          )}
        </div>

        {/* Duration & Timestamp */}
        <div className="flex items-center space-x-3 text-xs text-slate-500">
          {durationText && (
            <span
              data-testid="tool-duration-badge"
              className="inline-flex items-center space-x-1 rounded bg-slate-100 px-2 py-0.5 font-mono text-[11px] text-slate-700 border border-slate-200"
            >
              <Clock className="h-3 w-3 text-slate-400" />
              <span>{durationText}</span>
            </span>
          )}
          <time data-testid="tool-timestamp" dateTime={tool.timestamp} className="text-[11px]">
            {formatTimestamp(tool.timestamp)}
          </time>
        </div>
      </div>

      {/* Collapsible Disclosure Panels */}
      <div className="space-y-2 pt-1">
        {/* Input Arguments Panel */}
        <div className="space-y-1">
          <button
            type="button"
            onClick={() => setShowInputs((prev) => !prev)}
            aria-expanded={showInputs}
            data-testid="toggle-inputs-button"
            className="flex items-center space-x-1.5 text-xs font-semibold text-slate-700 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 rounded py-1"
          >
            {showInputs ? (
              <ChevronDown className="h-3.5 w-3.5 text-slate-500" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 text-slate-500" />
            )}
            <span>Input Arguments</span>
          </button>
          {showInputs && (
            <div data-testid="inputs-content" className="pt-1">
              <JsonCodeBlock data={tool.inputArgs} title="Inputs" />
            </div>
          )}
        </div>

        {/* Output Results Panel */}
        <div className="space-y-1">
          <button
            type="button"
            onClick={() => setShowOutputs((prev) => !prev)}
            aria-expanded={showOutputs}
            data-testid="toggle-outputs-button"
            className="flex items-center space-x-1.5 text-xs font-semibold text-slate-700 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 rounded py-1"
          >
            {showOutputs ? (
              <ChevronDown className="h-3.5 w-3.5 text-slate-500" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 text-slate-500" />
            )}
            <span>Execution Output</span>
          </button>
          {showOutputs && (
            <div data-testid="outputs-content" className="pt-1">
              <JsonCodeBlock data={tool.rawOutput} title="Raw Output" isError={isError} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export function ToolExecutionAuditViewer({
  toolCalls,
  emptyMessage = 'No external tool verifications or carrier queries were triggered during evaluation.',
  className,
}: ToolExecutionAuditViewerProps) {
  const normalizedCalls: NormalizedToolCall[] = React.useMemo(() => {
    if (!toolCalls || !Array.isArray(toolCalls)) return []
    return toolCalls.map(normalizeToolCall)
  }, [toolCalls])

  // Empty state
  if (normalizedCalls.length === 0) {
    return (
      <div
        data-testid="tool-audit-empty-state"
        className={cn(
          'flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50/60 p-8 text-center',
          className
        )}
      >
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-400 mb-3">
          <ShieldCheck className="h-6 w-6 stroke-1" aria-hidden="true" />
        </div>
        <h4 className="text-sm font-semibold text-slate-800">No external tools executed</h4>
        <p className="mt-1 text-xs text-slate-500 max-w-sm">{emptyMessage}</p>
      </div>
    )
  }

  return (
    <div
      data-testid="tool-audit-list-container"
      className={cn('space-y-4', className)}
    >
      {normalizedCalls.map((tool, idx) => (
        <ToolCard key={`${tool.toolName}-${tool.timestamp}-${idx}`} tool={tool} />
      ))}
    </div>
  )
}
