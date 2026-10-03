import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  subscribeToRefundEvents,
  type RefundEventPayload,
  type PolicyEventPayload,
} from '@/services/refundService'

export interface UseRefundEventsOptions {
  onEvent?: (event: RefundEventPayload) => void
  onError?: (error: Event) => void
  onPolicyEvent?: (event: PolicyEventPayload) => void
  enabled?: boolean
}

export interface UseRefundEventsReturn {
  isConnected: boolean
  isFallback: boolean
  lastEvent: RefundEventPayload | null
  lastPolicyEvent?: PolicyEventPayload | null
}

/**
 * Custom React hook subscribing to real-time refund server-sent events (SSE).
 *
 * Automatically invalidates ['refunds'] and ['refund', refundId] query caches upon receiving
 * refund_update events. Gracefully degrades to fallback mode when EventSource is unavailable
 * or experiences connection failures.
 */
export function useRefundEvents(options: UseRefundEventsOptions = {}): UseRefundEventsReturn {
  const { onEvent, onError, enabled = true } = options
  const queryClient = useQueryClient()

  const isEventSourceSupported =
    typeof window !== 'undefined' && typeof EventSource !== 'undefined'

  const [isConnected, setIsConnected] = React.useState<boolean>(false)
  const [isFallback, setIsFallback] = React.useState<boolean>(!isEventSourceSupported)
  const [lastEvent, setLastEvent] = React.useState<RefundEventPayload | null>(null)
  const [lastPolicyEvent, setLastPolicyEvent] = React.useState<PolicyEventPayload | null>(null)

  const onEventRef = React.useRef(onEvent)
  onEventRef.current = onEvent

  const onErrorRef = React.useRef(onError)
  onErrorRef.current = onError

  const onPolicyEventRef = React.useRef(options.onPolicyEvent)
  onPolicyEventRef.current = options.onPolicyEvent

  React.useEffect(() => {
    if (!enabled) {
      setIsConnected(false)
      setIsFallback(false)
      return
    }

    if (typeof window === 'undefined' || typeof EventSource === 'undefined') {
      setIsConnected(false)
      setIsFallback(true)
      return
    }

    const unsubscribe = subscribeToRefundEvents(
      (event: RefundEventPayload) => {
        setIsConnected(true)
        setIsFallback(false)
        setLastEvent(event)

        // Invalidate active refund queue listings
        queryClient.invalidateQueries({ queryKey: ['refunds'] })

        // Invalidate specific refund record if refund ID is present
        const refundId = event.refund_id || event.refundId
        if (refundId) {
          queryClient.invalidateQueries({ queryKey: ['refund', refundId] })
        }

        onEventRef.current?.(event)
      },
      (error: Event) => {
        setIsConnected(false)
        setIsFallback(true)
        onErrorRef.current?.(error)
      },
      () => {
        // Connection opened or initial ping received
        setIsConnected(true)
        setIsFallback(false)
      },
      (policyEvent: PolicyEventPayload) => {
        setIsConnected(true)
        setIsFallback(false)
        setLastPolicyEvent(policyEvent)

        // Automatically invalidate the TanStack Query cache for query key ['policies']
        queryClient.invalidateQueries({ queryKey: ['policies'] })

        onPolicyEventRef.current?.(policyEvent)
      }
    )

    return () => {
      unsubscribe()
      setIsConnected(false)
    }
  }, [enabled, queryClient])

  return {
    isConnected,
    isFallback,
    lastEvent,
    lastPolicyEvent,
  }
}
