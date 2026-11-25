#!/usr/bin/env python
"""Create default CriteriaProfile for user_id=1.

Usage:
    python scripts/seed_criteria.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import AsyncSessionLocal
from app.repositories.criteria import CriteriaRepository


async def main() -> None:
    async with AsyncSessionLocal() as db:
        existing = await CriteriaRepository.get_all(db, user_id=1)
        if existing:
            print(f"CriteriaProfile уже существует ({len(existing)} шт.). Пропускаем.")
            for p in existing:
                print(f"  id={p.id} name={p.name!r} active={p.is_active} min_score={p.min_score}")
            return

        profile = await CriteriaRepository.create(
            db=db,
            user_id=1,
            name="Предприниматели (базовый)",
            description=(
                "Предприниматели и специалисты с опытом, находящиеся в состоянии роста. "
                "Ищем людей у которых уже есть результат, но им этого мало или это не то."
            ),
            min_score=60,
        )
        await CriteriaRepository.set_active(db, criteria_id=profile.id, user_id=1)

        print(f"Создан CriteriaProfile:")
        print(f"  id={profile.id}")
        print(f"  name={profile.name!r}")
        print(f"  min_score={profile.min_score}")
        print(f"  is_active=True")


if __name__ == "__main__":
    asyncio.run(main())
