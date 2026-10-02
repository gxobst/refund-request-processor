import { apiClient } from './apiClient'

export interface PolicyRule {
  category: string
  return_window_days: number
  max_refund_amount: number
  auto_approve_threshold: number
  requires_proof: boolean
  eligible_delivery_statuses: string[]
  refund_window_days?: number
  max_order_amount?: number
}

export interface UpdatePolicyPayload {
  return_window_days?: number
  max_refund_amount?: number
  auto_approve_threshold?: number
  requires_proof?: boolean
  eligible_delivery_statuses?: string[]
}

/**
 * Fetches active refund policies across all categories.
 */
export async function fetchPolicies(): Promise<PolicyRule[]> {
  return apiClient.get<PolicyRule[]>('/v1/policies')
}

/**
 * Updates policy thresholds and rules for a specific refund category.
 */
export async function updatePolicy(
  category: string,
  payload: UpdatePolicyPayload
): Promise<PolicyRule> {
  return apiClient.put<PolicyRule>(`/v1/policies/${category}`, payload)
}
