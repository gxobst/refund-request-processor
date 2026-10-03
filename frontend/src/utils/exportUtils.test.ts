import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  serializeToCsv,
  serializeToJson,
  generateExportFilename,
  downloadExportFile,
  CSV_HEADERS,
} from './exportUtils'
import type { RefundRecord } from '../types/api'

describe('exportUtils', () => {
  describe('serializeToCsv', () => {
    it('outputs header row followed by newline when records array is empty', () => {
      const csv = serializeToCsv([])
      expect(csv).toBe(`${CSV_HEADERS.join(',')}\r\n`)
      expect(csv.endsWith('\n')).toBe(true)
    })

    it('includes all 13 standard CSV headers in exact required order', () => {
      expect(CSV_HEADERS).toEqual([
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
      ])
    })

    it('correctly serializes a complete refund record', () => {
      const mockRecord: RefundRecord = {
        refundId: 'ref_123',
        orderId: 'ORD-1001',
        status: 'completed',
        decision: 'auto_approve',
        category: 'damaged',
        confidenceScore: 0.95,
        customerRequestText: 'Item arrived broken',
        reasoning: 'Eligible damaged item within return window',
        overrideDecision: null,
        overrideReason: null,
        createdAt: '2026-10-01T10:00:00Z',
        updatedAt: '2026-10-01T10:05:00Z',
      }
      // Inject refundAmount into the record
      ;(mockRecord as Record<string, unknown>).refundAmount = 49.99

      const csv = serializeToCsv([mockRecord])
      const lines = csv.split('\r\n').filter(Boolean)

      expect(lines).toHaveLength(2)
      expect(lines[0]).toBe(CSV_HEADERS.join(','))
      expect(lines[1]).toBe(
        'ref_123,ORD-1001,completed,auto_approve,damaged,49.99,0.95,Item arrived broken,Eligible damaged item within return window,,,2026-10-01T10:00:00Z,2026-10-01T10:05:00Z'
      )
    })

    it('properly escapes values with commas, quotes, and newlines according to RFC 4180', () => {
      const mockRecord: RefundRecord = {
        refundId: 'ref_456',
        orderId: 'ORD-1002',
        status: 'escalated',
        decision: 'escalate',
        category: 'wrong_item',
        confidenceScore: 0.5,
        customerRequestText: 'Received "red" boots, not blue.\nPackage was also crushed.',
        reasoning: 'Needs manual review, ambiguous policy rule.\r\nEscalated to supervisor.',
        overrideDecision: 'approve',
        overrideReason: 'Approved because customer provided valid "photo, invoice", and proof.',
        createdAt: '2026-10-02T12:00:00Z',
        updatedAt: '2026-10-02T12:10:00Z',
      }

      const csv = serializeToCsv([mockRecord])
      const lines = csv.split('\r\n')

      // Customer request should wrap in quotes and escape internal quotes
      expect(csv).toContain('"Received ""red"" boots, not blue.\nPackage was also crushed."')
      // Reasoning with CRLF should wrap in quotes
      expect(csv).toContain('"Needs manual review, ambiguous policy rule.\r\nEscalated to supervisor."')
      // Override reason with comma and quotes
      expect(csv).toContain('"Approved because customer provided valid ""photo, invoice"", and proof."')
    })

    it('safely handles null, undefined, and missing properties without throwing exceptions', () => {
      const minimalRecord = {
        refundId: 'ref_789',
        orderId: 'ORD-1003',
        status: 'pending' as const,
      } as unknown as RefundRecord

      expect(() => serializeToCsv([minimalRecord])).not.toThrow()

      const csv = serializeToCsv([minimalRecord])
      const lines = csv.split('\r\n').filter(Boolean)
      expect(lines).toHaveLength(2)
      expect(lines[1]).toBe('ref_789,ORD-1003,pending,,,,,,,,,,')
    })

    it('handles snake_case fallback properties correctly', () => {
      const snakeCaseRecord = {
        refund_id: 'ref_snake',
        order_id: 'ORD-9999',
        status: 'pending',
        decision: 'deny',
        category: 'unauthorized',
        refund_amount: 120.5,
        confidence_score: 0.88,
        customer_request_text: 'Did not buy this',
        reasoning: 'Past window',
        override_decision: 'deny',
        override_reason: 'Denied by supervisor',
        created_at: '2026-10-03T01:00:00Z',
        updated_at: '2026-10-03T02:00:00Z',
      } as unknown as RefundRecord

      const csv = serializeToCsv([snakeCaseRecord])
      const lines = csv.split('\r\n').filter(Boolean)
      expect(lines[1]).toBe(
        'ref_snake,ORD-9999,pending,deny,unauthorized,120.5,0.88,Did not buy this,Past window,deny,Denied by supervisor,2026-10-03T01:00:00Z,2026-10-03T02:00:00Z'
      )
    })
  })

  describe('serializeToJson', () => {
    it('returns empty array string when given empty records', () => {
      expect(serializeToJson([])).toBe('[]')
    })

    it('returns formatted JSON with 2-space indentation', () => {
      const records: RefundRecord[] = [
        {
          refundId: 'ref_1',
          orderId: 'ORD-1',
          status: 'pending',
          customerRequestText: 'Need refund',
          createdAt: '2026-10-01T00:00:00Z',
          updatedAt: '2026-10-01T00:00:00Z',
        },
      ]

      const json = serializeToJson(records)
      expect(json).toBe(JSON.stringify(records, null, 2))
      expect(JSON.parse(json)).toEqual(records)
      expect(json).toContain('  "refundId": "ref_1"')
    })
  })

  describe('generateExportFilename', () => {
    const fixedDate = new Date(2026, 9, 3, 14, 30, 0) // 2026-10-03 14:30:00

    it('generates CSV filename with all status by default', () => {
      const filename = generateExportFilename('csv', undefined, fixedDate)
      expect(filename).toBe('refunds-all-20261003-143000.csv')
    })

    it('generates JSON filename with all status when empty string provided', () => {
      const filename = generateExportFilename('json', '', fixedDate)
      expect(filename).toBe('refunds-all-20261003-143000.json')
    })

    it('generates filename reflecting specific status tab filter', () => {
      const csvPending = generateExportFilename('csv', 'pending', fixedDate)
      expect(csvPending).toBe('refunds-pending-20261003-143000.csv')

      const jsonEscalated = generateExportFilename('json', 'escalated', fixedDate)
      expect(jsonEscalated).toBe('refunds-escalated-20261003-143000.json')

      const csvClarification = generateExportFilename('csv', 'awaiting_clarification', fixedDate)
      expect(csvClarification).toBe('refunds-awaiting_clarification-20261003-143000.csv')
    })

    it('handles uppercase format or status gracefully', () => {
      const filename = generateExportFilename('CSV' as 'csv', 'PENDING', fixedDate)
      expect(filename).toBe('refunds-pending-20261003-143000.csv')
    })
  })

  describe('downloadExportFile', () => {
    let mockCreateObjectURL: ReturnType<typeof vi.fn>
    let mockRevokeObjectURL: ReturnType<typeof vi.fn>

    beforeEach(() => {
      mockCreateObjectURL = vi.fn().mockReturnValue('blob:http://localhost/mock-uuid')
      mockRevokeObjectURL = vi.fn()
      window.URL.createObjectURL = mockCreateObjectURL
      window.URL.revokeObjectURL = mockRevokeObjectURL
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('creates Blob, sets link attributes, clicks link, and revokes Object URL', () => {
      const appendChildSpy = vi.spyOn(document.body, 'appendChild')
      const removeChildSpy = vi.spyOn(document.body, 'removeChild')
      const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

      downloadExportFile('test,content', 'test-export.csv', 'text/csv; charset=utf-8')

      expect(mockCreateObjectURL).toHaveBeenCalledTimes(1)
      const blobArg = mockCreateObjectURL.mock.calls[0][0]
      expect(blobArg).toBeInstanceOf(Blob)
      expect(blobArg.type).toBe('text/csv; charset=utf-8')

      expect(appendChildSpy).toHaveBeenCalled()
      expect(clickSpy).toHaveBeenCalledTimes(1)
      expect(removeChildSpy).toHaveBeenCalled()
      expect(mockRevokeObjectURL).toHaveBeenCalledWith('blob:http://localhost/mock-uuid')

      appendChildSpy.mockRestore()
      removeChildSpy.mockRestore()
      clickSpy.mockRestore()
    })
  })
})
