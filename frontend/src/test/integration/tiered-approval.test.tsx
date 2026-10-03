import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import { RoleProvider, UserRole } from '@/context/RoleContext'
import { ManualOverrideModal } from '@/components/modals/ManualOverrideModal'
import { RefundDetailDrawer } from '@/components/detail/RefundDetailDrawer'
import App from '@/App'
import type { ProblemDetails, RefundRecord } from '@/types/api'

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  })
}

function renderApp(initialRole?: UserRole) {
  const testClient = createTestQueryClient()
  return render(
    <QueryClientProvider client={testClient}>
      <RoleProvider initialRole={initialRole}>
        <App client={testClient} />
      </RoleProvider>
    </QueryClientProvider>
  )
}

describe('Tiered Approval Limits and Multi-Tier Escalation Integration Tests', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('cycles Header role switcher between Supervisor, Senior Manager, and Agent with approval limits', async () => {
    renderApp('supervisor')

    // Initial state: Supervisor ($500)
    const roleSwitcher = await screen.findByTestId('role-switcher')
    expect(roleSwitcher).toBeInTheDocument()
    expect(roleSwitcher).toHaveTextContent(/Supervisor/i)
    expect(roleSwitcher).toHaveTextContent(/\$500/i)

    // Toggle 1: Senior Manager ($2,500)
    fireEvent.click(roleSwitcher)
    expect(roleSwitcher).toHaveTextContent(/Senior Manager/i)
    expect(roleSwitcher).toHaveTextContent(/\$2,500/i)
    expect(window.localStorage.getItem('user_role')).toBe('senior_manager')

    // Toggle 2: Agent ($100)
    fireEvent.click(roleSwitcher)
    expect(roleSwitcher).toHaveTextContent(/Agent/i)
    expect(roleSwitcher).toHaveTextContent(/\$100/i)
    expect(window.localStorage.getItem('user_role')).toBe('agent')

    // Toggle 3: Back to Supervisor ($500)
    fireEvent.click(roleSwitcher)
    expect(roleSwitcher).toHaveTextContent(/Supervisor/i)
    expect(roleSwitcher).toHaveTextContent(/\$500/i)
    expect(window.localStorage.getItem('user_role')).toBe('supervisor')
  })

  it('displays active operator approval limit badge in ManualOverrideModal', () => {
    const testClient = createTestQueryClient()

    render(
      <QueryClientProvider client={testClient}>
        <RoleProvider initialRole="supervisor">
          <ManualOverrideModal
            refundId="ref-test-1"
            orderId="ORD-TEST-1"
            refundAmount={250.0}
            isOpen={true}
            onClose={() => {}}
          />
        </RoleProvider>
      </QueryClientProvider>
    )

    const limitBadge = screen.getByTestId('operator-approval-limit')
    expect(limitBadge).toBeInTheDocument()
    expect(limitBadge).toHaveTextContent(/Supervisor/i)
    expect(limitBadge).toHaveTextContent(/\$500/i)
  })

  it('renders limit warning banner and disables submit button when refund amount exceeds operator limit on approve', () => {
    const testClient = createTestQueryClient()

    render(
      <QueryClientProvider client={testClient}>
        <RoleProvider initialRole="agent">
          <ManualOverrideModal
            refundId="ref-test-2"
            orderId="ORD-TEST-2"
            refundAmount={150.0} // Agent limit is $100
            isOpen={true}
            onClose={() => {}}
          />
        </RoleProvider>
      </QueryClientProvider>
    )

    // Select "Approve Refund"
    const approveBtn = screen.getByTestId('decision-choice-approve')
    fireEvent.click(approveBtn)

    // Verify limit warning banner appears
    const warningBanner = screen.getByTestId('override-limit-warning')
    expect(warningBanner).toBeInTheDocument()
    expect(warningBanner).toHaveTextContent(/\$150\.00/i)
    expect(warningBanner).toHaveTextContent(/exceeds your agent approval limit of \$100\.00/i)

    // Fill in justification and checkbox
    const textarea = screen.getByLabelText(/override justification/i)
    fireEvent.change(textarea, { target: { value: 'Customer deserves exception.' } })
    const confirmCheckbox = screen.getByLabelText(/i confirm this manual decision override/i)
    fireEvent.click(confirmCheckbox)

    // Submit button should remain disabled
    const submitBtn = screen.getByRole('button', { name: /submit override/i })
    expect(submitBtn).toBeDisabled()

    // Escalation prompt button should be available
    const escalateChoice = screen.getByTestId('decision-choice-escalate')
    expect(escalateChoice).toBeInTheDocument()
    fireEvent.click(escalateChoice)

    // Warning banner should disappear and submit button becomes enabled
    expect(screen.queryByTestId('override-limit-warning')).not.toBeInTheDocument()
    expect(submitBtn).not.toBeDisabled()
  })

  it('displays RFC 9457 error banner upon receiving 403 Forbidden limit rejection', async () => {
    const testClient = createTestQueryClient()

    // Override handler to return 403 ProblemDetails
    server.use(
      http.post('*/v1/refunds/:refundId/override', () => {
        const problem: ProblemDetails = {
          type: 'urn:problem:forbidden',
          title: 'Forbidden',
          status: 403,
          detail: 'Refund amount $450.00 exceeds your agent approval limit of $100.00. Escalation to senior approval required.',
          instance: '/v1/refunds/ref-test-3/override',
        }
        return HttpResponse.json(problem, {
          status: 403,
          headers: { 'Content-Type': 'application/problem+json' },
        })
      })
    )

    render(
      <QueryClientProvider client={testClient}>
        <RoleProvider initialRole="supervisor">
          <ManualOverrideModal
            refundId="ref-test-3"
            orderId="ORD-TEST-3"
            refundAmount={450.0}
            isOpen={true}
            onClose={() => {}}
          />
        </RoleProvider>
      </QueryClientProvider>
    )

    // Select approve, enter justification, check confirm
    fireEvent.click(screen.getByTestId('decision-choice-approve'))
    fireEvent.change(screen.getByLabelText(/override justification/i), {
      target: { value: 'Valid customer justification.' },
    })
    fireEvent.click(screen.getByLabelText(/i confirm this manual decision override/i))

    // Submit override
    const submitBtn = screen.getByRole('button', { name: /submit override/i })
    fireEvent.click(submitBtn)

    // Verify error banner is rendered with RFC 9457 details
    await waitFor(() => {
      const errorBanner = screen.getByTestId('override-error-banner')
      expect(errorBanner).toBeInTheDocument()
      expect(errorBanner).toHaveTextContent('Forbidden')
      expect(errorBanner).toHaveTextContent(
        'Refund amount $450.00 exceeds your agent approval limit of $100.00. Escalation to senior approval required.'
      )
    })
  })

  it('displays escalation tier badge in RefundDetailDrawer when escalation_tier is set', async () => {
    const testClient = createTestQueryClient()

    const mockEscalatedRefund: RefundRecord = {
      refundId: 'ref-escalated-1',
      orderId: 'ORD-9999',
      status: 'escalated',
      decision: 'escalate',
      escalationTier: 'senior_manager',
      orderAmount: 1200.0,
      refundAmount: 1200.0,
      customerRequestText: 'High value electronics return request',
      category: 'defective',
      reasoning: 'Exceeds supervisor approval limit. Escalated to senior manager.',
      confidenceScore: 0.9,
      matchedPolicyRule: null,
      approvalEmailText: null,
      denialEmailText: null,
      clarificationEmailText: null,
      clarificationPrompt: null,
      clarificationResponse: null,
      clarificationCount: 0,
      clarificationHistory: [],
      evidence: [],
      toolCalls: [],
      overrideDecision: null,
      overrideReason: null,
      overriddenAt: null,
      createdAt: '2026-10-01T12:00:00Z',
      updatedAt: '2026-10-01T12:00:00Z',
    } as unknown as RefundRecord

    server.use(
      http.get('*/v1/refunds/:refundId', () => {
        return HttpResponse.json(mockEscalatedRefund)
      })
    )

    render(
      <QueryClientProvider client={testClient}>
        <RoleProvider initialRole="supervisor">
          <RefundDetailDrawer
            refundId="ref-escalated-1"
            isOpen={true}
            onClose={() => {}}
          />
        </RoleProvider>
      </QueryClientProvider>
    )

    await waitFor(() => {
      const badge = screen.getByTestId('escalation-tier-badge')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveTextContent(/Escalation: Senior Manager/i)
    })
  })
})
