import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import { PolicyRuleViewerModal } from '@/components/admin/PolicyRuleViewerModal'
import type { PolicyRule, PolicyAuditEntry } from '@/services/policyService'

const MOCK_POLICIES: PolicyRule[] = [
  {
    category: 'damaged',
    return_window_days: 45,
    max_refund_amount: 750.0,
    auto_approve_threshold: 0.0,
    requires_proof: false,
    eligible_delivery_statuses: ['delivered'],
    refund_window_days: 45,
    max_order_amount: 750.0,
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
]

const MOCK_AUDIT_HISTORY: PolicyAuditEntry[] = [
  {
    audit_id: 'audit_1001',
    category: 'damaged',
    timestamp: '2026-10-03T14:30:00Z',
    operator_id: 'operator-alice',
    changes: {
      return_window_days: { old_value: 30, new_value: 45 },
      max_refund_amount: { old_value: 500.0, new_value: 750.0 },
    },
    previous_state: {
      category: 'damaged',
      return_window_days: 30,
      max_refund_amount: 500.0,
      auto_approve_threshold: 0.0,
      requires_proof: false,
      eligible_delivery_statuses: ['delivered'],
    },
    action: 'update',
  },
  {
    audit_id: 'audit_1002',
    category: 'wrong_item',
    timestamp: '2026-10-03T13:00:00Z',
    operator_id: 'supervisor-bob',
    changes: {
      auto_approve_threshold: { old_value: 0.0, new_value: 50.0 },
    },
    previous_state: {
      category: 'wrong_item',
      return_window_days: 30,
      max_refund_amount: 1000.0,
      auto_approve_threshold: 0.0,
      requires_proof: false,
      eligible_delivery_statuses: ['delivered'],
    },
    action: 'update',
  },
]

function renderModal(queryClient?: QueryClient, onClose = vi.fn()) {
  const client =
    queryClient ||
    new QueryClient({
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

  return {
    ...render(
      <QueryClientProvider client={client}>
        <PolicyRuleViewerModal isOpen={true} onClose={onClose} />
      </QueryClientProvider>
    ),
    queryClient: client,
  }
}

describe('Policy Version History and Audit Log Rollback Integration Tests', () => {
  let auditHistory: PolicyAuditEntry[]
  let activePolicies: PolicyRule[]

  beforeEach(() => {
    auditHistory = JSON.parse(JSON.stringify(MOCK_AUDIT_HISTORY))
    activePolicies = JSON.parse(JSON.stringify(MOCK_POLICIES))

    server.use(
      http.get('*/v1/policies', () => {
        return HttpResponse.json(activePolicies, { status: 200 })
      }),
      http.get('*/v1/policies/history', ({ request }) => {
        const url = new URL(request.url)
        const categoryParam = url.searchParams.get('category')
        if (categoryParam) {
          const filtered = auditHistory.filter((e) => e.category === categoryParam)
          return HttpResponse.json(filtered, { status: 200 })
        }
        return HttpResponse.json(auditHistory, { status: 200 })
      }),
      http.post('*/v1/policies/:category/rollback', async ({ params, request }) => {
        const { category } = params as { category: string }
        const url = new URL(request.url)
        let auditId = url.searchParams.get('audit_id')

        try {
          const body = (await request.json()) as { audit_id?: string }
          if (body?.audit_id) auditId = body.audit_id
        } catch {
          // ignore empty body
        }

        const categoryEntries = auditHistory.filter((e) => e.category === category)
        if (categoryEntries.length === 0) {
          return HttpResponse.json(
            {
              type: 'urn:problem:not-found',
              title: 'Not Found',
              status: 404,
              detail: `No audit history found for category '${category}' to rollback`,
            },
            { status: 404 }
          )
        }

        const targetEntry = auditId
          ? categoryEntries.find((e) => e.audit_id === auditId)
          : categoryEntries[categoryEntries.length - 1]

        if (!targetEntry) {
          return HttpResponse.json(
            {
              type: 'urn:problem:not-found',
              title: 'Not Found',
              status: 404,
              detail: `Audit entry '${auditId}' not found for rollback`,
            },
            { status: 404 }
          )
        }

        const restoredPolicy: PolicyRule = {
          category,
          return_window_days: (targetEntry.previous_state.return_window_days as number) || 30,
          max_refund_amount: (targetEntry.previous_state.max_refund_amount as number) || 500,
          auto_approve_threshold: (targetEntry.previous_state.auto_approve_threshold as number) || 0,
          requires_proof: Boolean(targetEntry.previous_state.requires_proof),
          eligible_delivery_statuses: (targetEntry.previous_state.eligible_delivery_statuses as string[]) || ['delivered'],
        }

        const rollbackEntry: PolicyAuditEntry = {
          audit_id: `audit_rollback_${Date.now()}`,
          category,
          timestamp: new Date().toISOString(),
          operator_id: 'supervisor',
          changes: {
            return_window_days: {
              old_value: 45,
              new_value: restoredPolicy.return_window_days,
            },
          },
          previous_state: targetEntry.previous_state,
          action: 'rollback',
        }
        auditHistory.unshift(rollbackEntry)

        return HttpResponse.json(restoredPolicy, { status: 200 })
      })
    )
  })

  it('allows operators to switch between Active Policies and Version History tabs', async () => {
    renderModal()

    const activeTab = screen.getByTestId('tab-active-policies')
    const historyTab = screen.getByTestId('tab-policy-history')
    expect(activeTab).toBeInTheDocument()
    expect(historyTab).toBeInTheDocument()

    // Default tab is Active Policies
    await waitFor(() => {
      expect(screen.getByTestId('policy-card-damaged')).toBeInTheDocument()
    })

    // Switch to Version History tab
    fireEvent.click(historyTab)

    await waitFor(() => {
      expect(screen.getByTestId('history-category-filter')).toBeInTheDocument()
      expect(screen.queryByTestId('policy-card-damaged')).not.toBeInTheDocument()
    })

    // Switch back to Active Policies tab
    fireEvent.click(activeTab)

    await waitFor(() => {
      expect(screen.getByTestId('policy-card-damaged')).toBeInTheDocument()
      expect(screen.queryByTestId('history-category-filter')).not.toBeInTheDocument()
    })
  })

  it('renders audit entries with category badges, timestamps, operators, and field diffs', async () => {
    renderModal()

    fireEvent.click(screen.getByTestId('tab-policy-history'))

    await waitFor(() => {
      expect(screen.getByTestId('audit-history-list')).toBeInTheDocument()
    })

    // Check entry 1 details
    expect(screen.getByTestId('audit-category-audit_1001')).toHaveTextContent('Damaged Item')
    expect(screen.getByTestId('audit-timestamp-audit_1001')).toHaveTextContent('2026-10-03T14:30:00Z')
    expect(screen.getByTestId('audit-operator-audit_1001')).toHaveTextContent('operator-alice')

    const diffs1 = screen.getByTestId('audit-diffs-audit_1001')
    expect(diffs1).toHaveTextContent('return_window_days:')
    expect(diffs1).toHaveTextContent('30')
    expect(diffs1).toHaveTextContent('45')
    expect(diffs1).toHaveTextContent('max_refund_amount:')
    expect(diffs1).toHaveTextContent('500')
    expect(diffs1).toHaveTextContent('750')

    expect(screen.getByTestId('rollback-button-audit_1001')).toBeInTheDocument()

    // Check entry 2 details
    expect(screen.getByTestId('audit-category-audit_1002')).toHaveTextContent('Wrong Item')
    expect(screen.getByTestId('audit-operator-audit_1002')).toHaveTextContent('supervisor-bob')
    const diffs2 = screen.getByTestId('audit-diffs-audit_1002')
    expect(diffs2).toHaveTextContent('auto_approve_threshold:')
  })

  it('displays empty state when audit history is empty', async () => {
    server.use(
      http.get('*/v1/policies/history', () => {
        return HttpResponse.json([], { status: 200 })
      })
    )

    renderModal()
    fireEvent.click(screen.getByTestId('tab-policy-history'))

    await waitFor(() => {
      expect(screen.getByTestId('audit-empty-state')).toBeInTheDocument()
      expect(screen.getByTestId('audit-empty-state')).toHaveTextContent(
        /No policy version history found/i
      )
    })
  })

  it('filters audit history by category using the category selector', async () => {
    renderModal()
    fireEvent.click(screen.getByTestId('tab-policy-history'))

    await waitFor(() => {
      expect(screen.getByTestId('history-category-filter')).toBeInTheDocument()
    })

    const filterSelect = screen.getByTestId('history-category-filter')

    // Filter by damaged
    fireEvent.change(filterSelect, { target: { value: 'damaged' } })

    await waitFor(() => {
      expect(screen.getByTestId('audit-entry-audit_1001')).toBeInTheDocument()
      expect(screen.queryByTestId('audit-entry-audit_1002')).not.toBeInTheDocument()
    })

    // Filter by wrong_item
    fireEvent.change(filterSelect, { target: { value: 'wrong_item' } })

    await waitFor(() => {
      expect(screen.getByTestId('audit-entry-audit_1002')).toBeInTheDocument()
      expect(screen.queryByTestId('audit-entry-audit_1001')).not.toBeInTheDocument()
    })
  })

  it('rolls back a policy when clicking Rollback, invalidating query caches and showing success notification', async () => {
    const testClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false, gcTime: 0 },
        mutations: { retry: false },
      },
    })
    const invalidateSpy = vi.spyOn(testClient, 'invalidateQueries')

    renderModal(testClient)
    fireEvent.click(screen.getByTestId('tab-policy-history'))

    await waitFor(() => {
      expect(screen.getByTestId('rollback-button-audit_1001')).toBeInTheDocument()
    })

    const rollbackBtn = screen.getByTestId('rollback-button-audit_1001')
    fireEvent.click(rollbackBtn)

    await waitFor(() => {
      expect(screen.getByTestId('policy-success-toast')).toBeInTheDocument()
      expect(screen.getByTestId('policy-success-toast')).toHaveTextContent(
        /Policy restored to previous state successfully/i
      )
    })

    // Query caches invalidated
    expect(invalidateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: ['policies'] })
    )
    expect(invalidateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: ['policies', 'history'] })
    )
  })

  it('displays an error alert when rollback fails', async () => {
    server.use(
      http.post('*/v1/policies/:category/rollback', () => {
        return HttpResponse.json(
          {
            type: 'urn:problem:not-found',
            title: 'Not Found',
            status: 404,
            detail: 'Target audit entry not found for rollback.',
          },
          { status: 404 }
        )
      })
    )

    renderModal()
    fireEvent.click(screen.getByTestId('tab-policy-history'))

    await waitFor(() => {
      expect(screen.getByTestId('rollback-button-audit_1001')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('rollback-button-audit_1001'))

    await waitFor(() => {
      expect(screen.getByTestId('policy-error-alert')).toBeInTheDocument()
      expect(screen.getByTestId('policy-error-alert')).toHaveTextContent(
        /Target audit entry not found for rollback/i
      )
    })
  })
})
