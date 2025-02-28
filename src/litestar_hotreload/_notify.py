import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class Notify:
    def __init__(self) -> None:
        self._broadcast = _MemoryBroadcast()

    async def notify(self) -> None:
        logger.debug("Notifying clients to reload")
        await self._broadcast.publish("reload")

    async def watch(self) -> AsyncIterator[None]:
        logger.debug("Watching for reload events")
        async with self._broadcast.subscribe() as subscription:
            async for _ in subscription:
                logger.debug("Received reload event")
                yield


class _MemoryBroadcast:
    """A basic in-memory pub/sub helper."""

    class Subscription:
        def __init__(self, queue: asyncio.Queue) -> None:
            self._queue = queue

        async def __aiter__(self) -> AsyncIterator[str]:
            while True:
                yield await self._queue.get()

    def __init__(self) -> None:
        self._subscriptions: set[asyncio.Queue] = set()

    async def publish(self, event: str) -> None:
        logger.debug(
            f"Broadcasting event: {event} subscribers: {len(self._subscriptions)}"
        )
        for queue in self._subscriptions:
            await queue.put(event)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator["Subscription"]:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscriptions.add(queue)
        try:
            yield self.Subscription(queue)
        finally:
            self._subscriptions.remove(queue)
            await queue.put(None)
