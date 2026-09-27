import { describe, it, expect, vi, beforeEach } from 'vitest'
import { listRefunds, submitRefund, refundService } from './refundService'
import { apiClient, ApiError } from './apiClient'
import type { RefundRecord, RefundCreateResponse } from '../types/api'

vi.mock('./apiClient', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    postMultipart: vi.fn(),
    delete: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    readonly status: number
    readonly problem: unknown
    constructor(problem: { status: number; detail?: string; title?: string }) {
      super(problem.detail || problem.title)
      this.name = 'ApiError'
      this.status = problem.status
      this.problem = problem
    }
  },
}))

describe('refundService', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('listRefunds', () => {
    it('queries /v1/refunds without query parameters when none provided', async () => {
      const mockRecords: RefundRecord[] = [
        {
          refundId: 'ref_1',
          orderId: 'ORD-1001',
          customerRequestText: 'Damaged item',
          status: 'completed',
          decision: 'auto_approve',
          createdAt: '2026-09-28T00:00:00Z',
          updatedAt: '2026-09-28T00:01:00Z',
        },
      ]
      vi.mocked(apiClient.get).mockResolvedValueOnce(mockRecords)

      const result = await listRefunds()

      expect(apiClient.get).toHaveBeenCalledWith('/v1/refunds')
      expect(result).toEqual(mockRecords)
    })

    it('queries /v1/refunds with formatted status and limit query parameters', async () => {
      const mockRecords: RefundRecord[] = [
        {
          refundId: 'ref_2',
          orderId: 'ORD-1002',
          customerRequestText: 'Vague request',
          status: 'awaiting_clarification',
          decision: null,
          createdAt: '2026-09-28T00:00:00Z',
          updatedAt: '2026-09-28T00:01:00Z',
        },
      ]
      vi.mocked(apiClient.get).mockResolvedValueOnce(mockRecords)

      const result = await listRefunds({ status: 'awaiting_clarification', limit: 10 })

      expect(apiClient.get).toHaveBeenCalledWith('/v1/refunds?status=awaiting_clarification&limit=10')
      expect(result).toEqual(mockRecords)
    })

    it('returns empty array when server returns empty array or null', async () => {
      vi.mocked(apiClient.get).mockResolvedValueOnce([])
      const result = await listRefunds()
      expect(result).toEqual([])

      vi.mocked(apiClient.get).mockResolvedValueOnce(null as unknown as RefundRecord[])
      const nullResult = await listRefunds()
      expect(nullResult).toEqual([])
    })
  })

  describe('submitRefund', () => {
    it('submits JSON payload without file and returns RefundCreateResponse', async () => {
      const mockResponse: RefundCreateResponse = {
        refundId: 'ref_new123',
        orderId: 'ORD-1001',
        status: 'pending',
        createdAt: '2026-09-28T00:00:00Z',
      }
      vi.mocked(apiClient.post).mockResolvedValueOnce(mockResponse)

      const result = await submitRefund({
        orderId: 'ORD-1001',
        customerRequestText: 'Monitor arrived cracked.',
      })

      expect(apiClient.post).toHaveBeenCalledWith('/v1/refunds', {
        order_id: 'ORD-1001',
        customer_request_text: 'Monitor arrived cracked.',
      })
      expect(apiClient.postMultipart).not.toHaveBeenCalled()
      expect(result).toEqual(mockResponse)
    })

    it('submits FormData payload when file is provided and returns RefundCreateResponse', async () => {
      const mockFile = new File(['mock content'], 'damage.jpg', { type: 'image/jpeg' })
      const mockResponse: RefundCreateResponse = {
        refundId: 'ref_new456',
        orderId: 'ORD-1002',
        status: 'pending',
        createdAt: '2026-09-28T00:00:00Z',
      }
      vi.mocked(apiClient.postMultipart).mockResolvedValueOnce(mockResponse)

      const result = await submitRefund({
        orderId: 'ORD-1002',
        customerRequestText: 'Attached damage photo.',
        file: mockFile,
      })

      expect(apiClient.postMultipart).toHaveBeenCalledWith('/v1/refunds', expect.any(FormData))
      const calledFormData = vi.mocked(apiClient.postMultipart).mock.calls[0][1] as FormData
      expect(calledFormData.get('order_id')).toBe('ORD-1002')
      expect(calledFormData.get('customer_request_text')).toBe('Attached damage photo.')
      expect(calledFormData.get('file')).toBe(mockFile)
      expect(apiClient.post).not.toHaveBeenCalled()
      expect(result).toEqual(mockResponse)
    })

    it('propagates ApiError on HTTP 422 validation failure without swallowing details', async () => {
      const validationError = new ApiError({
        type: 'urn:problem:validation-error',
        title: 'Validation Error',
        status: 422,
        detail: 'One or more fields failed validation.',
      } as any)
      ;(validationError as any).problem = {
        type: 'urn:problem:validation-error',
        title: 'Validation Error',
        status: 422,
        detail: 'One or more fields failed validation.',
        invalidParams: [{ name: 'orderId', reason: 'Field cannot be blank or empty.' }],
      }
      vi.mocked(apiClient.post).mockRejectedValueOnce(validationError)

      await expect(
        submitRefund({ orderId: '', customerRequestText: 'Item missing' }),
      ).rejects.toThrow(ApiError)
    })

    it('propagates ApiError on HTTP 413 file too large', async () => {
      const payloadTooLargeError = new ApiError({
        type: 'urn:problem:413',
        title: 'Payload Too Large',
        status: 413,
        detail: 'Uploaded evidence file size exceeds 5MB limit.',
      } as any)
      vi.mocked(apiClient.postMultipart).mockRejectedValueOnce(payloadTooLargeError)

      const oversizedFile = new File(['oversized'], 'huge.jpg', { type: 'image/jpeg' })
      await expect(
        submitRefund({
          orderId: 'ORD-1003',
          customerRequestText: 'Large photo attached',
          file: oversizedFile,
        }),
      ).rejects.toThrow(ApiError)
    })
  })

  describe('refundService object export', () => {
    it('exposes listRefunds and submitRefund methods', () => {
      expect(refundService.listRefunds).toBe(listRefunds)
      expect(refundService.submitRefund).toBe(submitRefund)
    })
  })
})
