import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import App from '@/App'
import type { PolicyRule } from '@/services/policyService'

const MOCK_POLICIES: PolicyRule[] = [
  {
    category: 'damaged',
    return_window_days: 30,
    max_refund_amount: 500.0,
    auto_approve_threshold: 0.0,
    requires_proof: false,
    eligible_delivery_statuses: ['delivered'],
    refund_window_days: 30,
    max_order_amount: 500.0,
  },
  {
    category: 'wrong_item',
    return_window_days: 30,
    max_refund_amount: 1000.0,
    auto_approve_threshold: 0.0,
    requires_proof: false,
    eligible_delivery_statuses: ['delivered'],
    refund_window_days: 30,
    max_order_amount: 1000.0,
  },
  {
    category: 'changed_mind',
    return_window_days: 14,
    max_refund_amount: 200.0,
    auto_approve_threshold: 0.0,
    requires_proof: false,
    eligible_delivery_statuses: ['delivered'],
    refund_window_days: 14,
    max_order_amount: 200.0,
  },
  {
    category: 'late_delivery',
    return_window_days: 14,
    max_refund_amount: 300.0,
    auto_approve_threshold: 0.0,
    requires_proof: false,
    eligible_delivery_statuses: ['in_transit', 'delivered'],
    refund_window_days: 14,
    max_order_amount: 300.0,
  },
  {
    category: 'missing_item',
    return_window_days: 30,
    max_refund_amount: 1000.0,
    auto_approve_threshold: 0.0,
    requires_proof: false,
    eligible_delivery_statuses: ['delivered'],
    refund_window_days: 30,
    max_order_amount: 1000.0,
  },
]

function renderApp() {
  const testClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  })
  return render(
    <QueryClientProvider client={testClient}>
      <App />
    </QueryClientProvider>
  )
}

