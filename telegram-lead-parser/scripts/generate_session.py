#!/usr/bin/env python3
"""
Interactively authorize a Telethon account and print the StringSession.

Usage:
    python scripts/generate_session.py

You will be prompted for your phone number and the OTP Telegram sends you.
Copy the printed SESSION_STRING into your .env file.
"""
import asyncio
import logging
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


async def main() -> None:
    print("=== Telethon StringSession Generator ===\n")

    api_id_raw = input("Enter API_ID (from https://my.telegram.org/apps): ").strip()
    api_hash = input("Enter API_HASH: ").strip()

    if not api_id_raw.isdigit():
        print("ERROR: API_ID must be an integer.", file=sys.stderr)
        sys.exit(1)

    api_id = int(api_id_raw)

    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        await client.start()
        session_string = client.session.save()

    print("\n" + "=" * 60)
    print("SESSION_STRING (add this to your .env):")
    print("=" * 60)
    print(session_string)
    print("=" * 60 + "\n")
    print("IMPORTANT: Keep this secret — it grants full access to your account.")


if __name__ == "__main__":
    asyncio.run(main())
