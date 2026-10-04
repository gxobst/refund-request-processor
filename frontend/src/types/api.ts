import type { components, paths, operations } from './api.generated'

export type { paths, operations, components }

// Schema model aliases
export type Schema<T extends keyof components['schemas']> = components['schemas'][T]

export type ServiceInfo = components['schemas']['ServiceInfo']
export type HealthStatus = components['schemas']['HealthStatus']
export type RefundStatus = components['schemas']['RefundStatus']
export type RefundDecision = components['schemas']['RefundDecision']
export type RefundCategory = components['schemas']['RefundCategory']
export type OverrideDecisionType = 'approve' | 'deny' | 'escalate'

export type RefundCreateRequest = components['schemas']['RefundCreateRequest']
export type RefundCreateResponse = components['schemas']['RefundCreateResponse']
export type RefundClarificationRequest = components['schemas']['RefundClarificationRequest']
export interface RefundOverrideRequest {
  override_decision?: OverrideDecisionType
  overrideDecision?: OverrideDecisionType
  reason?: string
  override_reason?: string
  overrideReason?: string
}
export type ReviewerProofRequest = components['schemas']['ReviewerProofRequest']

export type EvidenceItem = components['schemas']['EvidenceItem'] & {
  scanStatus?: 'clean' | 'pending' | 'infected'
  scan_status?: 'clean' | 'pending' | 'infected'
  scannedAt?: string
  scanned_at?: string
  threatName?: string
  threat_name?: string
}
export type ClarificationTurn = components['schemas']['ClarificationTurn']
export type ToolCallAudit = components['schemas']['ToolCallAudit']
export type MatchedPolicyRule = components['schemas']['MatchedPolicyRule']

/**
 * RefundDetail represents the complete refund request record returned by the backend.
 * Aliased as RefundRecord for convenience and compatibility across back-office views.
 */
export type RefundRecord = components['schemas']['RefundDetail'] & {
  escalationTier?: 'supervisor' | 'senior_manager' | null
  escalation_tier?: 'supervisor' | 'senior_manager' | null
  refundAmount?: number | null
  refund_amount?: number | null
  orderAmount?: number | null
  order_amount?: number | null
}
export type RefundDetail = RefundRecord

export type ProblemDetails = components['schemas']['ProblemDetails']
export type ValidationProblemDetails = components['schemas']['ValidationProblemDetails']
export type InvalidParam = components['schemas']['InvalidParam']

export interface BulkExportJobRequest {
  format?: 'csv' | 'json'
  status?: RefundStatus | null
  start_date?: string | null
  end_date?: string | null
  columns?: string[]
}

export interface BulkExportJobResponse {
  job_id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  format: 'csv' | 'json'
  created_at: string
  expires_at?: string | null
  completed_at?: string | null
  download_url?: string | null
  record_count?: number | null
  error?: string | null
}

export interface ExportSchedule {
  schedule_id: string
  scheduleId?: string
  name: string
  recipients: string[]
  frequency: 'daily' | 'weekly'
  format: 'csv' | 'json'
  status_filter?: RefundStatus | null
  statusFilter?: RefundStatus | null
  columns?: string[] | null
  enabled: boolean
  created_at: string
  createdAt?: string
  last_run?: string | null
  lastRun?: string | null
  last_status?: 'success' | 'failure' | 'never_run'
  lastStatus?: 'success' | 'failure' | 'never_run'
}

export interface CreateExportSchedulePayload {
  name: string
  recipients: string[]
  frequency?: 'daily' | 'weekly'
  format?: 'csv' | 'json'
  status_filter?: RefundStatus | null
  statusFilter?: RefundStatus | null
  columns?: string[] | null
  enabled?: boolean
}

export interface UpdateExportSchedulePayload {
  name?: string
  recipients?: string[]
  frequency?: 'daily' | 'weekly'
  format?: 'csv' | 'json'
  status_filter?: RefundStatus | null
  statusFilter?: RefundStatus | null
  columns?: string[] | null
  enabled?: boolean
}

export interface ExportTriggerResponse {
  schedule_id: string
  scheduleId?: string
  records_exported: number
  recordsExported?: number
  recipients_delivered: string[]
  recipientsDelivered?: string[]
  status: 'success' | 'failure'
  executed_at: string
  executedAt?: string
}


