import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import { AnalyticsDashboardModal } from '@/components/analytics/AnalyticsDashboardModal'
import type { AnalyticsMetrics } from '@/services/analyticsService'

const MOCK_LATENCY_METRICS: AnalyticsMetrics = {
  total_requests: 15,
  status_breakdown: {
    pending: 2,
    completed: 10,
    escalated: 2,
    awaiting_clarification: 1,
  },
  decision_breakdown: {
    auto_approve: 10,
    deny: 2,
    escalate: 2,
    pending: 1,
  },
  auto_approval_rate: 0.6667,
  override_rate: 0.10,
  average_confidence: 0.94,
  category_breakdown: {
    damaged: 8,
    wrong_item: 5,
    late_delivery: 2,
  },
  average_latency_ms: 1240.0,
  node_latency_breakdown: {
    classifier: 240.0,
    policy_checker: 400.0,
    decision_agent: 600.0,
  },
}

const MOCK_ZERO_LATENCY_METRICS: AnalyticsMetrics = {
  total_requests: 5,
  status_breakdown: {
    pending: 5,
    completed: 0,
    escalated: 0,
    awaiting_clarification: 0,
  },
  decision_breakdown: {
    auto_approve: 0,
    deny: 0,
    escalate: 0,
    pending: 5,
  },
  auto_approval_rate: 0.0,
  override_rate: 0.0,
  average_confidence: 0.0,
  category_breakdown: {},
  average_latency_ms: 0.0,
  node_latency_breakdown: {
    classifier: 0.0,
    policy_checker: 0.0,
    decision_agent: 0.0,
  },
}

const MOCK_EMPTY_METRICS: AnalyticsMetrics = {
  total_requests: 0,
  status_breakdown: {
    pending: 0,
    completed: 0,
    escalated: 0,
    awaiting_clarification: 0,
  },
  decision_breakdown: {
    auto_approve: 0,
    deny: 0,
    escalate: 0,
    pending: 0,
  },
  auto_approval_rate: 0.0,
  override_rate: 0.0,
  average_confidence: 0.0,
  category_breakdown: {},
  average_latency_ms: 0.0,
  node_latency_breakdown: {
    classifier: 0.0,
    policy_checker: 0.0,
    decision_agent: 0.0,
  },
}

function renderModal(isOpen = true, onClose = () => {}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <AnalyticsDashboardModal isOpen={isOpen} onClose={onClose} />
    </QueryClientProvider>
  )
}

describe('LLM Inference Latency and Operational Telemetry Integration Tests', () => {
  beforeEach(() => {
    server.use(
      http.get('*/v1/analytics/metrics', () => {
        return HttpResponse.json(MOCK_LATENCY_METRICS, { status: 200 })
      })
    )
  })

  it('renders the Average Latency KPI card with formatted latency', async () => {
    renderModal()

    await waitFor(() => {
      expect(screen.getByTestId('kpi-average-latency')).toBeInTheDocument()
    })

    const latencyCard = screen.getByTestId('kpi-average-latency')
    expect(latencyCard).toHaveTextContent(/average latency/i)
    expect(latencyCard).toHaveTextContent('1,240 ms')
    expect(latencyCard).toHaveTextContent(/end-to-end evaluation/i)
  })

  it('renders the Agent Latency Breakdown section with Classifier, Policy Checker, and Decision Agent metrics', async () => {
    renderModal()

    await waitFor(() => {
      expect(screen.getByTestId('latency-distribution')).toBeInTheDocument()
    })

    const breakdownSection = screen.getByTestId('latency-distribution')
    expect(breakdownSection).toHaveTextContent('Agent Latency Breakdown')
    expect(breakdownSection).toHaveTextContent('Execution time per agent node')

    // Classifier node
    const classifierNode = screen.getByTestId('latency-node-classifier')
    expect(classifierNode).toBeInTheDocument()
    expect(classifierNode).toHaveTextContent('Classifier')
    expect(classifierNode).toHaveTextContent('240 ms')

    // Policy Checker node
    const policyCheckerNode = screen.getByTestId('latency-node-policy_checker')
    expect(policyCheckerNode).toBeInTheDocument()
    expect(policyCheckerNode).toHaveTextContent('Policy Checker')
    expect(policyCheckerNode).toHaveTextContent('400 ms')

    // Decision Agent node
    const decisionAgentNode = screen.getByTestId('latency-node-decision_agent')
    expect(decisionAgentNode).toBeInTheDocument()
    expect(decisionAgentNode).toHaveTextContent('Decision Agent')
    expect(decisionAgentNode).toHaveTextContent('600 ms')
  })

  it('handles zero-latency metrics gracefully without NaN or UI distortion', async () => {
    server.use(
      http.get('*/v1/analytics/metrics', () => {
        return HttpResponse.json(MOCK_ZERO_LATENCY_METRICS, { status: 200 })
      })
    )

    renderModal()

    await waitFor(() => {
      expect(screen.getByTestId('kpi-average-latency')).toBeInTheDocument()
    })

    const latencyCard = screen.getByTestId('kpi-average-latency')
    expect(latencyCard).toHaveTextContent('0 ms')
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()

    const breakdownSection = screen.getByTestId('latency-distribution')
    expect(breakdownSection).toBeInTheDocument()

    const classifierNode = screen.getByTestId('latency-node-classifier')
    expect(classifierNode).toHaveTextContent('0 ms')

    const policyCheckerNode = screen.getByTestId('latency-node-policy_checker')
    expect(policyCheckerNode).toHaveTextContent('0 ms')

    const decisionAgentNode = screen.getByTestId('latency-node-decision_agent')
    expect(decisionAgentNode).toHaveTextContent('0 ms')

    // Ensure progress bar styles do not contain NaN
    const progressBars = breakdownSection.querySelectorAll('.w-full > div')
    expect(progressBars.length).toBe(3)
    progressBars.forEach((bar) => {
      const style = bar.getAttribute('style') || ''
      expect(style).not.toContain('NaN')
      expect(style).toContain('width: 0%')
    })
  })

  it('when total_requests is 0, renders the empty state banner without rendering latency KPI cards', async () => {
    server.use(
      http.get('*/v1/analytics/metrics', () => {
        return HttpResponse.json(MOCK_EMPTY_METRICS, { status: 200 })
      })
    )

    renderModal()

    await waitFor(() => {
      expect(screen.getByTestId('analytics-empty')).toBeInTheDocument()
    })

    expect(screen.getByText('No Analytics Data Available')).toBeInTheDocument()
    expect(screen.queryByTestId('kpi-average-latency')).not.toBeInTheDocument()
    expect(screen.queryByTestId('latency-distribution')).not.toBeInTheDocument()
  })
})
