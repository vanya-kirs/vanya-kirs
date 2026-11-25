#!/usr/bin/env python3
"""
Parse messages from a Telegram chat WITHOUT saving to DB.
Use to verify that TelethonClient works correctly.

Usage:
    python scripts/test_parser.py --url @somegroup --limit 50
"""
import argparse
import asyncio
import logging

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.parser.client import TelethonClient

setup_logging()
logger = logging.getLogger(__name__)


async def main(url: str, limit: int) -> None:
    settings = get_settings()

    logger.info("Connecting to Telegram...")
    async with TelethonClient(
        api_id=settings.API_ID,
        api_hash=settings.API_HASH,
        session_string=settings.SESSION_STRING,
    ) as client:
        logger.info("Validating source: %s", url)
        validation = await client.validate_source(url)
        if not validation.is_valid:
            logger.error("Source is not valid: %s", validation.error)
            return

        logger.info(
            "Source OK — title=%r members=%s", validation.title, validation.members_count
        )

        logger.info("Scraping up to %d messages...", limit)
        messages = await client.scrape_messages(url, limit=limit)
        logger.info("Scraped %d messages. Enriching with bio...", len(messages))

        messages = await client.enrich_messages_with_bio(messages)

    print("\n" + "=" * 60)
    print(f"RESULTS — {url}")
    print("=" * 60)

    if not messages:
        print("(no messages scraped)")
    for i, msg in enumerate(messages[:5]):
        date_str = msg.tg_date.strftime("%Y-%m-%d %H:%M") if msg.tg_date else "unknown"
        print(f"\n[{i + 1}] ID={msg.tg_message_id}  {date_str}")
        username = msg.sender_username or ""
        print(f"     From: {msg.sender_name!r} (@{username})")
        if msg.sender_bio:
            print(f"     Bio:  {msg.sender_bio[:80]}")
        print(f"     Text: {msg.text[:120]}")

    print("\n" + "=" * 60)
    print(f"Total scraped  : {len(messages)}")
    print(f"With sender_bio: {sum(1 for m in messages if m.sender_bio)}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Telegram parser (no DB)")
    parser.add_argument("--url", required=True, help="Telegram chat URL, e.g. @somegroup")
    parser.add_argument("--limit", type=int, default=50, help="Max messages to fetch")
    args = parser.parse_args()

    try:
        asyncio.run(main(args.url, args.limit))
    except Exception as exc:
        logger.error("Fatal error: %s", exc)
        raise SystemExit(1) from exc
