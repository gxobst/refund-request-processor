import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  subscribeToRefundEvents,
  type RefundEventPayload,
} from '@/services/refundService'

export interface UseRefundEventsOptions {
  onEvent?: (event: RefundEventPayload) => void
  onError?: (error: Event) => void
  enabled?: boolean
}

export interface UseRefundEventsReturn {
  isConnected: boolean
  isFallback: boolean
  lastEvent: RefundEventPayload | null
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

  const onEventRef = React.useRef(onEvent)
  onEventRef.current = onEvent

  const onErrorRef = React.useRef(onError)
  onErrorRef.current = onError

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
  }
}
