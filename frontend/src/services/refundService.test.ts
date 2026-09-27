import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  listRefunds,
  submitRefund,
  getRefundById,
  overrideRefundDecision,
  submitClarification,
  uploadEvidence,
  requestReviewerProof,
  refundService,
} from './refundService'
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

  const baseRecord: RefundRecord = {
    refundId: 'ref_123',
    orderId: 'ORD-1001',
    customerRequestText: 'Item damaged',
    status: 'pending',
    createdAt: '2026-09-28T00:00:00Z',
    updatedAt: '2026-09-28T00:00:00Z',
  }

  describe('listRefunds', () => {
    it('queries /v1/refunds without query parameters when none provided', async () => {
      const mockRecords: RefundRecord[] = [baseRecord]
      vi.mocked(apiClient.get).mockResolvedValueOnce(mockRecords)

      const result = await listRefunds()

      expect(apiClient.get).toHaveBeenCalledWith('/v1/refunds')
      expect(result).toEqual(mockRecords)
    })

    it('queries /v1/refunds with formatted status and limit query parameters', async () => {
      const mockRecords: RefundRecord[] = [{ ...baseRecord, status: 'awaiting_clarification' }]
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

  describe('getRefundById', () => {
    it('queries /v1/refunds/{refundId} with encoded URL and returns matching RefundRecord', async () => {
      const mockRecord: RefundRecord = {
        ...baseRecord,
        refundId: 'ref_special#1',
        status: 'completed',
        decision: 'auto_approve',
      }
      vi.mocked(apiClient.get).mockResolvedValueOnce(mockRecord)

      const result = await getRefundById('ref_special#1')

      expect(apiClient.get).toHaveBeenCalledWith('/v1/refunds/ref_special%231')
      expect(result).toEqual(mockRecord)
    })

    it('throws ApiError on HTTP 404 when refund ID does not exist', async () => {
      const notFoundError = new ApiError({
        type: 'urn:problem:404',
        title: 'Not Found',
        status: 404,
        detail: "Refund request 'ref_nonexistent' not found.",
      } as any)
      vi.mocked(apiClient.get).mockRejectedValueOnce(notFoundError)

      await expect(getRefundById('ref_nonexistent')).rejects.toThrow(ApiError)
    })
  })

  describe('overrideRefundDecision', () => {
    it('posts override payload to /v1/refunds/{refundId}/override and returns completed record', async () => {
      const mockRecord: RefundRecord = {
        ...baseRecord,
        status: 'completed',
        decision: 'approve',
        overrideDecision: 'approve',
        overrideReason: 'VIP courtesy approval',
      }
      vi.mocked(apiClient.post).mockResolvedValueOnce(mockRecord)

      const result = await overrideRefundDecision('ref_123', {
        overrideDecision: 'approve',
        overrideReason: 'VIP courtesy approval',
      })

      expect(apiClient.post).toHaveBeenCalledWith('/v1/refunds/ref_123/override', {
        override_decision: 'approve',
        override_reason: 'VIP courtesy approval',
      })
      expect(result).toEqual(mockRecord)
    })

    it('propagates ApiError on HTTP 400 when refund is not escalated', async () => {
      const badRequestError = new ApiError({
        type: 'urn:problem:400',
        title: 'Bad Request',
        status: 400,
        detail: "Refund request 'ref_123' is not in escalated status.",
      } as any)
      vi.mocked(apiClient.post).mockRejectedValueOnce(badRequestError)

      await expect(
        overrideRefundDecision('ref_123', {
          overrideDecision: 'deny',
          overrideReason: 'Fraud suspected',
        }),
      ).rejects.toThrow(ApiError)
    })
  })

  describe('submitClarification', () => {
    it('dispatches JSON without file and returns pending resumed record', async () => {
      const mockRecord: RefundRecord = {
        ...baseRecord,
        status: 'pending',
        clarificationResponse: 'Here are details',
      }
      vi.mocked(apiClient.post).mockResolvedValueOnce(mockRecord)

      const result = await submitClarification('ref_123', {
        responseText: 'Here are details',
      })

      expect(apiClient.post).toHaveBeenCalledWith('/v1/refunds/ref_123/clarify', {
        response_text: 'Here are details',
      })
      expect(apiClient.postMultipart).not.toHaveBeenCalled()
      expect(result).toEqual(mockRecord)
    })

    it('dispatches multipart FormData when file is provided and returns pending resumed record', async () => {
      const mockFile = new File(['proof'], 'label.png', { type: 'image/png' })
      const mockRecord: RefundRecord = {
        ...baseRecord,
        status: 'pending',
        clarificationResponse: 'Attached image',
      }
      vi.mocked(apiClient.postMultipart).mockResolvedValueOnce(mockRecord)

      const result = await submitClarification('ref_123', {
        responseText: 'Attached image',
        evidenceFile: mockFile,
      })

      expect(apiClient.postMultipart).toHaveBeenCalledWith(
        '/v1/refunds/ref_123/clarify',
        expect.any(FormData),
      )
      const calledFormData = vi.mocked(apiClient.postMultipart).mock.calls[0][1] as FormData
      expect(calledFormData.get('response_text')).toBe('Attached image')
      expect(calledFormData.get('evidence_file')).toBe(mockFile)
      expect(result).toEqual(mockRecord)
    })
  })

  describe('uploadEvidence', () => {
    it('dispatches multipart FormData to /v1/refunds/{refundId}/evidence and returns updated record', async () => {
      const mockFile = new File(['evidence'], 'box.jpg', { type: 'image/jpeg' })
      const mockRecord: RefundRecord = {
        ...baseRecord,
        evidence: [
          {
            evidenceId: 'evi_1',
            storageKey: 'evidence/ref_123/box.jpg',
            filename: 'box.jpg',
            contentType: 'image/jpeg',
            sizeBytes: 1024,
            url: '/uploads/box.jpg',
            createdAt: '2026-09-28T00:00:00Z',
          },
        ],
      }
      vi.mocked(apiClient.postMultipart).mockResolvedValueOnce(mockRecord)

      const result = await uploadEvidence('ref_123', mockFile)

      expect(apiClient.postMultipart).toHaveBeenCalledWith(
        '/v1/refunds/ref_123/evidence',
        expect.any(FormData),
      )
      const calledFormData = vi.mocked(apiClient.postMultipart).mock.calls[0][1] as FormData
      expect(calledFormData.get('file')).toBe(mockFile)
      expect(result).toEqual(mockRecord)
    })

    it('propagates ApiError on HTTP 413 when file exceeds 5MB limit', async () => {
      const oversizedError = new ApiError({
        type: 'urn:problem:413',
        title: 'Payload Too Large',
        status: 413,
        detail: 'Evidence file exceeds 5MB limit',
      } as any)
      vi.mocked(apiClient.postMultipart).mockRejectedValueOnce(oversizedError)

      const bigFile = new File(['big'], 'huge.png', { type: 'image/png' })
      await expect(uploadEvidence('ref_123', bigFile)).rejects.toThrow(ApiError)
    })

    it('propagates ApiError on HTTP 400 for disallowed MIME type', async () => {
      const badMimeError = new ApiError({
        type: 'urn:problem:400',
        title: 'Bad Request',
        status: 400,
        detail: 'Disallowed file type. Only JPEG, PNG, and WebP images are accepted.',
      } as any)
      vi.mocked(apiClient.postMultipart).mockRejectedValueOnce(badMimeError)

      const videoFile = new File(['video'], 'movie.mp4', { type: 'video/mp4' })
      await expect(uploadEvidence('ref_123', videoFile)).rejects.toThrow(ApiError)
    })
  })

  describe('requestReviewerProof', () => {
    it('posts proof prompt to /v1/refunds/{refundId}/request-proof with customer_name when provided', async () => {
      const mockRecord: RefundRecord = {
        ...baseRecord,
        status: 'awaiting_clarification',
        clarificationPrompt: 'Please upload serial number label',
        clarificationEmailText: 'Dear John Doe...',
      }
      vi.mocked(apiClient.post).mockResolvedValueOnce(mockRecord)

      const result = await requestReviewerProof('ref_123', {
        proofPrompt: 'Please upload serial number label',
        customerName: 'John Doe',
      })

      expect(apiClient.post).toHaveBeenCalledWith('/v1/refunds/ref_123/request-proof', {
        proof_prompt: 'Please upload serial number label',
        customer_name: 'John Doe',
      })
      expect(result).toEqual(mockRecord)
    })

    it('posts proof prompt to /v1/refunds/{refundId}/request-proof omitting customer_name when null/undefined', async () => {
      const mockRecord: RefundRecord = {
        ...baseRecord,
        status: 'awaiting_clarification',
        clarificationPrompt: 'Please upload serial number label',
      }
      vi.mocked(apiClient.post).mockResolvedValueOnce(mockRecord)

      const result = await requestReviewerProof('ref_123', {
        proofPrompt: 'Please upload serial number label',
      })

      expect(apiClient.post).toHaveBeenCalledWith('/v1/refunds/ref_123/request-proof', {
        proof_prompt: 'Please upload serial number label',
      })
      expect(result).toEqual(mockRecord)
    })
  })

  describe('refundService object export', () => {
    it('exposes all refund methods on unified refundService object', () => {
      expect(refundService.listRefunds).toBe(listRefunds)
      expect(refundService.submitRefund).toBe(submitRefund)
      expect(refundService.getRefundById).toBe(getRefundById)
      expect(refundService.overrideRefundDecision).toBe(overrideRefundDecision)
      expect(refundService.submitClarification).toBe(submitClarification)
      expect(refundService.uploadEvidence).toBe(uploadEvidence)
      expect(refundService.requestReviewerProof).toBe(requestReviewerProof)
    })
  })
})
