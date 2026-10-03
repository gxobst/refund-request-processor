import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import {
  subscribeToRefundEvents,
  type PolicyEventPayload,
} from '@/services/refundService'
import { useRefundEvents } from '@/hooks/useRefundEvents'
import { PolicyRuleViewerModal } from '@/components/admin/PolicyRuleViewerModal'
import { App } from '@/App'
import type { PolicyRule } from '@/services/policyService'

class MockEventSource {
  static instances: MockEventSource[] = []
  url: string
  listeners: Record<string, ((e: unknown) => void)[]> = {}
  onopen: (() => void) | null = null
  onerror: ((err: unknown) => void) | null = null
  onmessage: ((msg: unknown) => void) | null = null
  readyState = 0

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
    setTimeout(() => {
      this.readyState = 1
      this.onopen?.()
    }, 0)
  }

  addEventListener(event: string, cb: (e: unknown) => void) {
    if (!this.listeners[event]) {
      this.listeners[event] = []
    }
    this.listeners[event].push(cb)
  }

  removeEventListener(event: string, cb: (e: unknown) => void) {
    if (!this.listeners[event]) return
    this.listeners[event] = this.listeners[event].filter((l) => l !== cb)
  }

  emit(event: string, data: unknown) {
    const payload = typeof data === 'string' ? data : JSON.stringify(data)
    const evt = { data: payload }
    this.listeners[event]?.forEach((cb) => cb(evt))
    if (event === 'message') {
      this.onmessage?.(evt)
    }
  }

  emitError(err: unknown = new Event('error')) {
    this.onerror?.(err)
  }

  close = vi.fn(() => {
    this.readyState = 2
  })
}

