import { Page, Route } from '@playwright/test'

export interface MockRefundRecord {
  refundId: string
  orderId: string
  customerRequestText: string
  status: string
  decision: string | null
  confidenceScore: number | null
  category: string
  reasoning: string | null
  orderAmount: number | null
  currency: string
  customerEmail: string
  clarificationPrompt?: string | null
  clarificationResponse?: string | null
  clarificationCount?: number
  clarificationHistory?: Array<{
    cycle: number
    prompt: string
    response?: string | null
    timestamp: string
  }>
  evidence?: Array<{
    evidenceId: string
    filename: string
    contentType: string
    sizeBytes: number
    url: string
    createdAt: string
  }>
  toolCalls?: Array<{
    toolName: string
    inputArgs: Record<string, unknown>
    rawOutput: Record<string, unknown>
    durationSeconds: number
    executedAt: string
  }>
  overrideDecision?: string | null
  overrideReason?: string | null
  overriddenAt?: string | null
  createdAt: string
  updatedAt: string
}

export const DEFAULT_MOCK_REFUNDS: MockRefundRecord[] = [
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
    createdAt: '2026-09-28T10:00:00Z',
    updatedAt: '2026-09-28T10:01:00Z',
  },
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
    createdAt: '2026-09-28T09:30:00Z',
    updatedAt: '2026-09-28T09:32:00Z',
  },
  {
    refundId: 'ref-103',
    orderId: 'ORD-1003',
    customerRequestText: 'Ordered 3-pack t-shirts, only received 1 shirt in packaging.',
    status: 'awaiting_clarification',
    decision: 'escalate',
    confidenceScore: 0.65,
    category: 'missing_item',
    reasoning: 'Customer asked to supply photo of packaging and packing slip.',
    orderAmount: 39.99,
    currency: 'USD',
    customerEmail: 'customer3@example.com',
    clarificationPrompt: 'Please upload a photo of the exterior shipping box and packing slip.',
    clarificationResponse: null,
    clarificationCount: 1,
    clarificationHistory: [
      {
        cycle: 1,
        prompt: 'Please upload a photo of the exterior shipping box and packing slip.',
        response: null,
        timestamp: '2026-09-28T09:05:00Z',
      },
    ],
    createdAt: '2026-09-28T09:00:00Z',
    updatedAt: '2026-09-28T09:05:00Z',
  },
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
    createdAt: '2026-09-28T10:10:00Z',
    updatedAt: '2026-09-28T10:10:00Z',
  },
  {
    refundId: 'ref-105',
    orderId: 'ORD-1005',
    customerRequestText: 'Did not like the fabric texture, purchased 60 days ago.',
    status: 'completed',
    decision: 'deny',
    confidenceScore: 0.94,
    category: 'changed_mind',
    reasoning: 'Return window expired 30 days after delivery. Denied per policy.',
    orderAmount: 64.0,
    currency: 'USD',
    customerEmail: 'customer5@example.com',
    createdAt: '2026-09-28T08:00:00Z',
    updatedAt: '2026-09-28T08:02:00Z',
  },
]

export interface MockApiState {
  refunds: MockRefundRecord[]
}

/**
 * Intercepts all backend /v1/refunds network calls made by the browser frontend
 * and serves deterministic in-memory responses.
 */
