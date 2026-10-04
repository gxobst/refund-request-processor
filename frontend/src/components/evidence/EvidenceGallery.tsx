import * as React from 'react'
import {
  ImageOff,
  ExternalLink,
  ZoomIn,
  CheckCircle,
  Clock,
  AlertTriangle,
} from 'lucide-react'
import {
  Dialog,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/Dialog'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import type { EvidenceItem } from '@/types/api'

export interface EvidenceGalleryProps {
  evidence?: EvidenceItem[] | null
  isLoading?: boolean
  emptyMessage?: string
  className?: string
}

interface NormalizedEvidence {
  id: string
  filename: string
  contentType: string
  sizeBytes: number
  url: string
  createdAt?: string
  scanStatus: 'clean' | 'pending' | 'infected'
  scannedAt?: string
  threatName?: string
}

export function formatFileSize(bytes?: number | null): string {
  if (!bytes || bytes <= 0 || isNaN(bytes)) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  const size = (bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)
  return `${size} ${units[i]}`
}

function normalizeEvidenceItem(item: EvidenceItem, index: number): NormalizedEvidence {
  const rec = item as Record<string, unknown>
  const id =
    (rec.evidenceId as string) ||
    (rec.evidence_id as string) ||
    item.filename ||
    `evidence-${index}`
  const filename = item.filename || `attachment-${index + 1}`
  const contentType =
    item.contentType || (rec.content_type as string) || 'image/jpeg'
  const sizeBytes =
    typeof item.sizeBytes === 'number'
      ? item.sizeBytes
      : typeof rec.size_bytes === 'number'
      ? rec.size_bytes
      : 0
  const url = item.url || (rec.storage_key as string) || ''
  const createdAt = item.createdAt || (rec.created_at as string) || undefined

  const rawStatus =
    item.scanStatus ||
    (rec.scan_status as 'clean' | 'pending' | 'infected') ||
    (rec.scanStatus as 'clean' | 'pending' | 'infected')
  const scanStatus: 'clean' | 'pending' | 'infected' =
    rawStatus === 'infected'
      ? 'infected'
      : rawStatus === 'pending'
      ? 'pending'
      : 'clean'
  const scannedAt =
    item.scannedAt ||
    (rec.scanned_at as string) ||
    (rec.scannedAt as string) ||
    undefined
  const threatName =
    item.threatName ||
    (rec.threat_name as string) ||
    (rec.threatName as string) ||
    undefined

  return {
    id,
    filename,
    contentType,
    sizeBytes,
    url,
    createdAt,
    scanStatus,
    scannedAt,
    threatName,
  }
}

export function EvidenceGallery({
  evidence,
  isLoading = false,
  emptyMessage = 'No customer-uploaded photos or documents attached to this refund request.',
  className,
}: EvidenceGalleryProps) {
  const [selectedItem, setSelectedItem] = React.useState<NormalizedEvidence | null>(null)
  const [failedImages, setFailedImages] = React.useState<Record<string, boolean>>({})

  const normalizedList: NormalizedEvidence[] = React.useMemo(() => {
    if (!evidence || !Array.isArray(evidence)) return []
    return evidence.map(normalizeEvidenceItem)
  }, [evidence])

  const handleImageError = (id: string) => {
    setFailedImages((prev) => ({ ...prev, [id]: true }))
  }

  // Loading skeleton state
  if (isLoading) {
    return (
      <div
        data-testid="evidence-loading-skeleton"
        className={cn('grid grid-cols-2 sm:grid-cols-3 gap-3', className)}
      >
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={`skeleton-card-${i}`}
            data-testid="evidence-skeleton-card"
            className="rounded-lg border border-slate-200 bg-white p-2.5 space-y-2 animate-pulse"
          >
            <div className="aspect-square w-full rounded bg-slate-200" />
            <div className="h-3.5 bg-slate-200 rounded w-3/4" />
            <div className="h-3 bg-slate-200 rounded w-1/2" />
          </div>
        ))}
      </div>
    )
  }

  // Empty state
  if (normalizedList.length === 0) {
    return (
      <div
        data-testid="evidence-empty-state"
        className={cn(
          'flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50/60 p-8 text-center',
          className
        )}
      >
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-400 mb-3">
          <ImageOff className="h-6 w-6 stroke-1" aria-hidden="true" />
        </div>
        <h4 className="text-sm font-semibold text-slate-800">No evidence attachments</h4>
        <p className="mt-1 text-xs text-slate-500 max-w-sm">{emptyMessage}</p>
      </div>
    )
  }

  return (
    <>
      <div
        data-testid="evidence-gallery-grid"
        className={cn('grid grid-cols-2 sm:grid-cols-3 gap-3', className)}
      >
        {normalizedList.map((item) => {
          const isBroken = failedImages[item.id]
          const isInfected = item.scanStatus === 'infected'

          return (
            <div
              key={item.id}
              data-testid="evidence-card"
              className={cn(
                'group relative flex flex-col rounded-lg border bg-white p-2.5 shadow-sm transition-all',
                isInfected
                  ? 'border-red-300 bg-red-50/20 cursor-not-allowed'
                  : 'border-slate-200 hover:border-slate-300 hover:shadow-md cursor-pointer'
              )}
              onClick={isInfected ? undefined : () => setSelectedItem(item)}
              role="button"
              tabIndex={isInfected ? -1 : 0}
              onKeyDown={(e) => {
                if (isInfected) return
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  setSelectedItem(item)
                }
              }}
              aria-label={isInfected ? `Quarantined evidence ${item.filename}` : `View evidence ${item.filename}`}
            >
              {/* Thumbnail Container */}
              <div className="relative aspect-square w-full overflow-hidden rounded bg-slate-100 border border-slate-200/80 mb-2">
                {isInfected ? (
                  <div
                    data-testid="evidence-infected-blocked"
                    className="flex h-full w-full flex-col items-center justify-center bg-red-50 p-2 text-center text-red-600 select-none"
                  >
                    <AlertTriangle className="h-8 w-8 mb-1 text-red-600 stroke-1" />
                    <span className="text-xs font-semibold text-red-700">Preview Blocked</span>
                    <span className="text-[10px] text-red-500">Security Threat Detected</span>
                  </div>
                ) : isBroken ? (
                  <div
                    data-testid="image-fallback"
                    className="flex h-full w-full flex-col items-center justify-center bg-slate-100 p-2 text-center text-slate-400"
                  >
                    <ImageOff className="h-6 w-6 mb-1 text-slate-400 stroke-1" />
                    <span className="text-[11px] font-medium text-slate-500">
                      Preview unavailable
                    </span>
                  </div>
                ) : (
                  <>
                    <img
                      src={item.url}
                      alt={item.filename}
                      onError={() => handleImageError(item.id)}
                      className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-105"
                      loading="lazy"
                    />
                    <div className="absolute inset-0 bg-slate-950/20 opacity-0 transition-opacity group-hover:opacity-100 flex items-center justify-center">
                      <span className="inline-flex items-center rounded bg-slate-900/80 px-2 py-1 text-[11px] font-medium text-white backdrop-blur-sm">
                        <ZoomIn className="h-3 w-3 mr-1" />
                        Enlarge
                      </span>
                    </div>
                  </>
                )}
              </div>

              {/* Card Metadata */}
              <div className="space-y-1">
                <div className="flex items-center justify-between gap-1">
                  <p
                    className="truncate text-xs font-semibold text-slate-900"
                    title={item.filename}
                  >
                    {item.filename}
                  </p>
                </div>

                <div className="flex items-center justify-between text-[11px] text-slate-500 pt-0.5">
                  <span>{formatFileSize(item.sizeBytes)}</span>
                  <span className="rounded bg-slate-100 border border-slate-200 px-1 py-0.2 font-mono text-[10px] text-slate-600 uppercase">
                    {item.contentType}
                  </span>
                </div>

                {/* Scan Status Badge */}
                <div className="pt-1 flex items-center gap-1.5 flex-wrap">
                  {item.scanStatus === 'clean' && (
                    <span
                      data-testid="evidence-scan-badge-clean"
                      className="inline-flex items-center gap-1 rounded bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 border border-emerald-200"
                    >
                      <CheckCircle className="h-3 w-3 text-emerald-600" />
                      Clean
                    </span>
                  )}
                  {item.scanStatus === 'pending' && (
                    <span
                      data-testid="evidence-scan-badge-pending"
                      className="inline-flex items-center gap-1 rounded bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800 border border-amber-200"
                    >
                      <Clock className="h-3 w-3 text-amber-600 animate-spin" />
                      Scanning...
                    </span>
                  )}
                  {item.scanStatus === 'infected' && (
                    <span
                      data-testid="evidence-scan-badge-infected"
                      className="inline-flex items-center gap-1 rounded bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-700 border border-red-200"
                    >
                      <AlertTriangle className="h-3 w-3 text-red-600" />
                      {item.threatName || 'Infected'}
                    </span>
                  )}
                </div>

                {/* Quarantined Warning Banner */}
                {isInfected && (
                  <div
                    data-testid="infected-evidence-warning"
                    className="mt-2 rounded bg-red-100 p-2 text-xs font-medium text-red-800 border border-red-200 flex items-start gap-1.5"
                  >
                    <AlertTriangle className="h-3.5 w-3.5 text-red-600 shrink-0 mt-0.5" />
                    <span>This file has been quarantined by automated malware inspection.</span>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Accessible Click-to-Zoom Modal */}
      {selectedItem && (
        <Dialog
          isOpen={Boolean(selectedItem)}
          onClose={() => setSelectedItem(null)}
          className="max-w-3xl w-full"
        >
          <DialogHeader>
            <DialogTitle className="text-base font-semibold text-slate-900 truncate pr-6" title={selectedItem.filename}>
              {selectedItem.filename}
            </DialogTitle>
            <DialogDescription className="text-xs text-slate-500">
              {formatFileSize(selectedItem.sizeBytes)} • {selectedItem.contentType}
            </DialogDescription>
          </DialogHeader>

          {/* Modal Enlarged Image Body */}
          <div className="my-4 flex items-center justify-center overflow-hidden rounded-md bg-slate-950/5 p-2">
            {failedImages[selectedItem.id] ? (
              <div className="flex flex-col items-center justify-center p-12 text-slate-400">
                <ImageOff className="h-12 w-12 mb-2 stroke-1" />
                <p className="text-sm font-medium text-slate-600">Full image preview unavailable</p>
                <p className="text-xs text-slate-400 mt-1">The image could not be loaded from storage.</p>
              </div>
            ) : (
              <img
                data-testid="zoom-modal-image"
                src={selectedItem.url}
                alt={selectedItem.filename}
                className="max-h-[75vh] w-auto max-w-full rounded object-contain shadow-sm"
              />
            )}
          </div>

          <DialogFooter className="mt-2 flex items-center justify-between sm:justify-between w-full">
            {selectedItem.url ? (
              <a
                href={selectedItem.url}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="open-original-link"
                className="inline-flex items-center text-xs font-medium text-sky-600 hover:text-sky-800 transition-colors"
              >
                <ExternalLink className="h-3.5 w-3.5 mr-1" />
                Open original in new tab
              </a>
            ) : (
              <span />
            )}

            <Button
              variant="outline"
              size="sm"
              onClick={() => setSelectedItem(null)}
            >
              Close
            </Button>
          </DialogFooter>
        </Dialog>
      )}
    </>
  )
}
