import type { RefundRecord } from '../types/api'

export const CSV_HEADERS = [
  'Refund ID',
  'Order ID',
  'Status',
  'Decision',
  'Category',
  'Refund Amount',
  'Confidence Score',
  'Customer Request',
  'Decision Reasoning',
  'Override Decision',
  'Override Reason',
  'Created At',
  'Updated At',
] as const

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

/**
 * Serializes an array of RefundRecord objects to an RFC 4180 compliant CSV string.
 * Uses 13 standard columns in exact order.
 * Outputs header row followed by a newline for an empty array.
 */
export function serializeToCsv(records: RefundRecord[]): string {
  const headerRow = CSV_HEADERS.join(',')

  if (!records || records.length === 0) {
    return `${headerRow}\r\n`
  }

  const rows = records.map((record) => {
    const rec = (record || {}) as Record<string, unknown>

    const refundId = record?.refundId ?? rec.refund_id ?? ''
    const orderId = record?.orderId ?? rec.order_id ?? ''
    const status = record?.status ?? rec.status ?? ''
    const decision = record?.decision ?? rec.decision ?? ''
    const category = record?.category ?? rec.category ?? ''

    // Refund Amount check
    const amountVal =
      rec.refundAmount ??
      rec.refund_amount ??
      rec.orderAmount ??
      rec.order_amount ??
      ''
    const refundAmount = amountVal !== '' && amountVal !== null && amountVal !== undefined
      ? amountVal
      : ''

    // Confidence Score check
    const confVal = record?.confidenceScore ?? rec.confidence_score
    const confidenceScore = confVal !== null && confVal !== undefined ? confVal : ''

    const customerRequest = record?.customerRequestText ?? rec.customer_request_text ?? ''
    const reasoning = record?.reasoning ?? rec.reasoning ?? ''
    const overrideDecision = record?.overrideDecision ?? rec.override_decision ?? ''
    const overrideReason = record?.overrideReason ?? rec.override_reason ?? ''
    const createdAt = record?.createdAt ?? rec.created_at ?? ''
    const updatedAt = record?.updatedAt ?? rec.updated_at ?? ''

    return [
      formatCsvCell(refundId),
      formatCsvCell(orderId),
      formatCsvCell(status),
      formatCsvCell(decision),
      formatCsvCell(category),
      formatCsvCell(refundAmount),
      formatCsvCell(confidenceScore),
      formatCsvCell(customerRequest),
      formatCsvCell(reasoning),
      formatCsvCell(overrideDecision),
      formatCsvCell(overrideReason),
      formatCsvCell(createdAt),
      formatCsvCell(updatedAt),
    ].join(',')
  })

  return `${headerRow}\r\n${rows.join('\r\n')}\r\n`
}

/**
 * Serializes an array of RefundRecord objects to a formatted JSON string (2-space indent).
 */
export function serializeToJson(records: RefundRecord[]): string {
  return JSON.stringify(records ?? [], null, 2)
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