export async function setupMockApi(page: Page, initialRefunds = DEFAULT_MOCK_REFUNDS): Promise<MockApiState> {
  const state: MockApiState = {
    refunds: JSON.parse(JSON.stringify(initialRefunds)),
  }

  await page.route('**/v1/refunds**', async (route: Route) => {
    const request = route.request()
    const url = new URL(request.url())
    const method = request.method().toUpperCase()
    const pathname = url.pathname

    // 1. Manual Decision Override: POST /v1/refunds/:id/override
    const overrideMatch = pathname.match(/\/v1\/refunds\/([^/?#]+)\/override/)
    if (method === 'POST' && overrideMatch) {
      const refundId = decodeURIComponent(overrideMatch[1])
      const target = state.refunds.find((r) => r.refundId === refundId)
      if (!target) {
        return route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ title: 'Not Found', detail: `Refund ${refundId} not found` }),
        })
      }

      let bodyData: { override_decision?: string; override_reason?: string } = {}
      try {
        bodyData = JSON.parse(request.postData() || '{}')
      } catch {
        bodyData = {}
      }

      target.overrideDecision = bodyData.override_decision || 'approve'
      target.overrideReason = bodyData.override_reason || 'Supervisor override approved.'
      target.overriddenAt = new Date().toISOString()
      target.updatedAt = new Date().toISOString()

      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(target),
      })
    }

    // 2. Submit Clarification: POST /v1/refunds/:id/clarify
    const clarifyMatch = pathname.match(/\/v1\/refunds\/([^/?#]+)\/clarify/)
    if (method === 'POST' && clarifyMatch) {
      const refundId = decodeURIComponent(clarifyMatch[1])
      const target = state.refunds.find((r) => r.refundId === refundId)
      if (!target) {
        return route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ title: 'Not Found', detail: `Refund ${refundId} not found` }),
        })
      }

      let responseText = 'Customer response received.'
      const postData = request.postData()
      if (postData) {
        try {
          const parsed = JSON.parse(postData)
          if (parsed.response_text) responseText = parsed.response_text
        } catch {
          // May be multipart, search string for response_text
          const match = postData.match(/name="response_text"\r?\n\r?\n([^\r\n]+)/)
          if (match) responseText = match[1]
        }
      }

      target.clarificationResponse = responseText
      target.status = 'pending'
      target.updatedAt = new Date().toISOString()

      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(target),
      })
    }

    // 3. Single Refund Detail: GET /v1/refunds/:id
    const singleMatch = pathname.match(/\/v1\/refunds\/([^/?#]+)$/)
    if (method === 'GET' && singleMatch) {
      const refundId = decodeURIComponent(singleMatch[1])
      const target = state.refunds.find((r) => r.refundId === refundId)
      if (!target) {
        return route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ title: 'Not Found', detail: `Refund ${refundId} not found` }),
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(target),
      })
    }

    // 4. Create Refund: POST /v1/refunds
    if (method === 'POST' && (pathname === '/v1/refunds' || pathname.endsWith('/v1/refunds'))) {
      let orderId = 'ORD-9999'
      let customerRequestText = 'Automated refund request test.'
      const postData = request.postData()
      if (postData) {
        try {
          const parsed = JSON.parse(postData)
          if (parsed.order_id) orderId = parsed.order_id
          if (parsed.customer_request_text) customerRequestText = parsed.customer_request_text
        } catch {
          const matchOrder = postData.match(/name="order_id"\r?\n\r?\n([^\r\n]+)/)
          if (matchOrder) orderId = matchOrder[1]
          const matchText = postData.match(/name="customer_request_text"\r?\n\r?\n([^\r\n]+)/)
          if (matchText) customerRequestText = matchText[1]
        }
      }

      const newRefund: MockRefundRecord = {
        refundId: `ref-${Math.floor(1000 + Math.random() * 9000)}`,
        orderId,
        customerRequestText,
        status: 'pending',
        decision: null,
        confidenceScore: null,
        category: 'damaged',
        reasoning: null,
        orderAmount: 99.99,
        currency: 'USD',
        customerEmail: 'testuser@example.com',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      }

      state.refunds.unshift(newRefund)

      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          refund_id: newRefund.refundId,
          status: 'pending',
          message: 'Refund request accepted and queued for evaluation.',
        }),
      })
    }

    // 5. List Refunds: GET /v1/refunds(?status=...)
    if (method === 'GET') {
      const statusParam = url.searchParams.get('status')
      let results = [...state.refunds]
      if (statusParam) {
        results = results.filter((r) => r.status === statusParam)
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(results),
      })
    }

    return route.continue()
  })

  return state
}
