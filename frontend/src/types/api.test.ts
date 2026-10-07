import { describe, it, expect } from 'vitest'
import type {
  RefundRecord,
  RefundDetail,
  RefundStatus,
  RefundDecision,
  RefundCategory,
  EvidenceItem,
  ClarificationTurn,
  ToolCallAudit,
  ProblemDetails,
  ValidationProblemDetails,
  RefundCreateRequest,
  RefundCreateResponse,
  RefundClarificationRequest,
  RefundOverrideRequest,
  ReviewerProofRequest,
} from './api'

describe('API Types Contract and Compatibility', () => {
  it('validates a complete mocked RefundRecord object', () => {
    const mockEvidence: EvidenceItem = {
      evidenceId: 'evi_test123',
      storageKey: 'evidence/ref_test/crack.jpg',
      filename: 'crack.jpg',
      contentType: 'image/jpeg',
      sizeBytes: 10240,
      url: '/static/uploads/evidence/ref_test/crack.jpg',
      createdAt: '2026-09-28T00:00:00Z',
    }

    const mockClarificationTurn: ClarificationTurn = {
      cycle: 1,
      prompt: 'Please provide damage photos',
      response: 'Attached damage photo',
      timestamp: '2026-09-28T00:01:00Z',
      evidenceIds: [mockEvidence.evidenceId],
    }

    const mockToolAudit: ToolCallAudit = {
      toolName: 'query_carrier_tracking',
      inputArgs: { trackingNumber: 'TRK-1001' },
      rawOutput: { status: 'delivered' },
      durationSeconds: 0.35,
      timestamp: '2026-09-28T00:01:30Z',
    }

    const mockRefundRecord: RefundRecord = {
      refundId: 'ref_abc123',
      orderId: 'ORD-1001',
      customerRequestText: 'Chair arrived broken with cracked frame.',
      status: 'completed',
      decision: 'auto_approve',
      reasoning: 'Damage confirmed via photo evidence.',
      category: 'damaged',
      confidenceScore: 0.95,
      matchedPolicyRule: {
        category: 'damaged',
        policyName: 'standard_damaged',
        action: 'auto_approve',
        returnRequired: false,
      },
      clarificationCount: 1,
      clarificationPrompt: 'Please provide damage photos',
      clarificationResponse: 'Attached damage photo',
      clarificationHistory: [mockClarificationTurn],
      evidence: [mockEvidence],
      toolCalls: [mockToolAudit],
      approvalEmailText: 'Your refund has been approved.',
      denialEmailText: null,
      clarificationEmailText: null,
      overrideDecision: null,
      overrideReason: null,
      overriddenAt: null,
      createdAt: '2026-09-28T00:00:00Z',
      updatedAt: '2026-09-28T00:02:00Z',
    }

    expect(mockRefundRecord.refundId).toBe('ref_abc123')
    expect(mockRefundRecord.status).toBe('completed')
    expect(mockRefundRecord.decision).toBe('auto_approve')
    expect(mockRefundRecord.evidence).toHaveLength(1)
    expect(mockRefundRecord.clarificationHistory).toHaveLength(1)

    // Type compatibility check: RefundRecord and RefundDetail are structurally identical
    const asDetail: RefundDetail = mockRefundRecord
    expect(asDetail.orderId).toBe('ORD-1001')
  })

  it('validates status, decision, and category literal unions', () => {
    const statuses: RefundStatus[] = ['pending', 'completed', 'escalated', 'awaiting_clarification']
    const decisions: RefundDecision[] = ['auto_approve', 'deny', 'escalate', 'approve']
    const categories: RefundCategory[] = [
      'damaged',
      'wrong_item',
      'changed_mind',
      'late_delivery',
      'missing_item',
    ]

    expect(statuses).toContain('pending')
    expect(decisions).toContain('auto_approve')
    expect(categories).toContain('wrong_item')
  })

  it('validates ProblemDetails and ValidationProblemDetails error schemas', () => {
    const problem: ProblemDetails = {
      type: 'urn:problem:not-found',
      title: 'Resource Not Found',
      status: 404,
      detail: "Refund request 'ref_missing' not found.",
      instance: '/v1/refunds/ref_missing',
    }

    const validationProblem: ValidationProblemDetails = {
      type: 'urn:problem:validation-error',
      title: 'Validation Error',
      status: 422,
      detail: 'Invalid parameters provided.',
      instance: '/v1/refunds',
      invalidParams: [
        {
          name: 'orderId',
          reason: 'Field cannot be blank or empty.',
        },
      ],
    }

    expect(problem.status).toBe(404)
    expect(validationProblem.status).toBe(422)
    expect(validationProblem.invalidParams?.[0]?.name).toBe('orderId')
  })

  it('validates request payload interfaces', () => {
    const createReq: RefundCreateRequest = {
      orderId: 'ORD-1002',
      customerRequestText: 'Item never arrived.',
    }

    const createResp: RefundCreateResponse = {
      refundId: 'ref_new789',
      orderId: 'ORD-1002',
      status: 'pending',
      createdAt: '2026-09-28T00:00:00Z',
    }

    const clarifyReq: RefundClarificationRequest = {
      responseText: 'Here are the details requested.',
    }

    const overrideReq: RefundOverrideRequest = {
      overrideDecision: 'approve',
      overrideReason: 'Customer is loyal member.',
    }

    const proofReq: ReviewerProofRequest = {
      proofPrompt: 'Please upload image of box label.',
      customerName: 'Sam',
    }

    expect(createReq.orderId).toBe('ORD-1002')
    expect(createResp.status).toBe('pending')
    expect(clarifyReq.responseText).toBeTruthy()
    expect(overrideReq.overrideDecision).toBe('approve')
    expect(proofReq.proofPrompt).toBeTruthy()
  })

  it('validates bulk export job request and response interfaces', () => {
    const jobReq = {
      format: 'csv' as const,
      status: 'completed' as const,
      columns: ['refund_id', 'order_id', 'refund_amount', 'status'],
    }

    const jobResp = {
      job_id: 'job_export_123',
      status: 'completed' as const,
      format: 'csv' as const,
      created_at: '2026-10-06T12:00:00Z',
      download_url: 'https://s3.example.com/exports/job_123.csv',
      record_count: 42,
    }

    expect(jobReq.format).toBe('csv')
    expect(jobReq.columns).toHaveLength(4)
    expect(jobResp.job_id).toBe('job_export_123')
    expect(jobResp.status).toBe('completed')
    expect(jobResp.record_count).toBe(42)
  })

  it('validates recurring export schedule and trigger response interfaces', () => {
    const schedule = {
      schedule_id: 'sch_abc123',
      name: 'Weekly Executive Audit',
      recipients: ['audit@example.com', 'finance@example.com'],
      frequency: 'weekly' as const,
      format: 'csv' as const,
      columns: ['refund_id', 'refund_amount'],
      enabled: true,
      created_at: '2026-10-06T12:00:00Z',
      last_run: '2026-10-06T12:30:00Z',
      last_status: 'success' as const,
    }

    const triggerResp = {
      schedule_id: 'sch_abc123',
      records_exported: 15,
      recipients_delivered: ['audit@example.com'],
      status: 'success' as const,
      executed_at: '2026-10-06T12:35:00Z',
    }

    expect(schedule.name).toBe('Weekly Executive Audit')
    expect(schedule.recipients).toContain('finance@example.com')
    expect(triggerResp.records_exported).toBe(15)
    expect(triggerResp.status).toBe('success')
  })

  it('validates EvidenceItem with malware scan metadata and quarantine states', () => {
    const cleanItem: EvidenceItem = {
      evidenceId: 'evi_clean1',
      storageKey: 'evidence/clean.jpg',
      filename: 'clean.jpg',
      contentType: 'image/jpeg',
      sizeBytes: 20480,
      url: '/static/evidence/clean.jpg',
      createdAt: '2026-10-06T12:00:00Z',
      scanStatus: 'clean',
      scannedAt: '2026-10-06T12:00:05Z',
      threatName: undefined,
    }

    const infectedItem: EvidenceItem = {
      evidenceId: 'evi_infected2',
      storageKey: 'evidence/infected.jpg',
      filename: 'infected.jpg',
      contentType: 'image/jpeg',
      sizeBytes: 1500,
      url: '/static/evidence/infected.jpg',
      createdAt: '2026-10-06T12:00:00Z',
      scanStatus: 'infected',
      scannedAt: '2026-10-06T12:00:02Z',
      threatName: 'Win32.Eicar.TestFile',
    }

    expect(cleanItem.scanStatus).toBe('clean')
    expect(cleanItem.threatName).toBeUndefined()
    expect(infectedItem.scanStatus).toBe('infected')
    expect(infectedItem.threatName).toBe('Win32.Eicar.TestFile')
  })

  it('validates tiered approval limits, monetary amounts, and escalation decision types', () => {
    const overrideDecisions: ('approve' | 'deny' | 'escalate')[] = ['approve', 'deny', 'escalate']
    expect(overrideDecisions).toContain('escalate')

    const escalatedRecord: RefundRecord = {
      refundId: 'ref_high_value',
      orderId: 'ORD-1010',
      customerRequestText: 'High value monitor damaged.',
      status: 'escalated',
      decision: 'escalate',
      reasoning: 'Refund amount $1,299.99 exceeds supervisor limit of $500.00.',
      category: 'damaged',
      confidenceScore: 0.88,
      escalationTier: 'senior_manager',
      refundAmount: 1299.99,
      orderAmount: 1299.99,
      matchedPolicyRule: null,
      clarificationCount: 0,
      clarificationPrompt: null,
      clarificationResponse: null,
      clarificationHistory: [],
      evidence: [],
      toolCalls: [],
      approvalEmailText: null,
      denialEmailText: null,
      clarificationEmailText: null,
      overrideDecision: null,
      overrideReason: null,
      overriddenAt: null,
      createdAt: '2026-10-06T12:00:00Z',
      updatedAt: '2026-10-06T12:05:00Z',
    }

    expect(escalatedRecord.escalationTier).toBe('senior_manager')
    expect(escalatedRecord.refundAmount).toBe(1299.99)
    expect(escalatedRecord.orderAmount).toBe(1299.99)
  })
})
