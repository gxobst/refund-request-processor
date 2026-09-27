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
})
