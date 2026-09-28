import { http, HttpResponse } from 'msw'
import type {
  RefundRecord,
  RefundCreateResponse,
  ProblemDetails,
} from '@/types/api'

export const INITIAL_MOCK_REFUNDS: RefundRecord[] = [
  {
    refundId: 'ref-101',
    orderId: 'ORD-1001',
    customerRequestText: 'The ceramic vase arrived shattered inside shipping box with no padding.',
    status: 'completed',
    decision: 'auto_approve',
    confidenceScore: 0.96,
    category: 'damaged',
    reasoning: 'Category damaged meets standard 30-day window policy. Auto-approved.',
    orderAmount: 85.5,
    currency: 'USD',
    customerEmail: 'customer1@example.com',
    matchedPolicyRule: {
      policyName: 'standard_30_day_damaged',
      action: 'auto_approve',
      returnRequired: false,
    },
    approvalEmailText: 'Dear Customer, your refund request of $85.50 has been approved.',
    denialEmailText: null,
    clarificationEmailText: null,
    clarificationPrompt: null,
    clarificationResponse: null,
    clarificationCount: 0,
    clarificationHistory: [],
    evidence: [],
    toolCalls: [],
    overrideDecision: null,
    overrideReason: null,
    overriddenAt: null,
    createdAt: '2026-09-28T10:00:00Z',
    updatedAt: '2026-09-28T10:01:00Z',
  } as unknown as RefundRecord,
  {
    refundId: 'ref-102',
    orderId: 'ORD-1002',
    customerRequestText: 'Received size 8 shoes instead of size 10 ordered.',
    status: 'escalated',
    decision: 'escalate',
    confidenceScore: 0.88,
    category: 'wrong_item',
    reasoning: 'High-value footwear exchange requires supervisor verification.',
    orderAmount: 149.99,
    currency: 'USD',
    customerEmail: 'customer2@example.com',
    matchedPolicyRule: {
      policyName: 'wrong_item_exchange_policy',
      action: 'manual_review',
      returnRequired: true,
    },
    approvalEmailText: null,
    denialEmailText: null,
    clarificationEmailText: null,
    clarificationPrompt: null,
    clarificationResponse: null,
    clarificationCount: 0,
    clarificationHistory: [],
    evidence: [],
    toolCalls: [],
    overrideDecision: null,
    overrideReason: null,
    overriddenAt: null,
    createdAt: '2026-09-28T09:30:00Z',
    updatedAt: '2026-09-28T09:32:00Z',
  } as unknown as RefundRecord,
  {
    refundId: 'ref-103',
    orderId: 'ORD-1003',
    customerRequestText: 'Ordered 3-pack t-shirts, only received 1 shirt in packaging.',
    status: 'awaiting_clarification',
    decision: 'escalate',
    confidenceScore: 0.65,
    category: 'missing_items',
    reasoning: 'Customer asked to supply photo of packaging and packing slip.',
    orderAmount: 39.99,
    currency: 'USD',
    customerEmail: 'customer3@example.com',
    matchedPolicyRule: {
      policyName: 'partial_missing_items_policy',
      action: 'request_proof',
      returnRequired: false,
    },
    approvalEmailText: null,
    denialEmailText: null,
    clarificationEmailText: null,
    clarificationPrompt: 'Please upload a photo of the exterior shipping box and packing slip.',
    clarificationResponse: null,
    clarificationCount: 1,
    clarificationHistory: [
      {
        cycle: 1,
        prompt: 'Please upload a photo of the exterior shipping box and packing slip.',
        response: null,
        timestamp: '2026-09-28T09:05:00Z',
        evidenceIds: ['evi-101'],
      },
    ],
    evidence: [
      {
        evidenceId: 'evi-101',
        filename: 'shipping_bag.jpg',
        contentType: 'image/jpeg',
        sizeBytes: 254100,
        url: 'https://example.com/uploads/shipping_bag.jpg',
        createdAt: '2026-09-28T09:05:00Z',
      },
    ],
    toolCalls: [
      {
        toolName: 'query_carrier_tracking',
        inputArgs: { trackingNumber: '1Z9999999999999999' },
        rawOutput: { status: 'Delivered', deliveredAt: '2026-09-27' },
        durationSeconds: 0.42,
        executedAt: '2026-09-28T09:01:00Z',
      },
      {
        toolName: 'query_payment_transaction',
        inputArgs: { orderId: 'ORD-1003' },
        rawOutput: { status: 'Authorized', amount: 39.99 },
        durationSeconds: 0.28,
        executedAt: '2026-09-28T09:01:30Z',
      },
    ],
    overrideDecision: null,
    overrideReason: null,
    overriddenAt: null,
    createdAt: '2026-09-28T09:00:00Z',
    updatedAt: '2026-09-28T09:05:00Z',
  } as unknown as RefundRecord,
  {
    refundId: 'ref-104',
    orderId: 'ORD-1004',
    customerRequestText: 'Package is still marked in transit 2 weeks after estimated delivery.',
    status: 'pending',
    decision: null,
    confidenceScore: null,
    category: 'late_delivery',
    reasoning: null,
    orderAmount: 49.0,
    currency: 'USD',
    customerEmail: 'customer4@example.com',
    matchedPolicyRule: null,
    approvalEmailText: null,
    denialEmailText: null,
    clarificationEmailText: null,
    clarificationPrompt: null,
    clarificationResponse: null,
    clarificationCount: 0,
    clarificationHistory: [],
    evidence: [],
    toolCalls: [],
    overrideDecision: null,
    overrideReason: null,
    overriddenAt: null,
    createdAt: '2026-09-28T10:10:00Z',
    updatedAt: '2026-09-28T10:10:00Z',
  } as unknown as RefundRecord,
  {
    refundId: 'ref-105',
    orderId: 'ORD-1005',
    customerRequestText: 'Did not like the fabric texture, purchased 60 days ago.',
    status: 'completed',
    decision: 'deny',
    confidenceScore: 0.94,
    category: 'buyer_remorse',
    reasoning: 'Return window expired 30 days after delivery. Denied per policy.',
    orderAmount: 64.0,
    currency: 'USD',
    customerEmail: 'customer5@example.com',
    matchedPolicyRule: {
      policyName: 'buyer_remorse_return_window',
      action: 'deny',
      returnRequired: false,
    },
    approvalEmailText: null,
    denialEmailText: 'Your refund request has been denied because the return window expired.',
    clarificationEmailText: null,
    clarificationPrompt: null,
    clarificationResponse: null,
    clarificationCount: 0,
    clarificationHistory: [],
    evidence: [],
    toolCalls: [],
    overrideDecision: null,
    overrideReason: null,
    overriddenAt: null,
    createdAt: '2026-09-28T08:00:00Z',
    updatedAt: '2026-09-28T08:02:00Z',
  } as unknown as RefundRecord,
]

