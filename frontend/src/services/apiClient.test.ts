import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  apiClient,
  ApiError,
  isApiError,
  isValidationProblem,
  buildUrl,
} from './apiClient'

describe('apiClient', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  describe('buildUrl', () => {
    it('constructs absolute URL handling leading and trailing slashes', () => {
      expect(buildUrl('/v1/refunds')).toBe('http://localhost:8000/v1/refunds')
      expect(buildUrl('v1/refunds')).toBe('http://localhost:8000/v1/refunds')
      expect(buildUrl('/v1/refunds/ref_123')).toBe('http://localhost:8000/v1/refunds/ref_123')
    })
  })

  describe('successful requests', () => {
    it('executes successful GET request and returns parsed JSON', async () => {
      const mockData = [{ refundId: 'ref_1', orderId: 'ORD-1001', status: 'completed' }]
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockData,
      })

      const result = await apiClient.get<typeof mockData>('/v1/refunds')

      expect(result).toEqual(mockData)
      expect(globalThis.fetch).toHaveBeenCalledWith(
        'http://localhost:8000/v1/refunds',
        expect.objectContaining({
          method: 'GET',
          headers: expect.any(Headers),
        }),
      )

      const calledHeaders = (globalThis.fetch as unknown as { mock: { calls: Array<[string, RequestInit]> } }).mock.calls[0][1].headers as Headers
      expect(calledHeaders.get('Accept')).toBe('application/json, application/problem+json')
    })

    it('executes successful POST JSON request and serializes payload', async () => {
      const payload = { orderId: 'ORD-1002', customerRequestText: 'Item missing' }
      const mockResponse = { refundId: 'ref_2', orderId: 'ORD-1002', status: 'pending' }

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 201,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockResponse,
      })

      const result = await apiClient.post<typeof mockResponse>('/v1/refunds', payload)

      expect(result).toEqual(mockResponse)
      expect(globalThis.fetch).toHaveBeenCalledWith(
        'http://localhost:8000/v1/refunds',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify(payload),
        }),
      )

      const calledHeaders = (globalThis.fetch as unknown as { mock: { calls: Array<[string, RequestInit]> } }).mock.calls[0][1].headers as Headers
      expect(calledHeaders.get('Content-Type')).toBe('application/json')
      expect(calledHeaders.get('Accept')).toBe('application/json, application/problem+json')
    })

    it('executes multipart POST with FormData without setting explicit Content-Type', async () => {
      const formData = new FormData()
      formData.append('orderId', 'ORD-1003')
      formData.append('file', new Blob(['test-image'], { type: 'image/jpeg' }), 'box.jpg')

      const mockResponse = { refundId: 'ref_3', orderId: 'ORD-1003', status: 'pending' }

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 202,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockResponse,
      })

      const result = await apiClient.postMultipart<typeof mockResponse>('/v1/refunds', formData)

      expect(result).toEqual(mockResponse)
      expect(globalThis.fetch).toHaveBeenCalledWith(
        'http://localhost:8000/v1/refunds',
        expect.objectContaining({
          method: 'POST',
          body: formData,
        }),
      )

      const calledHeaders = (globalThis.fetch as unknown as { mock: { calls: Array<[string, RequestInit]> } }).mock.calls[0][1].headers as Headers
      expect(calledHeaders.has('Content-Type')).toBe(false)
      expect(calledHeaders.get('Accept')).toBe('application/json, application/problem+json')
    })
  })

  describe('RFC 9457 error handling', () => {
    it('throws ApiError with accurate ProblemDetails when receiving application/problem+json (HTTP 400)', async () => {
      const problemPayload = {
        type: 'urn:problem:bad-request',
        title: 'Bad Request',
        status: 400,
        detail: 'Query parameter limit must be greater than 0',
        instance: '/v1/refunds',
      }

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        statusText: 'Bad Request',
        headers: new Headers({ 'content-type': 'application/problem+json' }),
        json: async () => problemPayload,
      })

      await expect(apiClient.get('/v1/refunds')).rejects.toThrow(ApiError)

      try {
        await apiClient.get('/v1/refunds')
      } catch (err) {
        expect(isApiError(err)).toBe(true)
        if (isApiError(err)) {
          expect(err.status).toBe(400)
          expect(err.problem.type).toBe('urn:problem:bad-request')
          expect(err.problem.title).toBe('Bad Request')
          expect(err.problem.detail).toBe('Query parameter limit must be greater than 0')
          expect(err.problem.instance).toBe('/v1/refunds')
          expect(isValidationProblem(err)).toBe(false)
        }
      }
    })

    it('normalizes FastAPI string detail response into ProblemDetails (HTTP 404)', async () => {
      const fastApiPayload = {
        detail: "Refund request 'ref_missing' not found.",
      }

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: 'Not Found',
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => fastApiPayload,
      })

      try {
        await apiClient.get('/v1/refunds/ref_missing')
      } catch (err) {
        expect(isApiError(err)).toBe(true)
        if (isApiError(err)) {
          expect(err.status).toBe(404)
          expect(err.problem.type).toBe('urn:problem:404')
          expect(err.problem.title).toBe('Not Found')
          expect(err.problem.detail).toBe("Refund request 'ref_missing' not found.")
          expect(err.problem.instance).toBe('/v1/refunds/ref_missing')
        }
      }
    })

    it('normalizes HTTP 422 validation errors into ValidationProblemDetails with invalidParams', async () => {
      const validationPayload = {
        detail: [
          {
            loc: ['body', 'orderId'],
            msg: 'Field cannot be blank or empty.',
            type: 'value_error',
          },
          {
            loc: ['body', 'customerRequestText'],
            msg: 'String should have at least 1 characters',
            type: 'string_too_short',
          },
        ],
      }

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        statusText: 'Unprocessable Entity',
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => validationPayload,
      })

      try {
        await apiClient.post('/v1/refunds', { orderId: '' })
      } catch (err) {
        expect(isApiError(err)).toBe(true)
        expect(isValidationProblem(err)).toBe(true)
        if (isValidationProblem(err)) {
          expect(err.status).toBe(422)
          expect(err.problem.type).toBe('urn:problem:validation-error')
          expect(err.problem.title).toBe('Validation Error')
          expect(err.problem.invalidParams).toHaveLength(2)
          expect(err.problem.invalidParams[0]).toEqual({
            name: 'orderId',
            reason: 'Field cannot be blank or empty.',
          })
          expect(err.problem.invalidParams[1]).toEqual({
            name: 'customerRequestText',
            reason: 'String should have at least 1 characters',
          })
        }
      }
    })

    it('handles network connection failure by throwing ApiError with status 0 and synthetic ProblemDetails', async () => {
      globalThis.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch (Connection refused)'))

      try {
        await apiClient.get('/v1/refunds')
      } catch (err) {
        expect(isApiError(err)).toBe(true)
        if (isApiError(err)) {
          expect(err.status).toBe(0)
          expect(err.problem.type).toBe('urn:problem:network-error')
          expect(err.problem.title).toBe('Network Error')
          expect(err.problem.detail).toContain('Failed to fetch')
          expect(err.problem.instance).toBe('/v1/refunds')
        }
      }
    })
  })
})
