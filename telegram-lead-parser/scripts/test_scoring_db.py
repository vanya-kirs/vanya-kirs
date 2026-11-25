#!/usr/bin/env python
"""Score unscored messages from a DB source and save leads.

Usage:
    python scripts/test_scoring_db.py --source-id 1 --user-id 1 --limit 20
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import AsyncSessionLocal
from app.core.logging import setup_logging
from app.repositories.lead import LeadRepository
from app.scoring.service import ScoringService

setup_logging()


async def main(source_id: int, user_id: int, limit: int) -> None:
    service = ScoringService()

    async with AsyncSessionLocal() as db:
        print(f"\nСкоринг source_id={source_id} user_id={user_id} limit={limit}...\n")
        result = await service.score_source_messages(
            db=db, source_id=source_id, user_id=user_id, limit=limit
        )

        print(f"{'='*50}")
        print(f"Всего сообщений:  {result.total}")
        print(f"Проскорено:       {result.scored}")
        print(f"Лидов найдено:    {result.leads_found}")
        print(f"Ошибок:           {result.errors}")
        print(f"Время:            {result.duration_seconds:.1f}с")
        print(f"{'='*50}\n")

        if result.leads_found > 0:
            leads = await LeadRepository.get_all(db, user_id=user_id, limit=3)
            print(f"Топ-{min(3, len(leads))} лидов:\n")
            for i, lead in enumerate(leads[:3], 1):
                print(f"  #{i} Lead id={lead.id}  score={lead.score}  status={lead.status}")
                print(f"     Reason: {lead.reason}")
                print(f"     Signals: {', '.join(lead.signals) if lead.signals else '—'}")
                print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score messages from DB source")
    parser.add_argument("--source-id", type=int, required=True)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    asyncio.run(main(args.source_id, args.user_id, args.limit))
