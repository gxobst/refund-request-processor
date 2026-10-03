import { apiClient, buildUrl } from './apiClient'
import { getActiveUserRole } from '../context/RoleContext'

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

export interface TrendDataPoint {
  period: string
  total_requests: number
  auto_approved: number
  denied: number
  escalated: number
  average_confidence: number
  average_latency_ms: number
}

export interface AnalyticsTrendsResponse {
  interval: 'daily' | 'weekly'
  start_date: string | null
  end_date: string | null
  points: TrendDataPoint[]
}

/**
 * Fetches aggregate operational analytics and AI metrics.
 */
export async function fetchAnalyticsMetrics(
  startDate?: string,
  endDate?: string
): Promise<AnalyticsMetrics> {
  const params = new URLSearchParams()
  if (startDate) params.append('start_date', startDate)
  if (endDate) params.append('end_date', endDate)
  const queryString = params.toString()
  return apiClient.get<AnalyticsMetrics>(
    `/v1/analytics/metrics${queryString ? `?${queryString}` : ''}`
  )
}

/**
 * Fetches historical trend time-series analytics.
 */
export async function fetchAnalyticsTrends(
  startDate?: string,
  endDate?: string,
  interval?: 'daily' | 'weekly'
): Promise<AnalyticsTrendsResponse> {
  const params = new URLSearchParams()
  if (startDate) params.append('start_date', startDate)
  if (endDate) params.append('end_date', endDate)
  if (interval) params.append('interval', interval)
  const queryString = params.toString()
  return apiClient.get<AnalyticsTrendsResponse>(
    `/v1/analytics/trends${queryString ? `?${queryString}` : ''}`
  )
}

/**
 * Exports operational analytics report as a binary Blob in CSV or PDF format.
 */
export async function exportAnalyticsReport(
  format: 'csv' | 'pdf',
  startDate?: string,
  endDate?: string
): Promise<Blob> {
  const params = new URLSearchParams()
  params.append('format', format)
  if (startDate) params.append('start_date', startDate)
  if (endDate) params.append('end_date', endDate)
  const queryString = params.toString()
  const path = `/v1/analytics/export?${queryString}`
  const url = buildUrl(path)

  const headers = new Headers()
  headers.set('X-User-Role', getActiveUserRole())
  if (format === 'csv') {
    headers.set('Accept', 'text/csv, application/problem+json')
  } else {
    headers.set('Accept', 'application/pdf, application/problem+json')
  }

  const response = await fetch(url, {
    method: 'GET',
    headers,
  })

  if (!response.ok) {
    let errorMsg = `Export failed with status ${response.status}`
    try {
      const errJson = await response.json()
      if (errJson?.detail) {
        errorMsg = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail)
      }
    } catch {
      // ignore
    }
    throw new Error(errorMsg)
  }

  return await response.blob()
}
