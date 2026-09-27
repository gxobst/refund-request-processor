import { apiClient } from './apiClient'
import type { RefundRecord, RefundStatus, RefundCreateResponse } from '../types/api'

export interface ListRefundsParams {
  status?: RefundStatus
  limit?: number
}

export interface SubmitRefundParams {
  orderId: string
  customerRequestText: string
  file?: File | Blob | null
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

export const refundService = {
  listRefunds,
  submitRefund,
}
