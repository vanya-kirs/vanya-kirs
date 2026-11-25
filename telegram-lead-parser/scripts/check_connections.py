#!/usr/bin/env python3
"""
Verify all external connections before running the application.

Checks:
  1. All required environment variables are present
  2. PostgreSQL connection
  3. Redis connection
  4. Telethon authorization (prints the Telegram account username)

Usage:
    python scripts/check_connections.py
"""
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

REQUIRED_VARS = [
    "API_ID",
    "API_HASH",
    "BOT_TOKEN",
    "DATABASE_URL",
    "REDIS_URL",
    "ANTHROPIC_API_KEY",
    "SESSION_STRING",
]


def check_env() -> bool:
    """Return True if all required env vars are set."""
    from pydantic import ValidationError

    try:
        from app.core.config import Settings
        Settings()
        logger.info("[ENV]       OK — all required variables present")
        return True
    except ValidationError as exc:
        missing = [e["loc"][0] for e in exc.errors() if e["type"] == "missing"]
        logger.error("[ENV]       FAIL — missing variables: %s", missing)
        return False
    except Exception as exc:
        logger.error("[ENV]       FAIL — %s", exc)
        return False


async def check_postgres() -> bool:
    """Return True if a SELECT 1 succeeds."""
    try:
        from sqlalchemy import text
        from app.core.database import engine

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("[PostgreSQL] OK — connection successful")
        return True
    except Exception as exc:
        logger.error("[PostgreSQL] FAIL — %s", exc)
        return False


async def check_redis() -> bool:
    """Return True if Redis PING succeeds."""
    try:
        import redis.asyncio as aioredis
        from app.core.config import get_settings

        settings = get_settings()
        client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=5)
        await client.ping()
        await client.aclose()
        logger.info("[Redis]      OK — connection successful")
        return True
    except Exception as exc:
        logger.error("[Redis]      FAIL — %s", exc)
        return False


async def check_telethon() -> bool:
    """Return True if Telethon can authorize and retrieve account info."""
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from app.core.config import get_settings

        settings = get_settings()
        client = TelegramClient(
            StringSession(settings.SESSION_STRING),
            settings.API_ID,
            settings.API_HASH,
        )
        await client.connect()
        if not await client.is_user_authorized():
            logger.error("[Telethon]   FAIL — session is not authorized")
            await client.disconnect()
            return False

        me = await client.get_me()
        username = f"@{me.username}" if me.username else str(me.id)
        logger.info("[Telethon]   OK — authorized as %s", username)
        await client.disconnect()
        return True
    except Exception as exc:
        logger.error("[Telethon]   FAIL — %s", exc)
        return False


async def main() -> None:
    print("\n=== Telegram Lead Parser — Connection Check ===\n")

    results = {
        "ENV": check_env(),
        "PostgreSQL": await check_postgres(),
        "Redis": await check_redis(),
        "Telethon": await check_telethon(),
    }

    print("\n=== Summary ===")
    all_ok = True
    for name, ok in results.items():
        status = "OK" if ok else "FAIL"
        print(f"  {name:<12} {status}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        logger.info("All checks passed. Ready to run Phase 2!")
        sys.exit(0)
    else:
        logger.error("Some checks failed. Fix the issues above before proceeding.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
