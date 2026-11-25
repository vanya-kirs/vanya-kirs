#!/usr/bin/env python3
"""
Run the full parse cycle for a Source that already exists in the DB.
Saves messages to DB via ParserService.

Prerequisites:
    - PostgreSQL running (make up)
    - Migrations applied (make migrate)
    - A Source row in the DB (insert via psql or admin)

Usage:
    python scripts/test_parser_db.py --source-id 1
"""
import argparse
import asyncio
import logging

from app.core.logging import setup_logging
from app.parser.service import ParserService

setup_logging()
logger = logging.getLogger(__name__)


async def main(source_id: int, limit: int) -> None:
    logger.info("Starting full parse cycle for source_id=%d", source_id)
    service = ParserService()
    try:
        result = await service.parse_source(source_id=source_id, limit=limit)
    except ValueError as exc:
        logger.error("%s", exc)
        return

    print("\n" + "=" * 60)
    print(f"PARSE RESULT — source_id={result.source_id}")
    print("=" * 60)
    print(f"  Messages scraped : {result.parsed}")
    print(f"  New (saved to DB): {result.new}")
    print(f"  Skipped (dupes)  : {result.skipped}")
    print(f"  Duration         : {result.duration_seconds:.1f}s")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test parser with DB save")
    parser.add_argument("--source-id", type=int, required=True, help="Source.id in DB")
    parser.add_argument("--limit", type=int, default=200, help="Max messages to fetch")
    args = parser.parse_args()

    try:
        asyncio.run(main(args.source_id, args.limit))
    except Exception as exc:
        logger.error("Fatal error: %s", exc)
        raise SystemExit(1) from exc