const INITIAL_POLICIES: PolicyRule[] = [
  {
    category: 'damaged',
    return_window_days: 30,
    max_refund_amount: 500.0,
    auto_approve_threshold: 50.0,
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

describe('Real-Time Policy SSE Updates Integration Tests', () => {
  const originalEventSource = globalThis.EventSource
  let activePolicies: PolicyRule[]

  beforeEach(() => {
    MockEventSource.instances = []
    // @ts-expect-error Mocking global EventSource
    globalThis.EventSource = MockEventSource
    activePolicies = JSON.parse(JSON.stringify(INITIAL_POLICIES))

    server.use(
      http.get('*/v1/policies', () => {
        return HttpResponse.json(activePolicies, { status: 200 })
      }),
      http.put('*/v1/policies/:category', async ({ params, request }) => {
        const { category } = params as { category: string }
        const index = activePolicies.findIndex((p) => p.category === category)
        if (index === -1) {
          return HttpResponse.json({ detail: 'Category not found' }, { status: 404 })
        }
        const body = (await request.json()) as Partial<PolicyRule>
        activePolicies[index] = { ...activePolicies[index], ...body }
        return HttpResponse.json(activePolicies[index], { status: 200 })
      })
    )
  })

  afterEach(() => {
    globalThis.EventSource = originalEventSource
    vi.restoreAllMocks()
  })

  describe('subscribeToRefundEvents policy_update handling', () => {
    it('listens for policy_update and invokes onPolicyEvent with parsed payload', () => {
      const onEvent = vi.fn()
      const onPolicyEvent = vi.fn()
      const unsubscribe = subscribeToRefundEvents(onEvent, undefined, undefined, onPolicyEvent)

      expect(MockEventSource.instances).toHaveLength(1)
      const instance = MockEventSource.instances[0]

      const payload: PolicyEventPayload = {
        category: 'damaged',
        return_window_days: 45,
        max_refund_amount: 750.0,
        auto_approve_threshold: 100.0,
        requires_proof: true,
        eligible_delivery_statuses: ['delivered'],
        refund_window_days: 45,
        max_order_amount: 750.0,
      }

      instance.emit('policy_update', payload)

      expect(onPolicyEvent).toHaveBeenCalledWith(payload)
      unsubscribe()
      expect(instance.close).toHaveBeenCalledTimes(1)
    })

    it('falls back to onEvent when onPolicyEvent is omitted', () => {
      const onEvent = vi.fn()
      const unsubscribe = subscribeToRefundEvents(onEvent)
      const instance = MockEventSource.instances[0]

      const payload: PolicyEventPayload = {
        category: 'changed_mind',
        return_window_days: 21,
        max_refund_amount: 350.0,
        auto_approve_threshold: 25.0,
        requires_proof: false,
        eligible_delivery_statuses: ['delivered'],
      }

      instance.emit('policy_update', payload)

      expect(onEvent).toHaveBeenCalledWith(payload)
      unsubscribe()
    })
  })

  describe('useRefundEvents hook policy_update cache invalidation', () => {
    function HookTestComponent({
      onPolicyEvent,
    }: {
      onPolicyEvent?: (e: PolicyEventPayload) => void
    }) {
      const { lastPolicyEvent, isConnected } = useRefundEvents({ onPolicyEvent })
      return (
        <div>
          <span data-testid="hook-status">{isConnected ? 'connected' : 'disconnected'}</span>
          <span data-testid="last-policy-cat">{lastPolicyEvent?.category || 'none'}</span>
        </div>
      )
    }

    it('invalidates ["policies"] query cache upon receiving policy_update event', async () => {
      const queryClient = new QueryClient()
      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

      render(
        <QueryClientProvider client={queryClient}>
          <HookTestComponent />
        </QueryClientProvider>
      )

      await waitFor(() => {
        expect(MockEventSource.instances).toHaveLength(1)
      })

      const instance = MockEventSource.instances[0]
      const eventPayload: PolicyEventPayload = {
        category: 'damaged',
        return_window_days: 45,
        max_refund_amount: 850.0,
        auto_approve_threshold: 120.0,
        requires_proof: true,
        eligible_delivery_statuses: ['delivered'],
      }

      act(() => {
        instance.emit('policy_update', eventPayload)
      })

      await waitFor(() => {
        expect(screen.getByTestId('last-policy-cat')).toHaveTextContent('damaged')
      })

      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['policies'] })
    })
  })

  describe('PolicyRuleViewerModal real-time updates via SSE in App', () => {
    it('dynamically updates category cards and input fields in real time when policy_update arrives', async () => {
      const queryClient = new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            gcTime: 0,
          },
        },
      })

      render(
        <QueryClientProvider client={queryClient}>
          <App client={queryClient} />
        </QueryClientProvider>
      )

      await waitFor(() => {
        expect(MockEventSource.instances).toHaveLength(1)
      })

      // Open the Policy Rules modal
      const policyRulesBtn = screen.getByTestId('policy-rules-button')
      fireEvent.click(policyRulesBtn)

      // Verify modal is open and displays initial 'damaged' policy values
      await waitFor(() => {
        expect(screen.getByTestId('policy-rule-viewer-modal')).toBeInTheDocument()
        expect(screen.getByTestId('policy-return-window-damaged')).toHaveTextContent('30 days')
        expect(screen.getByTestId('policy-max-amount-damaged')).toHaveTextContent('$500.00')
        expect(screen.getByTestId('policy-auto-approve-damaged')).toHaveTextContent('$50.00')
        expect(screen.getByTestId('policy-requires-proof-damaged')).toHaveTextContent('No')
      })

      // Verify initial input values
      const returnWindowInput = screen.getByTestId('input-return-window-damaged') as HTMLInputElement
      const maxAmountInput = screen.getByTestId('input-max-amount-damaged') as HTMLInputElement
      const autoApproveInput = screen.getByTestId('input-auto-approve-damaged') as HTMLInputElement
      const requiresProofInput = screen.getByTestId('input-requires-proof-damaged') as HTMLInputElement

      expect(returnWindowInput.value).toBe('30')
      expect(maxAmountInput.value).toBe('500')
      expect(autoApproveInput.value).toBe('50')
      expect(requiresProofInput.checked).toBe(false)

      // Update simulated backend data store
      const updatedDamaged: PolicyRule = {
        category: 'damaged',
        return_window_days: 45,
        max_refund_amount: 800.0,
        auto_approve_threshold: 150.0,
        requires_proof: true,
        eligible_delivery_statuses: ['delivered'],
        refund_window_days: 45,
        max_order_amount: 800.0,
      }
      activePolicies = activePolicies.map((p) =>
        p.category === 'damaged' ? updatedDamaged : p
      )

      // Emit SSE policy_update event from server
      const instance = MockEventSource.instances[0]
      act(() => {
        instance.emit('policy_update', updatedDamaged)
      })

      // Verify displayed summary values update in real time without manual reload
      await waitFor(() => {
        expect(screen.getByTestId('policy-return-window-damaged')).toHaveTextContent('45 days')
        expect(screen.getByTestId('policy-max-amount-damaged')).toHaveTextContent('$800.00')
        expect(screen.getByTestId('policy-auto-approve-damaged')).toHaveTextContent('$150.00')
        expect(screen.getByTestId('policy-requires-proof-damaged')).toHaveTextContent('Yes')
      })

      // Verify form input fields also synchronize dynamically with the new values
      await waitFor(() => {
        expect(returnWindowInput.value).toBe('45')
        expect(maxAmountInput.value).toBe('800')
        expect(autoApproveInput.value).toBe('150')
        expect(requiresProofInput.checked).toBe(true)
      })
    })

    it('dynamically updates another category (late_delivery) when policy_update arrives', async () => {
      const queryClient = new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            gcTime: 0,
          },
        },
      })

      function StandaloneViewer() {
        useRefundEvents()
        return <PolicyRuleViewerModal isOpen={true} onClose={() => {}} />
      }

      render(
        <QueryClientProvider client={queryClient}>
          <StandaloneViewer />
        </QueryClientProvider>
      )

      await waitFor(() => {
        expect(screen.getByTestId('policy-return-window-late_delivery')).toHaveTextContent('14 days')
        expect(screen.getByTestId('policy-max-amount-late_delivery')).toHaveTextContent('$300.00')
      })

      const updatedLateDelivery: PolicyRule = {
        category: 'late_delivery',
        return_window_days: 28,
        max_refund_amount: 450.0,
        auto_approve_threshold: 75.0,
        requires_proof: true,
        eligible_delivery_statuses: ['in_transit', 'delivered'],
        refund_window_days: 28,
        max_order_amount: 450.0,
      }
      activePolicies = activePolicies.map((p) =>
        p.category === 'late_delivery' ? updatedLateDelivery : p
      )

      const instance = MockEventSource.instances[0]
      act(() => {
        instance.emit('policy_update', updatedLateDelivery)
      })

      await waitFor(() => {
        expect(screen.getByTestId('policy-return-window-late_delivery')).toHaveTextContent('28 days')
        expect(screen.getByTestId('policy-max-amount-late_delivery')).toHaveTextContent('$450.00')
        expect(screen.getByTestId('policy-auto-approve-late_delivery')).toHaveTextContent('$75.00')
        expect(screen.getByTestId('policy-requires-proof-late_delivery')).toHaveTextContent('Yes')
      })
    })
  })
})
