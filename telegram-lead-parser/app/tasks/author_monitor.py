"""
Lead author monitor: finds new messages from authors whose messages became leads,
re-scores them with Claude, creates lead_signals, and updates lead score.

Confidence = score / 100.0 (0.0–1.0 scale).
Threshold for saving a signal:  >= 0.5
Threshold for "hot lead" alert: >= 0.85
"""

import asyncio
import logging

import httpx

from app.core.celery import celery_app
from app.core.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

_SIGNAL_THRESHOLD = 0.5
_HOT_THRESHOLD = 0.85
_NEW_MSGS_LIMIT = 20


@celery_app.task(
    bind=True,
    name="app.tasks.author_monitor.monitor_lead_authors",
    max_retries=1,
    default_retry_delay=300,
)
def monitor_lead_authors(self) -> dict:
    """Hourly: re-score new messages from lead authors and update confidence."""

    async def _run() -> dict:
        from datetime import datetime, timezone

        from sqlalchemy import func, select, update
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.core.config import get_settings
        from app.core.database import AsyncSessionLocal, dispose_engine
        from app.models.lead import Lead
        from app.models.lead_signal import LeadSignal
        from app.models.message import Message
        from app.repositories.user import UserRepository
        from app.scoring.claude_client import ClaudeClient

        await dispose_engine()
        settings = get_settings()

        async with AsyncSessionLocal() as db:
            owner = await UserRepository.get_by_telegram_id(db, settings.OWNER_TELEGRAM_ID)
            if owner is None:
                return {"error": "owner_not_found"}
            user_id = owner.id

            criteria_description: str | None = None
            try:
                from app.repositories.criteria import CriteriaRepository
                criteria = await CriteriaRepository.get_active(db, user_id)
                criteria_description = criteria.description if criteria else None
            except Exception:
                pass

            rows = await db.execute(
                select(Lead, Message.sender_id, Message.sender_username)
                .join(Lead.message)
                .where(
                    Lead.status != "rejected",
                    Message.sender_id.isnot(None),
                )
            )
            lead_author_rows = rows.all()

        if not lead_author_rows:
            logger.info("monitor_lead_authors: no active leads with known authors")
            return {"leads_checked": 0, "signals_added": 0, "leads_updated": 0}

        claude = ClaudeClient(api_key=settings.ANTHROPIC_API_KEY)
        signals_added = leads_updated = 0

        for lead, sender_id, sender_username in lead_author_rows:
            async with AsyncSessionLocal() as db:
                already_done = await db.execute(
                    select(LeadSignal.message_id).where(LeadSignal.lead_id == lead.id)
                )
                done_ids: set[int] = {r[0] for r in already_done.fetchall()}

                new_rows = await db.execute(
                    select(Message)
                    .where(
                        Message.sender_id == sender_id,
                        Message.tg_date > lead.scored_at,
                        Message.text.isnot(None),
                        Message.id.notin_(done_ids) if done_ids else True,
                    )
                    .order_by(Message.tg_date)
                    .limit(_NEW_MSGS_LIMIT)
                )
                new_messages = list(new_rows.scalars().all())

            if not new_messages:
                continue

            logger.info(
                "monitor_lead_authors: lead_id=%d author=%s new_msgs=%d",
                lead.id,
                sender_username or str(sender_id),
                len(new_messages),
            )

            old_score = lead.score
            got_signal = False

            for msg in new_messages:
                try:
                    result = await claude.score_message(
                        message_text=msg.text,
                        sender_name=msg.sender_name or "",
                        sender_bio=msg.sender_bio,
                        criteria_description=criteria_description,
                    )
                except Exception as exc:
                    logger.error(
                        "monitor_lead_authors: Claude error msg_id=%d: %s", msg.id, exc
                    )
                    continue

                if result is None:
                    continue

                confidence = result.score / 100.0
                if confidence < _SIGNAL_THRESHOLD:
                    logger.debug(
                        "monitor_lead_authors: msg_id=%d confidence=%.2f < %.2f — skip",
                        msg.id,
                        confidence,
                        _SIGNAL_THRESHOLD,
                    )
                    continue

                async with AsyncSessionLocal() as db:
                    stmt = (
                        pg_insert(LeadSignal)
                        .values(
                            lead_id=lead.id,
                            message_id=msg.id,
                            confidence=confidence,
                            found_at=datetime.now(timezone.utc),
                        )
                        .on_conflict_do_nothing(
                            index_elements=["lead_id", "message_id"]
                        )
                    )
                    ins_result = await db.execute(stmt)
                    await db.commit()

                if ins_result.rowcount:
                    signals_added += 1
                    got_signal = True
                    logger.info(
                        "monitor_lead_authors: signal lead_id=%d msg_id=%d confidence=%.2f",
                        lead.id,
                        msg.id,
                        confidence,
                    )

            if not got_signal:
                continue

            # Recalculate: average of original score and mean of all signals (×100)
            async with AsyncSessionLocal() as db:
                avg_row = await db.execute(
                    select(func.avg(LeadSignal.confidence)).where(
                        LeadSignal.lead_id == lead.id
                    )
                )
                avg_confidence = avg_row.scalar_one() or 0.0

            new_score = max(0, min(100, round((old_score + avg_confidence * 100) / 2)))

            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(Lead).where(Lead.id == lead.id).values(score=new_score)
                )
                await db.commit()

            leads_updated += 1
            logger.info(
                "monitor_lead_authors: lead_id=%d score %d→%d",
                lead.id,
                old_score,
                new_score,
            )

            old_conf = old_score / 100.0
            new_conf = new_score / 100.0
            if old_conf < _HOT_THRESHOLD and new_conf >= _HOT_THRESHOLD and settings.BOT_TOKEN:
                author_tag = f"@{sender_username}" if sender_username else f"id={sender_id}"
                text = (
                    f"🔥 Лид усилился: {author_tag}\n"
                    f"Новый score: {new_score} ({new_conf:.0%})"
                )
                admins = settings.admin_ids or (
                    [settings.OWNER_TELEGRAM_ID] if settings.OWNER_TELEGRAM_ID else []
                )
                proxy = settings.PROXY_URL or None
                async with httpx.AsyncClient(timeout=10, proxy=proxy) as http:
                    for admin_id in admins:
                        try:
                            await http.post(
                                f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage",
                                json={"chat_id": admin_id, "text": text},
                            )
                        except Exception as exc:
                            logger.warning(
                                "monitor_lead_authors notify %d: %s", admin_id, exc
                            )

        stats = {
            "leads_checked": len(lead_author_rows),
            "signals_added": signals_added,
            "leads_updated": leads_updated,
        }
        logger.info("monitor_lead_authors done: %s", stats)
        return stats

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("monitor_lead_authors failed: %s", exc)
        raise self.retry(exc=exc)
