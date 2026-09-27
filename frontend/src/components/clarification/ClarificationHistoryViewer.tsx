import * as React from 'react'
import {
  HelpCircle,
  Bot,
  User,
  Clock,
  Paperclip,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ClarificationTurn } from '@/types/api'

export interface ClarificationHistoryViewerProps {
  history?: ClarificationTurn[] | null
  emptyMessage?: string
  onSelectEvidence?: (evidenceId: string) => void
  className?: string
}

interface NormalizedTurn {
  cycle: number
  prompt: string | null
  response: string | null
  timestamp: string
  evidenceIds: string[]
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

function normalizeTurn(turn: ClarificationTurn, index: number): NormalizedTurn {
  const rec = turn as Record<string, unknown>
  const cycle = typeof turn.cycle === 'number' ? turn.cycle : index + 1
  const prompt = turn.prompt ?? (rec.prompt as string) ?? null
  const response = turn.response ?? (rec.response as string) ?? null
  const timestamp = turn.timestamp ?? (rec.timestamp as string) ?? ''

  let evidenceIds: string[] = []
  if (Array.isArray(turn.evidenceIds)) {
    evidenceIds = turn.evidenceIds
  } else if (Array.isArray(rec.evidence_ids)) {
    evidenceIds = rec.evidence_ids as string[]
  }

  return {
    cycle,
    prompt,
    response,
    timestamp,
    evidenceIds,
  }
}

export function ClarificationHistoryViewer({
  history,
  emptyMessage = 'No clarification cycles or customer inquiries recorded for this refund request.',
  onSelectEvidence,
  className,
}: ClarificationHistoryViewerProps) {
  const normalizedTurns: NormalizedTurn[] = React.useMemo(() => {
    if (!history || !Array.isArray(history)) return []
    // Sort turns chronologically by cycle (or timestamp)
    return [...history].map(normalizeTurn).sort((a, b) => a.cycle - b.cycle)
  }, [history])

  // Empty state
  if (normalizedTurns.length === 0) {
    return (
      <div
        data-testid="clarification-empty-state"
        className={cn(
          'flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50/60 p-8 text-center',
          className
        )}
      >
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-400 mb-3">
          <HelpCircle className="h-6 w-6 stroke-1" aria-hidden="true" />
        </div>
        <h4 className="text-sm font-semibold text-slate-800">No clarification history</h4>
        <p className="mt-1 text-xs text-slate-500 max-w-sm">{emptyMessage}</p>
      </div>
    )
  }

  return (
    <div
      data-testid="clarification-timeline-container"
      className={cn('relative space-y-6', className)}
    >
      <ol role="list" className="relative border-l-2 border-slate-200 ml-3.5 space-y-6">
        {normalizedTurns.map((turn, index) => {
          const hasEvidence = turn.evidenceIds.length > 0
          const hasResponse = Boolean(turn.response && turn.response.trim().length > 0)
          const hasPrompt = Boolean(turn.prompt && turn.prompt.trim().length > 0)

          return (
            <li
              key={`cycle-${turn.cycle}-${index}`}
              data-testid="clarification-turn-item"
              data-cycle={turn.cycle}
              className="ml-6 relative"
            >
              {/* Timeline marker node */}
              <span
                data-testid="turn-marker"
                className="absolute -left-[31px] top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-slate-100 ring-4 ring-white border-2 border-slate-400"
                aria-hidden="true"
              />

              {/* Turn Header Metadata */}
              <div className="flex flex-wrap items-center justify-between gap-2 mb-2.5">
                <div className="flex items-center space-x-2">
                  <span
                    data-testid="cycle-badge"
                    className="inline-flex items-center rounded-md bg-slate-900 px-2 py-0.5 text-xs font-semibold text-white shadow-sm"
                  >
                    Cycle {turn.cycle}
                  </span>
                  <span className="text-xs font-medium text-slate-500">
                    Clarification Turn
                  </span>
                </div>
                <time
                  data-testid="turn-timestamp"
                  dateTime={turn.timestamp}
                  className="text-[11px] font-medium text-slate-500"
                >
                  {formatTimestamp(turn.timestamp)}
                </time>
              </div>

              {/* Turn Cards Container */}
              <div className="space-y-3">
                {/* Inquiry Prompt Card */}
                {hasPrompt ? (
                  <div
                    data-testid="inquiry-prompt-card"
                    className="rounded-lg border border-slate-200 bg-slate-50 p-3.5 space-y-1.5 shadow-sm"
                  >
                    <div className="flex items-center space-x-2 text-slate-700">
                      <Bot className="h-4 w-4 text-slate-500" />
                      <span className="text-xs font-semibold uppercase tracking-wider text-slate-600">
                        Inquiry Prompt
                      </span>
                    </div>
                    <p className="text-xs text-slate-800 leading-relaxed whitespace-pre-wrap">
                      {turn.prompt}
                    </p>
                  </div>
                ) : (
                  <div
                    data-testid="inquiry-prompt-subtle-notice"
                    className="rounded border border-dashed border-slate-200 bg-slate-50/50 p-2 text-xs text-slate-500 italic"
                  >
                    Direct customer submission
                  </div>
                )}

                {/* Customer Response Card */}
                {hasResponse ? (
                  <div
                    data-testid="customer-response-card"
                    className="rounded-lg border border-sky-200 bg-sky-50/60 p-3.5 space-y-1.5 shadow-sm"
                  >
                    <div className="flex items-center space-x-2 text-sky-800">
                      <User className="h-4 w-4 text-sky-600" />
                      <span className="text-xs font-semibold uppercase tracking-wider text-sky-700">
                        Customer Response
                      </span>
                    </div>
                    <p className="text-xs text-slate-800 leading-relaxed whitespace-pre-wrap">
                      {turn.response}
                    </p>
                  </div>
                ) : (
                  <div
                    data-testid="awaiting-response-indicator"
                    className="flex items-center space-x-2 rounded-lg border border-amber-200 bg-amber-50/80 p-3 text-amber-800 text-xs font-medium shadow-sm"
                  >
                    <Clock className="h-4 w-4 text-amber-600 animate-pulse flex-shrink-0" />
                    <span>Awaiting customer response</span>
                  </div>
                )}

                {/* Linked Evidence Attachments Row */}
                {hasEvidence && (
                  <div
                    data-testid="linked-evidence-row"
                    className="flex flex-wrap items-center gap-1.5 pt-1 text-xs"
                  >
                    <div className="flex items-center space-x-1 text-slate-500 mr-1">
                      <Paperclip className="h-3.5 w-3.5 text-slate-400" />
                      <span className="text-[11px] font-medium">
                        {turn.evidenceIds.length} attached:
                      </span>
                    </div>
                    {turn.evidenceIds.map((evidenceId) => (
                      <button
                        key={evidenceId}
                        type="button"
                        role="button"
                        data-testid="evidence-id-chip"
                        onClick={() => onSelectEvidence?.(evidenceId)}
                        className={cn(
                          'inline-flex items-center rounded-md border border-slate-300 bg-white px-2 py-0.5 font-mono text-[11px] text-slate-700 shadow-sm transition-colors',
                          'hover:bg-slate-50 hover:border-slate-400 hover:text-slate-900',
                          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400'
                        )}
                        aria-label={`View evidence ${evidenceId}`}
                      >
                        {evidenceId}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
