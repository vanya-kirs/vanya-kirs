import asyncio
import logging
import time

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_HEALTH_KEY = "listener:health"
_HEARTBEAT_INTERVAL = 60   # seconds between writes
_KEY_TTL = 120             # Redis TTL — if missed 2 beats, considered dead


class ListenerHealthCheck:
    """
    Writes a heartbeat to Redis every 60 seconds.
    The API reads this key to report listener status.
    TTL of 120s means the key expires if two beats are missed.
    """

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="listener-health")

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def _run(self) -> None:
        r = aioredis.from_url(self._redis_url)
        try:
            while True:
                try:
                    await r.set(_HEALTH_KEY, int(time.time()), ex=_KEY_TTL)
                    logger.debug("ListenerHealthCheck: heartbeat written")
                except Exception as exc:
                    logger.warning("ListenerHealthCheck: redis error: %s", exc)
                await asyncio.sleep(_HEARTBEAT_INTERVAL)
        except asyncio.CancelledError:
            logger.info("ListenerHealthCheck: stopped")
        finally:
            await r.aclose()


async def get_listener_status(redis_url: str) -> dict:
    """Read listener health from Redis. Used by the stats API."""
    r = aioredis.from_url(redis_url)
    try:
        val = await r.get(_HEALTH_KEY)
        if val is None:
            return {"status": "offline", "last_heartbeat_at": None}
        return {"status": "online", "last_heartbeat_at": int(val)}
    except Exception as exc:
        logger.warning("get_listener_status: redis error: %s", exc)
        return {"status": "unknown", "last_heartbeat_at": None}
    finally:
        await r.aclose()
