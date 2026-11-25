#!/usr/bin/env python
"""Test scoring a single message without DB.

Usage:
    python scripts/test_scoring.py --message "Веду бизнес 3 года, оборот растёт..."
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.scoring.claude_client import ClaudeClient


async def main(message_text: str) -> None:
    settings = get_settings()
    client = ClaudeClient(api_key=settings.ANTHROPIC_API_KEY)

    print(f"\nСообщение:\n{message_text}\n")
    print("Отправляю в Claude...\n")

    result = await client.score_message(
        message_text=message_text,
        sender_name="Test User",
        sender_bio=None,
    )

    if result is None:
        print("Ошибка: Claude не вернул результат")
        return

    print(f"{'='*50}")
    print(f"FIT:     {'✓ ПОДХОДИТ' if result.fit else '✗ НЕ ПОДХОДИТ'}")
    print(f"SCORE:   {result.score}/100")
    print(f"REASON:  {result.reason}")
    print(f"SIGNALS: {', '.join(result.signals) if result.signals else '—'}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score a single message with Claude")
    parser.add_argument("--message", "-m", required=True, help="Message text to score")
    args = parser.parse_args()
    asyncio.run(main(args.message))
