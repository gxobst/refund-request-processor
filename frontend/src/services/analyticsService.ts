import { apiClient } from './apiClient'

export interface StatusBreakdown {
  pending: number
  completed: number
  escalated: number
  awaiting_clarification: number
}

export interface DecisionBreakdown {
  auto_approve: number
  deny: number
  escalate: number
  pending: number
}

export interface AnalyticsMetrics {
  total_requests: number
  status_breakdown: StatusBreakdown
  decision_breakdown: DecisionBreakdown
  auto_approval_rate: number
  override_rate: number
  average_confidence: number
  category_breakdown: Record<string, number>
  average_latency_ms: number
  node_latency_breakdown: Record<string, number>
}

/**
 * Fetches aggregate operational analytics and AI metrics.
 */
export async function fetchAnalyticsMetrics(): Promise<AnalyticsMetrics> {
  return apiClient.get<AnalyticsMetrics>('/v1/analytics/metrics')
}
