import type { RefundRecord } from '../types/api'

export interface ExportColumnDefinition {
  id: string
  label: string
}

export const EXPORT_COLUMNS: readonly ExportColumnDefinition[] = [
  { id: 'refund_id', label: 'Refund ID' },
  { id: 'order_id', label: 'Order ID' },
  { id: 'status', label: 'Status' },
  { id: 'decision', label: 'Decision' },
  { id: 'category', label: 'Category' },
  { id: 'refund_amount', label: 'Refund Amount' },
  { id: 'confidence_score', label: 'Confidence Score' },
  { id: 'customer_request_text', label: 'Customer Request' },
  { id: 'reasoning', label: 'Decision Reasoning' },
  { id: 'override_decision', label: 'Override Decision' },
  { id: 'override_reason', label: 'Override Reason' },
  { id: 'created_at', label: 'Created At' },
  { id: 'updated_at', label: 'Updated At' },
] as const

export const CSV_HEADERS = EXPORT_COLUMNS.map((c) => c.label)

export function resolveColumnId(col: string): string | null {
  const norm = col.trim().toLowerCase().replace(/-/g, '_')
  const found = EXPORT_COLUMNS.find(
    (c) =>
      c.id.toLowerCase() === norm ||
      c.label.toLowerCase() === norm ||
      c.label.toLowerCase().replace(/\s+/g, '_') === norm ||
      (c.id === 'customer_request_text' && (norm === 'customer_request' || norm === 'customer request')) ||
      (c.id === 'reasoning' && (norm === 'decision_reasoning' || norm === 'decision reasoning'))
  )
  return found ? found.id : null
}

/**
 * Properly escapes a field value according to RFC 4180 rules.
 * Wraps values containing commas, newlines, or double quotes in double quotes,
 * and escapes inner quotes as `""`.
 * Safely handles null, undefined, or missing values by returning empty string.
 */
export function formatCsvCell(value: unknown): string {
  if (value === null || value === undefined) {
    return ''
  }
  const str = String(value)
  if (str.includes('"') || str.includes(',') || str.includes('\n') || str.includes('\r')) {
    return `"${str.replace(/"/g, '""')}"`
  }
  return str
}

export function getColumnValue(record: RefundRecord, colId: string): unknown {
  const rec = (record || {}) as Record<string, unknown>
  switch (colId) {
    case 'refund_id':
      return record?.refundId ?? rec.refund_id ?? ''
    case 'order_id':
      return record?.orderId ?? rec.order_id ?? ''
    case 'status':
      return record?.status ?? rec.status ?? ''
    case 'decision':
      return record?.decision ?? rec.decision ?? ''
    case 'category':
      return record?.category ?? rec.category ?? ''
    case 'refund_amount': {
      const amountVal =
        rec.refundAmount ??
        rec.refund_amount ??
        rec.orderAmount ??
        rec.order_amount ??
        ''
      return amountVal !== '' && amountVal !== null && amountVal !== undefined
        ? amountVal
        : ''
    }
    case 'confidence_score': {
      const confVal = record?.confidenceScore ?? rec.confidence_score
      return confVal !== null && confVal !== undefined ? confVal : ''
    }
    case 'customer_request_text':
      return record?.customerRequestText ?? rec.customer_request_text ?? ''
    case 'reasoning':
      return record?.reasoning ?? rec.reasoning ?? ''
    case 'override_decision':
      return record?.overrideDecision ?? rec.override_decision ?? ''
    case 'override_reason':
      return record?.overrideReason ?? rec.override_reason ?? ''
    case 'created_at':
      return record?.createdAt ?? rec.created_at ?? ''
    case 'updated_at':
      return record?.updatedAt ?? rec.updated_at ?? ''
    default:
      return rec[colId] ?? ''
  }
}

/**
 * Serializes an array of RefundRecord objects to an RFC 4180 compliant CSV string.
 * Filters and orders columns according to optional `columns` parameter (falling back to all 13 standard columns).
 */
export function serializeToCsv(records: RefundRecord[], columns?: string[]): string {
  let targetCols: ExportColumnDefinition[]
  if (columns && columns.length > 0) {
    targetCols = columns
      .map((c) => {
        const id = resolveColumnId(c)
        if (!id) return null
        const def = EXPORT_COLUMNS.find((col) => col.id === id)
        return def || { id, label: id }
      })
      .filter((c): c is ExportColumnDefinition => c !== null)
  } else {
    targetCols = [...EXPORT_COLUMNS]
  }

  const headerRow = targetCols.map((c) => c.label).join(',')

  if (!records || records.length === 0) {
    return `${headerRow}\r\n`
  }

  const rows = records.map((record) => {
    return targetCols
      .map((col) => formatCsvCell(getColumnValue(record, col.id)))
      .join(',')
  })

  return `${headerRow}\r\n${rows.join('\r\n')}\r\n`
}

/**
 * Serializes an array of RefundRecord objects to a formatted JSON string (2-space indent).
 * Filters and orders keys according to optional `columns` parameter (falling back to full record serialization).
 */
export function serializeToJson(records: RefundRecord[], columns?: string[]): string {
  if (!columns || columns.length === 0) {
    return JSON.stringify(records ?? [], null, 2)
  }

  const resolvedIds = columns
    .map((c) => resolveColumnId(c))
    .filter((id): id is string => id !== null)

  const projected = (records || []).map((record) => {
    const rec = (record || {}) as Record<string, unknown>
    const item: Record<string, unknown> = {}
    for (const id of resolvedIds) {
      if (id === 'refund_amount') {
        const amt =
          rec.refundAmount ??
          rec.refund_amount ??
          rec.orderAmount ??
          rec.order_amount ??
          null
        item[id] = amt
      } else if (id === 'confidence_score') {
        const conf = record?.confidenceScore ?? rec.confidence_score ?? null
        item[id] = conf
      } else if (id === 'refund_id') {
        item[id] = record?.refundId ?? rec.refund_id ?? ''
      } else if (id === 'order_id') {
        item[id] = record?.orderId ?? rec.order_id ?? ''
      } else if (id === 'customer_request_text') {
        item[id] = record?.customerRequestText ?? rec.customer_request_text ?? ''
      } else {
        item[id] = rec[id] ?? null
      }
    }
    return item
  })

  return JSON.stringify(projected, null, 2)
}

/**
 * Generates export filename following `refunds-<status>-<YYYYMMDD-HHmmss>.<format>`.
 * Defaults status to 'all' if not provided or empty.
 */
export function generateExportFilename(
  format: 'csv' | 'json',
  statusFilter?: string,
  date: Date = new Date()
): string {
  const status = statusFilter && statusFilter.trim() ? statusFilter.trim().toLowerCase() : 'all'
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')
  const timestamp = `${year}${month}${day}-${hours}${minutes}${seconds}`
  const ext = format.toLowerCase().replace(/^\./, '')
  return `refunds-${status}-${timestamp}.${ext}`
}

/**
 * Initiates a browser download for exported file content using a Blob and anchor click.
 */
export function downloadExportFile(content: string, filename: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType })
  const url = typeof URL.createObjectURL === 'function' ? URL.createObjectURL(blob) : ''
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  if (typeof URL.revokeObjectURL === 'function' && url) {
    URL.revokeObjectURL(url)
  }
}
