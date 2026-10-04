import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { subscribeToRefundEvents, type RefundEventPayload } from '@/services/refundService'
import { useRefundEvents } from '@/hooks/useRefundEvents'
import { Header } from '@/components/layout/Header'
import { App } from '@/App'

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
    // Simulate async connection open
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

describe('Server-Sent Events (SSE) real-time updates', () => {
  const originalEventSource = globalThis.EventSource

  beforeEach(() => {
    MockEventSource.instances = []
    // @ts-expect-error Mocking global EventSource
    globalThis.EventSource = MockEventSource
  })

  afterEach(() => {
    globalThis.EventSource = originalEventSource
    vi.restoreAllMocks()
  })

  describe('subscribeToRefundEvents service', () => {
    it('connects to /v1/refunds/events endpoint', () => {
      const onEvent = vi.fn()
      const unsubscribe = subscribeToRefundEvents(onEvent)

      expect(MockEventSource.instances).toHaveLength(1)
      expect(MockEventSource.instances[0].url).toContain('/v1/refunds/events')

      unsubscribe()
      expect(MockEventSource.instances[0].close).toHaveBeenCalledTimes(1)
    })

    it('receives and parses refund_update events', () => {
      const onEvent = vi.fn()
      const unsubscribe = subscribeToRefundEvents(onEvent)
      const instance = MockEventSource.instances[0]

      const samplePayload: RefundEventPayload = {
        refund_id: 'ref_sse_1',
        order_id: 'ORD-1001',
        status: 'pending',
      }

      instance.emit('refund_update', samplePayload)

      expect(onEvent).toHaveBeenCalledWith(samplePayload)
      unsubscribe()
    })

    it('invokes onError on EventSource connection error', () => {
      const onEvent = vi.fn()
      const onError = vi.fn()
      const unsubscribe = subscribeToRefundEvents(onEvent, onError)
      const instance = MockEventSource.instances[0]

      const err = new Event('error')
      instance.emitError(err)

      expect(onError).toHaveBeenCalledWith(err)
      unsubscribe()
    })
  })

  describe('useRefundEvents hook', () => {
    function TestHookComponent({ onEvent }: { onEvent?: (e: RefundEventPayload) => void }) {
      const { isConnected, isFallback, lastEvent } = useRefundEvents({ onEvent })
      return (
        <div>
          <span data-testid="status">
            {isConnected ? 'connected' : isFallback ? 'fallback' : 'idle'}
          </span>
          <span data-testid="last-refund-id">{lastEvent?.refund_id || 'none'}</span>
        </div>
      )
    }

    it('tracks connection state and transitions to connected upon open', async () => {
      const queryClient = new QueryClient()

      render(
        <QueryClientProvider client={queryClient}>
          <TestHookComponent />
        </QueryClientProvider>
      )

      expect(screen.getByTestId('status')).toHaveTextContent(/idle|connected/)
      await waitFor(() => {
        expect(screen.getByTestId('status')).toHaveTextContent('connected')
      })
    })

    it('invalidates ["refunds"] and ["refund", refundId] on refund_update', async () => {
      const queryClient = new QueryClient()
      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

      render(
        <QueryClientProvider client={queryClient}>
          <TestHookComponent />
        </QueryClientProvider>
      )

      await waitFor(() => {
        expect(MockEventSource.instances).toHaveLength(1)
      })

      const instance = MockEventSource.instances[0]
      act(() => {
        instance.emit('refund_update', {
          refund_id: 'ref_inv_99',
          status: 'completed',
          decision: 'auto_approve',
        })
      })

      await waitFor(() => {
        expect(screen.getByTestId('last-refund-id')).toHaveTextContent('ref_inv_99')
      })

      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['refunds'] })
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['refund', 'ref_inv_99'] })
    })

    it('transitions to fallback mode on connection error', async () => {
      const queryClient = new QueryClient()

      render(
        <QueryClientProvider client={queryClient}>
          <TestHookComponent />
        </QueryClientProvider>
      )

      await waitFor(() => {
        expect(screen.getByTestId('status')).toHaveTextContent('connected')
      })

      const instance = MockEventSource.instances[0]
      act(() => {
        instance.emitError()
      })

      await waitFor(() => {
        expect(screen.getByTestId('status')).toHaveTextContent('fallback')
      })
    })

    it('falls back cleanly when EventSource is not supported', async () => {
      // @ts-expect-error simulate unsupported browser environment
      delete globalThis.EventSource

      const queryClient = new QueryClient()

      render(
        <QueryClientProvider client={queryClient}>
          <TestHookComponent />
        </QueryClientProvider>
      )

      expect(screen.getByTestId('status')).toHaveTextContent('fallback')
    })

    it('cleans up and closes EventSource when unmounted', async () => {
      const queryClient = new QueryClient()

      const { unmount } = render(
        <QueryClientProvider client={queryClient}>
          <TestHookComponent />
        </QueryClientProvider>
      )

      await waitFor(() => {
        expect(MockEventSource.instances).toHaveLength(1)
      })

      const instance = MockEventSource.instances[0]
      unmount()

      expect(instance.close).toHaveBeenCalledTimes(1)
    })
  })

  describe('Header and App component live indicator', () => {
    it('Header displays "Live - SSE connected" when sseConnected is true', () => {
      render(<Header sseConnected={true} />)

      const status = screen.getByTestId('polling-status')
      expect(status).toHaveTextContent(/Live - SSE connected/i)
    })

    it('Header falls back to polling indicator when sseConnected is false and isPolling is true', () => {
      render(<Header sseConnected={false} isPolling={true} pollingIntervalSeconds={3} />)

      const status = screen.getByTestId('polling-status')
      expect(status).toHaveTextContent(/Live - polling every 3s/i)
    })

    it('App displays "Live - SSE connected" indicator when EventSource connects', async () => {
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      })

      render(<App client={queryClient} />)

      await waitFor(() => {
        const pollingStatus = screen.getByTestId('polling-status')
        expect(pollingStatus).toHaveTextContent(/Live - SSE connected/i)
      })
    })
  })
})
