import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_CHANNEL = "source:added"


async def publish_source_added(redis_url: str, source_id: int, url: str, user_id: int) -> None:
    """Publish a source-added event so the listener picks it up immediately."""
    r = aioredis.from_url(redis_url)
    try:
        payload = json.dumps({"source_id": source_id, "url": url, "user_id": user_id})
        await r.publish(_CHANNEL, payload)
        logger.info(
            "publish_source_added: source_id=%d url=%s user_id=%d", source_id, url, user_id
        )
    finally:
        await r.aclose()


SourceAddedCallback = Callable[[int, str, int], Coroutine[Any, Any, None]]


class SourceSyncSubscriber:
    """
    Subscribes to the Redis `source:added` channel and calls `on_source_added`
    whenever a new source is published.
    """

    def __init__(self, redis_url: str, on_source_added: SourceAddedCallback) -> None:
        self._redis_url = redis_url
        self._on_source_added = on_source_added
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._listen(), name="source-sync-subscriber")

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def _listen(self) -> None:
        while True:
            try:
                r = aioredis.from_url(self._redis_url)
                async with r.pubsub() as pubsub:
                    await pubsub.subscribe(_CHANNEL)
                    logger.info("SourceSyncSubscriber: subscribed to %s", _CHANNEL)
                    async for message in pubsub.listen():
                        if message["type"] != "message":
                            continue
                        try:
                            data = json.loads(message["data"])
                            await self._on_source_added(
                                data["source_id"], data["url"], data["user_id"]
                            )
                        except Exception as exc:
                            logger.error("SourceSyncSubscriber: parse error: %s", exc)
            except asyncio.CancelledError:
                logger.info("SourceSyncSubscriber: stopped")
                return
            except Exception as exc:
                logger.error("SourceSyncSubscriber: connection error: %s — retrying in 5s", exc)
                await asyncio.sleep(5)
