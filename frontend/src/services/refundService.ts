import { apiClient, buildUrl } from './apiClient'
import type { RefundRecord, RefundStatus, RefundCreateResponse } from '../types/api'

export interface RefundEventPayload {
  refund_id?: string
  refundId?: string
  order_id?: string
  orderId?: string
  status?: RefundStatus
  decision?: string
  override_decision?: string
  overrideDecision?: string
  reasoning?: string
  confidence_score?: number
  confidenceScore?: number
  [key: string]: unknown
}

export interface PolicyEventPayload {
  category: string
  return_window_days: number
  max_refund_amount: number
  auto_approve_threshold: number
  requires_proof: boolean
  eligible_delivery_statuses: string[]
  refund_window_days?: number
  max_order_amount?: number
  [key: string]: unknown
}

export interface ListRefundsParams {
  status?: RefundStatus
  limit?: number
}

export interface SubmitRefundParams {
  orderId: string
  customerRequestText: string
  file?: File | Blob | null
}

export interface OverrideRefundPayload {
  overrideDecision: 'approve' | 'deny'
  overrideReason: string
}

export interface SubmitClarificationPayload {
  responseText: string
  evidenceFile?: File | Blob | null
}

export interface RequestReviewerProofPayload {
  proofPrompt: string
  customerName?: string | null
}

/**
 * Retrieves the refund evaluation queue with optional status and limit filters.
 */
export async function listRefunds(params?: ListRefundsParams): Promise<RefundRecord[]> {
  const queryParams = new URLSearchParams()

  if (params?.status) {
    queryParams.append('status', params.status)
  }
  if (params?.limit !== undefined && params?.limit !== null) {
    queryParams.append('limit', String(params.limit))
  }

  const queryString = queryParams.toString()
  const path = queryString ? `/v1/refunds?${queryString}` : '/v1/refunds'

  const result = await apiClient.get<RefundRecord[]>(path)
  return result ?? []
}

/**
 * Submits a new refund request for automated evaluation.
 * If a file attachment is provided, dispatches as multipart/form-data.
 * Otherwise dispatches as application/json.
 */
export async function submitRefund(params: SubmitRefundParams): Promise<RefundCreateResponse> {
  const path = '/v1/refunds'

  if (params.file) {
    const formData = new FormData()
    formData.append('order_id', params.orderId)
    formData.append('customer_request_text', params.customerRequestText)
    formData.append('file', params.file)

    return apiClient.postMultipart<RefundCreateResponse>(path, formData)
  }

  const payload = {
    order_id: params.orderId,
    customer_request_text: params.customerRequestText,
  }

  return apiClient.post<RefundCreateResponse>(path, payload)
}

/**
 * Retrieves detailed record and agent reasoning for a specific refund request.
 */
export async function getRefundById(refundId: string): Promise<RefundRecord> {
  const path = `/v1/refunds/${encodeURIComponent(refundId)}`
  return apiClient.get<RefundRecord>(path)
}

/**
 * Applies a binding human operator / supervisor override decision to an escalated refund.
 */
export async function overrideRefundDecision(
  refundId: string,
  payload: OverrideRefundPayload,
): Promise<RefundRecord> {
  const path = `/v1/refunds/${encodeURIComponent(refundId)}/override`
  const body = {
    override_decision: payload.overrideDecision,
    override_reason: payload.overrideReason,
  }
  return apiClient.post<RefundRecord>(path, body)
}

/**
 * Submits customer clarification response text and optional evidence image.
 */
export async function submitClarification(
  refundId: string,
  payload: SubmitClarificationPayload,
): Promise<RefundRecord> {
  const path = `/v1/refunds/${encodeURIComponent(refundId)}/clarify`

  if (payload.evidenceFile) {
    const formData = new FormData()
    formData.append('response_text', payload.responseText)
    formData.append('evidence_file', payload.evidenceFile)
    return apiClient.postMultipart<RefundRecord>(path, formData)
  }

  const body = {
    response_text: payload.responseText,
  }
  return apiClient.post<RefundRecord>(path, body)
}

/**
 * Uploads a customer proof image (JPEG, PNG, WebP <= 5MB) for a refund.
 */
export async function uploadEvidence(
  refundId: string,
  file: File | Blob,
): Promise<RefundRecord> {
  const path = `/v1/refunds/${encodeURIComponent(refundId)}/evidence`
  const formData = new FormData()
  formData.append('file', file)
  return apiClient.postMultipart<RefundRecord>(path, formData)
}

/**
 * Submits a supervisor proof inquiry prompt for an escalated refund.
 */
export async function requestReviewerProof(
  refundId: string,
  payload: RequestReviewerProofPayload,
): Promise<RefundRecord> {
  const path = `/v1/refunds/${encodeURIComponent(refundId)}/request-proof`
  const body: Record<string, unknown> = {
    proof_prompt: payload.proofPrompt,
  }
  if (payload.customerName !== undefined && payload.customerName !== null) {
    body.customer_name = payload.customerName
  }
  return apiClient.post<RefundRecord>(path, body)
}

/**
 * Subscribes to real-time refund server-sent events (SSE).
 *
 * @param onEvent Callback invoked when a refund_update event or message is received.
 * @param onError Optional callback invoked on EventSource error.
 * @param onOpen Optional callback invoked when the connection is opened.
 * @param onPolicyEvent Optional callback invoked when a policy_update event is received.
 * @returns A cleanup function that closes the EventSource connection.
 */
export function subscribeToRefundEvents(
  onEvent: (event: RefundEventPayload) => void,
  onError?: (err: Event) => void,
  onOpen?: () => void,
  onPolicyEvent?: (event: PolicyEventPayload) => void,
): () => void {
  if (typeof window === 'undefined' || typeof EventSource === 'undefined') {
    return () => {}
  }

  const url = buildUrl('/v1/refunds/events')
  const eventSource = new EventSource(url)

  if (onOpen) {
    eventSource.onopen = () => {
      onOpen()
    }
  }

  const handleMessage = (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data) as RefundEventPayload
      onEvent(data)
    } catch {
      // Ignore non-JSON or ping payloads
    }
  }

  const handlePolicyMessage = (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data) as PolicyEventPayload
      if (onPolicyEvent) {
        onPolicyEvent(data)
      } else {
        onEvent(data as unknown as RefundEventPayload)
      }
    } catch {
      // Ignore non-JSON or ping payloads
    }
  }

  eventSource.addEventListener('refund_update', handleMessage)
  eventSource.addEventListener('policy_update', handlePolicyMessage)
  eventSource.onmessage = handleMessage

  eventSource.addEventListener('ping', () => {
    if (onOpen) {
      onOpen()
    }
  })

  if (onError) {
    eventSource.onerror = (err) => {
      onError(err)
    }
  }

  return () => {
    eventSource.removeEventListener('refund_update', handleMessage)
    eventSource.removeEventListener('policy_update', handlePolicyMessage)
    eventSource.close()
  }
}

export const refundService = {
  listRefunds,
  submitRefund,
  getRefundById,
  overrideRefundDecision,
  submitClarification,
  uploadEvidence,
  requestReviewerProof,
  subscribeToRefundEvents,
}
