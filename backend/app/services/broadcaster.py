"""In-memory pub/sub event broadcaster for Server-Sent Events (SSE)."""

import asyncio
from typing import Any


class EventBroadcaster:
    """In-memory pub/sub event broadcaster supporting asynchronous subscriptions and event delivery."""

    def __init__(self, max_queue_size: int = 100) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._max_queue_size = max_queue_size

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Register a new subscriber queue and return it."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue_size)
        self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Deregister and discard a subscriber queue."""
        self._subscribers.discard(queue)

    async def publish(self, event_type: str, data: dict[str, Any]) -> int:
        """Broadcast an event payload to all active subscribers.

        Args:
            event_type: Name or category of the event (e.g. 'refund_update').
            data: Dictionary payload containing event details.

        Returns:
            Number of active subscribers that received the event.
        """
        payload = {"event": event_type, "data": data}
        delivered = 0
        subscribers = list(self._subscribers)

        stale_queues: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in subscribers:
            try:
                queue.put_nowait(payload)
                delivered += 1
            except asyncio.QueueFull:
                pass
            except Exception:
                stale_queues.append(queue)

        for sq in stale_queues:
            self._subscribers.discard(sq)

        return delivered

    @property
    def subscriber_count(self) -> int:
        """Return the current number of active subscribers."""
        return len(self._subscribers)


broadcaster = EventBroadcaster()