describe('Policy Rule Viewer and Configuration Integration Tests', () => {
  let activePolicies: PolicyRule[]

  beforeEach(() => {
    activePolicies = JSON.parse(JSON.stringify(MOCK_POLICIES))

    server.use(
      http.get('*/v1/policies', () => {
        return HttpResponse.json(activePolicies, { status: 200 })
      }),
      http.put('*/v1/policies/:category', async ({ params, request }) => {
        const { category } = params as { category: string }
        const index = activePolicies.findIndex((p) => p.category === category)
        if (index === -1) {
          return HttpResponse.json(
            {
              type: 'urn:problem:not-found',
              title: 'Not Found',
              status: 404,
              detail: `Category '${category}' not found.`,
            },
            { status: 404 }
          )
        }

        const body = (await request.json()) as Partial<PolicyRule>
        const updated: PolicyRule = {
          ...activePolicies[index],
          ...body,
          category,
          refund_window_days: body.return_window_days ?? activePolicies[index].return_window_days,
          max_order_amount: body.max_refund_amount ?? activePolicies[index].max_refund_amount,
        }
        activePolicies[index] = updated
        return HttpResponse.json(updated, { status: 200 })
      })
    )
  })

  it('renders the Policy Rules button in header and opens PolicyRuleViewerModal on click', async () => {
    renderApp()

    const triggerBtn = screen.getByTestId('policy-rules-button')
    expect(triggerBtn).toBeInTheDocument()
    expect(triggerBtn).toHaveTextContent(/Policy Rules/i)

    fireEvent.click(triggerBtn)

    await waitFor(() => {
      expect(screen.getByTestId('policy-rule-viewer-modal')).toBeInTheDocument()
      expect(screen.getByText('Refund Policy Configuration')).toBeInTheDocument()
    })
  })

  it('displays rule values across all 5 categories: badges, windows, amounts, and statuses', async () => {
    renderApp()

    fireEvent.click(screen.getByTestId('policy-rules-button'))

    await waitFor(() => {
      expect(screen.getByTestId('category-badge-damaged')).toBeInTheDocument()
      expect(screen.getByTestId('category-badge-wrong_item')).toBeInTheDocument()
      expect(screen.getByTestId('category-badge-changed_mind')).toBeInTheDocument()
      expect(screen.getByTestId('category-badge-late_delivery')).toBeInTheDocument()
      expect(screen.getByTestId('category-badge-missing_item')).toBeInTheDocument()
    })

    // Check displayed values for damaged
    expect(screen.getByTestId('policy-return-window-damaged')).toHaveTextContent('30 days')
    expect(screen.getByTestId('policy-max-amount-damaged')).toHaveTextContent('$500.00')
    expect(screen.getByTestId('policy-auto-approve-damaged')).toHaveTextContent('$0.00')
    expect(screen.getByTestId('policy-requires-proof-damaged')).toHaveTextContent('No')
    expect(screen.getByTestId('policy-eligible-statuses-damaged')).toHaveTextContent('delivered')

    // Check displayed values for late_delivery
    expect(screen.getByTestId('policy-return-window-late_delivery')).toHaveTextContent('14 days')
    expect(screen.getByTestId('policy-eligible-statuses-late_delivery')).toHaveTextContent('in_transit')
  })

  it('performs client-side validation preventing negative or zero numbers and displays inline feedback', async () => {
    renderApp()

    fireEvent.click(screen.getByTestId('policy-rules-button'))

    await waitFor(() => {
      expect(screen.getByTestId('input-return-window-damaged')).toBeInTheDocument()
    })

    const returnWindowInput = screen.getByTestId('input-return-window-damaged')
    const maxAmountInput = screen.getByTestId('input-max-amount-damaged')
    const saveBtn = screen.getByTestId('save-policy-damaged')

    // Set invalid non-positive return window
    fireEvent.change(returnWindowInput, { target: { value: '0' } })
    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(screen.getByTestId('error-return-window-damaged')).toHaveTextContent(
        /Return window must be a positive integer/i
      )
    })

    // Set invalid negative max refund amount
    fireEvent.change(returnWindowInput, { target: { value: '30' } })
    fireEvent.change(maxAmountInput, { target: { value: '-50' } })
    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(screen.getByTestId('error-max-amount-damaged')).toHaveTextContent(
        /Maximum refund amount must be a non-negative number/i
      )
    })
  })

  it('submits valid changes, updates displayed values, and shows success notification', async () => {
    renderApp()

    fireEvent.click(screen.getByTestId('policy-rules-button'))

    await waitFor(() => {
      expect(screen.getByTestId('input-return-window-damaged')).toBeInTheDocument()
    })

    const returnWindowInput = screen.getByTestId('input-return-window-damaged')
    const maxAmountInput = screen.getByTestId('input-max-amount-damaged')
    const autoApproveInput = screen.getByTestId('input-auto-approve-damaged')
    const proofCheckbox = screen.getByTestId('input-requires-proof-damaged')
    const saveBtn = screen.getByTestId('save-policy-damaged')

    fireEvent.change(returnWindowInput, { target: { value: '45' } })
    fireEvent.change(maxAmountInput, { target: { value: '750' } })
    fireEvent.change(autoApproveInput, { target: { value: '60' } })
    fireEvent.click(proofCheckbox)

    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(screen.getByTestId('success-message-damaged')).toHaveTextContent(
        /Policy rules updated successfully/i
      )
    })

    // Verify local displayed values updated
    expect(screen.getByTestId('policy-return-window-damaged')).toHaveTextContent('45 days')
    expect(screen.getByTestId('policy-max-amount-damaged')).toHaveTextContent('$750.00')
    expect(screen.getByTestId('policy-auto-approve-damaged')).toHaveTextContent('$60.00')
    expect(screen.getByTestId('policy-requires-proof-damaged')).toHaveTextContent('Yes')
  })

  it('displays error alert on server API failure without closing the modal', async () => {
    server.use(
      http.put('*/v1/policies/:category', () => {
        return HttpResponse.json(
          {
            type: 'urn:problem:validation-error',
            title: 'Validation Error',
            status: 422,
            detail: 'Server rejected update: return window exceeds maximum allowable threshold.',
          },
          { status: 422 }
        )
      })
    )

    renderApp()

    fireEvent.click(screen.getByTestId('policy-rules-button'))

    await waitFor(() => {
      expect(screen.getByTestId('save-policy-damaged')).toBeInTheDocument()
    })

    const saveBtn = screen.getByTestId('save-policy-damaged')
    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(screen.getByTestId('error-alert-damaged')).toBeInTheDocument()
      expect(screen.getByTestId('error-alert-damaged')).toHaveTextContent(
        /Server rejected update: return window exceeds maximum allowable threshold/i
      )
    })

    // Verify modal remains open
    expect(screen.getByTestId('policy-rule-viewer-modal')).toBeInTheDocument()
  })

  it('closes the modal when close button is clicked', async () => {
    renderApp()

    fireEvent.click(screen.getByTestId('policy-rules-button'))

    await waitFor(() => {
      expect(screen.getByTestId('policy-rule-viewer-modal')).toBeInTheDocument()
    })

    const closeBtn = screen.getByTestId('close-policy-modal-button')
    fireEvent.click(closeBtn)

    await waitFor(() => {
      expect(screen.queryByTestId('policy-rule-viewer-modal')).not.toBeInTheDocument()
    })
  })
})