// Mutable in-memory store for MSW
export let mockRefunds: RefundRecord[] = JSON.parse(JSON.stringify(INITIAL_MOCK_REFUNDS))

export function resetMockRefunds() {
  mockRefunds = JSON.parse(JSON.stringify(INITIAL_MOCK_REFUNDS))
}

export const handlers = [
  // GET /v1/refunds (list with optional status filter)
  http.get('*/v1/refunds', ({ request }) => {
    const url = new URL(request.url)
    const statusFilter = url.searchParams.get('status')
    const limit = url.searchParams.get('limit')

    let results = [...mockRefunds]
    if (statusFilter) {
      results = results.filter((r) => r.status === statusFilter)
    }
    if (limit) {
      const num = parseInt(limit, 10)
      if (!isNaN(num) && num > 0) {
        results = results.slice(0, num)
      }
    }

    return HttpResponse.json(results)
  }),

  // POST /v1/refunds (submit refund - JSON or FormData)
  http.post('*/v1/refunds', async ({ request }) => {
    try {
      const contentType = request.headers.get('content-type') || ''
      let orderId = ''
      let customerRequestText = ''
      let hasFile = false

      if (contentType.includes('multipart/form-data')) {
        try {
          const formData = await request.formData()
          orderId = String(formData.get('order_id') || formData.get('orderId') || '')
          customerRequestText = String(
            formData.get('customer_request_text') || formData.get('customerRequestText') || ''
          )
          hasFile = Boolean(formData.get('file'))
        } catch {
          // Fallback if formData extraction is unsupported in environment
        }
      } else {
        try {
          const body = (await request.json()) as Record<string, unknown>
          orderId = String(body.order_id || body.orderId || '')
          customerRequestText = String(body.customer_request_text || body.customerRequestText || '')
        } catch {
          // Fallback if body JSON is malformed
        }
      }

      if (!orderId || !customerRequestText) {
        const error: ProblemDetails = {
          type: 'https://api.refund-processor.local/problems/validation',
          title: 'Validation Error',
          status: 422,
          detail: 'orderId and customerRequestText are required.',
        }
        return HttpResponse.json(error, { status: 422 })
      }

      const newRefundId = `ref_${Date.now()}`
      const now = new Date().toISOString()

      const newRecord: RefundRecord = {
        refundId: newRefundId,
        orderId,
        customerRequestText,
        status: 'pending',
        decision: null,
        confidenceScore: null,
        category: 'General',
        reasoning: 'Evaluation queued',
        orderAmount: 99.0,
        currency: 'USD',
        matchedPolicyRule: null,
        approvalEmailText: null,
        denialEmailText: null,
        clarificationEmailText: null,
        clarificationPrompt: null,
        clarificationResponse: null,
        clarificationCount: 0,
        clarificationHistory: [],
        evidence: hasFile
          ? [
              {
                evidenceId: `evi_${Date.now()}`,
                storageKey: 'evidence/initial_proof.png',
                filename: 'initial_proof.png',
                contentType: 'image/png',
                sizeBytes: 512000,
                url: 'https://example.com/uploads/initial_proof.png',
                createdAt: now,
              },
            ]
          : [],
        toolCalls: [],
        overrideDecision: null,
        overrideReason: null,
        overriddenAt: null,
        createdAt: now,
        updatedAt: now,
      } as unknown as RefundRecord

      mockRefunds.unshift(newRecord)

      const response: RefundCreateResponse = {
        refundId: newRefundId,
        orderId,
        status: 'pending',
        createdAt: now,
      }

      return HttpResponse.json(response, { status: 202 })
    } catch (outerErr) {
      console.error('DEBUG outer error in POST /v1/refunds:', outerErr)
      return HttpResponse.json({ title: 'Internal Server Error', status: 500 }, { status: 500 })
    }
  }),

  // GET /v1/refunds/:refundId (single record detail)
  http.get('*/v1/refunds/:refundId', ({ params }) => {
    const { refundId } = params
    const record = mockRefunds.find((r) => r.refundId === refundId)

    if (!record) {
      const error: ProblemDetails = {
        type: 'https://api.refund-processor.local/problems/not-found',
        title: 'Refund Not Found',
        status: 404,
        detail: `No refund record found with identifier ${refundId}.`,
      }
      return HttpResponse.json(error, { status: 404 })
    }

    return HttpResponse.json(record)
  }),

  // POST /v1/refunds/:refundId/override (supervisor manual override)
  http.post('*/v1/refunds/:refundId/override', async ({ params, request }) => {
    const { refundId } = params
    const record = mockRefunds.find((r) => r.refundId === refundId)

    if (!record) {
      const error: ProblemDetails = {
        type: 'https://api.refund-processor.local/problems/not-found',
        title: 'Refund Not Found',
        status: 404,
        detail: `No refund record found with identifier ${refundId}.`,
      }
      return HttpResponse.json(error, { status: 404 })
    }

    const body = (await request.json()) as Record<string, unknown>
    const decision = (body.override_decision || body.overrideDecision) as 'approve' | 'deny'
    const reason = String(body.override_reason || body.overrideReason || '')

    record.status = 'completed'
    record.decision = decision
    record.overrideDecision = decision
    record.overrideReason = reason
    record.overriddenAt = new Date().toISOString()
    record.updatedAt = new Date().toISOString()

    return HttpResponse.json(record, { status: 200 })
  }),

  // POST /v1/refunds/:refundId/clarify (customer clarification submission)
  http.post('*/v1/refunds/:refundId/clarify', async ({ params, request }) => {
    const { refundId } = params
    const record = mockRefunds.find((r) => r.refundId === refundId)

    if (!record) {
      const error: ProblemDetails = {
        type: 'https://api.refund-processor.local/problems/not-found',
        title: 'Refund Not Found',
        status: 404,
        detail: `No refund record found with identifier ${refundId}.`,
      }
      return HttpResponse.json(error, { status: 404 })
    }

    const contentType = request.headers.get('content-type') || ''
    let responseText = ''

    if (contentType.includes('multipart/form-data')) {
      const formData = await request.formData()
      responseText = String(formData.get('response_text') || formData.get('responseText') || '')
    } else {
      const body = (await request.json()) as Record<string, unknown>
      responseText = String(body.response_text || body.responseText || '')
    }

    record.status = 'pending'
    record.clarificationResponse = responseText
    if (!record.clarificationHistory) record.clarificationHistory = []
    record.clarificationHistory.push({
      cycle: (record.clarificationCount || 0) + 1,
      prompt: record.clarificationPrompt || 'Evidence inquiry',
      response: responseText,
      timestamp: new Date().toISOString(),
      evidenceIds: [],
    })
    record.updatedAt = new Date().toISOString()

    return HttpResponse.json(record, { status: 200 })
  }),

  // POST /v1/refunds/:refundId/evidence (evidence upload)
  http.post('*/v1/refunds/:refundId/evidence', async ({ params, request }) => {
    const { refundId } = params
    const record = mockRefunds.find((r) => r.refundId === refundId)

    if (!record) {
      const error: ProblemDetails = {
        type: 'https://api.refund-processor.local/problems/not-found',
        title: 'Refund Not Found',
        status: 404,
        detail: `No refund record found with identifier ${refundId}.`,
      }
      return HttpResponse.json(error, { status: 404 })
    }

    const formData = await request.formData()
    const file = formData.get('file') as File | null
    const filename = file?.name || 'uploaded_proof.jpg'

    const newEvidence = {
      evidenceId: `evi_${Date.now()}`,
      storageKey: `evidence/${filename}`,
      filename,
      contentType: file?.type || 'image/jpeg',
      sizeBytes: file?.size || 102400,
      url: `https://example.com/uploads/${filename}`,
      createdAt: new Date().toISOString(),
    }

    if (!record.evidence) record.evidence = []
    record.evidence.push(newEvidence)
    record.updatedAt = new Date().toISOString()

    return HttpResponse.json(record, { status: 201 })
  }),

  // POST /v1/refunds/:refundId/request-proof (supervisor proof inquiry)
  http.post('*/v1/refunds/:refundId/request-proof', async ({ params, request }) => {
    const { refundId } = params
    const record = mockRefunds.find((r) => r.refundId === refundId)

    if (!record) {
      const error: ProblemDetails = {
        type: 'https://api.refund-processor.local/problems/not-found',
        title: 'Refund Not Found',
        status: 404,
        detail: `No refund record found with identifier ${refundId}.`,
      }
      return HttpResponse.json(error, { status: 404 })
    }

    const body = (await request.json()) as Record<string, unknown>
    const proofPrompt = String(body.proof_prompt || body.proofPrompt || '')

    record.status = 'awaiting_clarification'
    record.clarificationPrompt = proofPrompt
    record.clarificationCount = (record.clarificationCount || 0) + 1

    if (!record.clarificationHistory) record.clarificationHistory = []
    record.clarificationHistory.push({
      cycle: record.clarificationCount,
      prompt: proofPrompt,
      response: null,
      timestamp: new Date().toISOString(),
      evidenceIds: [],
    })
    record.updatedAt = new Date().toISOString()

    return HttpResponse.json(record, { status: 200 })
  }),
]
