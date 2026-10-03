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

export interface PolicyFieldChange {
  old_value: unknown
  new_value: unknown
}

export interface PolicyAuditEntry {
  audit_id: string
  category: string
  timestamp: string
  operator_id: string
  changes: Record<string, PolicyFieldChange | Record<string, unknown>>
  previous_state: Record<string, unknown>
  action: string
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

/**
 * Fetches policy configuration version history and audit log.
 */
export async function fetchPolicyHistory(
  category?: string
): Promise<PolicyAuditEntry[]> {
  const url = category
    ? `/v1/policies/history?category=${encodeURIComponent(category)}`
    : '/v1/policies/history'
  return apiClient.get<PolicyAuditEntry[]>(url)
}

/**
 * Restores a refund category's policy to a previous version from the audit log.
 */
export async function rollbackPolicy(
  category: string,
  auditId?: string
): Promise<PolicyRule> {
  const url = auditId
    ? `/v1/policies/${encodeURIComponent(category)}/rollback?audit_id=${encodeURIComponent(auditId)}`
    : `/v1/policies/${encodeURIComponent(category)}/rollback`
  return apiClient.post<PolicyRule>(url, auditId ? { audit_id: auditId } : {})
}

