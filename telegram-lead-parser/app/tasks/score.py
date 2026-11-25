import asyncio
import logging

from app.core.celery import celery_app
from app.core.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.tasks.score.score_source_task",
    max_retries=3,
    default_retry_delay=30,
)
def score_source_task(self, source_id: int, user_id: int, limit: int = 100) -> dict:
    """Score unscored messages for one source."""
    from app.core.database import AsyncSessionLocal
    from app.scoring.service import ScoringService

    async def _run():
        from app.core.database import dispose_engine
        await dispose_engine()
        service = ScoringService()
        async with AsyncSessionLocal() as db:
            return await service.score_source_messages(
                db=db, source_id=source_id, user_id=user_id, limit=limit
            )

    try:
        result = asyncio.run(_run())
        logger.info(
            "score_source_task done: source_id=%d total=%d leads=%d errors=%d",
            source_id,
            result.total,
            result.leads_found,
            result.errors,
        )
        return {
            "source_id": source_id,
            "total": result.total,
            "scored": result.scored,
            "leads_found": result.leads_found,
            "errors": result.errors,
            "duration_seconds": result.duration_seconds,
        }
    except Exception as exc:
        logger.error("score_source_task failed for source_id=%d: %s", source_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(name="app.tasks.score.score_all_sources_task")
def score_all_sources_task(user_id: int) -> dict:
    """Enqueue score tasks for all active sources of a user."""
    from app.core.database import AsyncSessionLocal
    from app.repositories.source import SourceRepository

    async def _get_sources():
        from app.core.database import dispose_engine
        await dispose_engine()
        async with AsyncSessionLocal() as db:
            return await SourceRepository.get_all_active(db, user_id=user_id)

    sources = asyncio.run(_get_sources())
    for source in sources:
        score_source_task.delay(source.id, user_id)

    logger.info("score_all_sources_task: queued %d sources for user_id=%d", len(sources), user_id)
    return {"queued": len(sources), "user_id": user_id}


@celery_app.task(
    bind=True,
    name="app.tasks.score.score_new_message_task",
    max_retries=3,
    default_retry_delay=10,
)
def score_new_message_task(self, message_id: int, user_id: int) -> dict:
    """
    Score a single new message from the real-time listener.
    Full flow: fetch message → get criteria → call Claude → create Lead → notify.
    """
    from datetime import datetime, timezone

    from app.core.config import get_settings
    from app.core.database import AsyncSessionLocal
    from app.repositories.criteria import CriteriaRepository
    from app.repositories.lead import LeadRepository
    from app.repositories.message import MessageRepository
    from app.scoring.claude_client import ClaudeClient
    from app.scoring.schemas import MessageToScore, ScoringResult

    async def _run() -> dict:
        from app.core.database import dispose_engine
        await dispose_engine()
        settings = get_settings()
        sender_id_for_enrichment: int | None = None
        async with AsyncSessionLocal() as db:
            # 1. Fetch the message with its source
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            from app.models.message import Message

            result = await db.execute(
                select(Message)
                .options(selectinload(Message.source))
                .where(Message.id == message_id)
            )
            msg = result.scalar_one_or_none()
            if msg is None:
                logger.warning("score_new_message_task: message_id=%d not found", message_id)
                return {"message_id": message_id, "scored": False, "reason": "not_found"}

            if not msg.text:
                logger.debug("score_new_message_task: message_id=%d has no text", message_id)
                return {"message_id": message_id, "scored": False, "reason": "no_text"}

            # 2. Atomically claim this message — prevents duplicate scoring
            #    by concurrent workers or the batch scoring task
            claimed = await MessageRepository.claim_for_scoring(db, [message_id])
            if not claimed:
                logger.debug("score_new_message_task: message_id=%d already claimed", message_id)
                return {"message_id": message_id, "scored": False, "reason": "already_scored"}

            # 2a. Cross-source deduplication — skip if exact repost or same sender/topic
            from app.scoring.dedup import jaccard, text_hash as compute_text_hash
            if msg.text:
                if await MessageRepository.has_scored_text_hash(db, compute_text_hash(msg.text)):
                    logger.info(
                        "score_new_message_task: message_id=%d exact repost, skipping", message_id
                    )
                    return {"message_id": message_id, "scored": False, "reason": "duplicate_text"}
                if msg.sender_id:
                    prior_texts = await MessageRepository.get_lead_texts_by_sender(db, msg.sender_id)
                    if any(jaccard(msg.text, t) >= 0.6 for t in prior_texts):
                        logger.info(
                            "score_new_message_task: message_id=%d similar topic from sender_id=%d, skipping",
                            message_id, msg.sender_id,
                        )
                        return {"message_id": message_id, "scored": False, "reason": "duplicate_sender_topic"}

            # 2b. Keyword pre-filter — skip obvious non-leads before Claude
            from app.scoring.keyword_filter import keyword_prefilter
            if msg.text:
                should_score, kw_reason = keyword_prefilter(msg.text)
                if not should_score:
                    logger.info(
                        "score_new_message_task: message_id=%d skipped by keyword_filter reason=%s",
                        message_id, kw_reason,
                    )
                    return {"message_id": message_id, "scored": False, "reason": kw_reason}

            # 3. Get active criteria profile
            criteria = await CriteriaRepository.get_active(db, user_id=user_id)
            if criteria is None:
                logger.warning(
                    "score_new_message_task: no active criteria for user_id=%d", user_id
                )
                return {"message_id": message_id, "scored": False, "reason": "no_criteria"}

            # 4. Score via Claude
            client = ClaudeClient(api_key=settings.ANTHROPIC_API_KEY)
            msg_to_score = MessageToScore(
                message_id=message_id,
                text=msg.text,
                sender_name=msg.sender_name or "",
                sender_username=msg.sender_username,
                sender_bio=msg.sender_bio,
                source_url=msg.source.url if msg.source else "",
            )
            scoring_result = await client.score_message_for_id(
                msg_to_score,
                criteria_description=criteria.description,
                source_context=msg.source.name if msg.source else None,
            )

            if scoring_result is None:
                logger.error(
                    "score_new_message_task: Claude returned None for message_id=%d", message_id
                )
                return {"message_id": message_id, "scored": False, "reason": "claude_error"}

            # Fix message_id (score_message_for_id sets it from msg object)
            scoring_result.message_id = message_id

            # 6. Skip or create Lead
            if not scoring_result.fit or scoring_result.score < criteria.min_score:
                logger.info(
                    "score_new_message_task: message_id=%d score=%d fit=%s below threshold — no lead",
                    message_id,
                    scoring_result.score,
                    scoring_result.fit,
                )
                return {
                    "message_id": message_id,
                    "scored": True,
                    "fit": scoring_result.fit,
                    "score": scoring_result.score,
                    "lead_created": False,
                }

            # 7. Idempotency — skip if lead already exists
            if await LeadRepository.exists(db, message_id):
                logger.info(
                    "score_new_message_task: lead already exists for message_id=%d", message_id
                )
                return {
                    "message_id": message_id,
                    "scored": True,
                    "fit": scoring_result.fit,
                    "score": scoring_result.score,
                    "lead_created": False,
                }

            lead = await LeadRepository.create(db, scoring_result, criteria.id)
            logger.info(
                "score_new_message_task: created lead_id=%d for message_id=%d score=%d",
                lead.id,
                message_id,
                lead.score,
            )
            sender_id_for_enrichment = msg.sender_id

        # 8. Enrich sender profile (only for leads that passed threshold)
        if sender_id_for_enrichment:
            enrich_lead_profile_task.delay(message_id, sender_id_for_enrichment)

        # 9. Send Telegram notification outside the DB session
        await _notify_lead(message_id, user_id)

        return {
            "message_id": message_id,
            "scored": True,
            "fit": scoring_result.fit,
            "score": scoring_result.score,
            "lead_created": True,
        }

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("score_new_message_task failed for message_id=%d: %s", message_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    name="app.tasks.score.enrich_lead_profile_task",
    max_retries=2,
    default_retry_delay=15,
)
def enrich_lead_profile_task(self, message_id: int, sender_id: int) -> dict:
    """
    Fetch full Telegram profile for a lead's sender and store bio/phone on the message.
    Called only after a message passes the scoring threshold.
    """
    from app.core.config import get_settings
    from app.core.database import AsyncSessionLocal
    from app.parser.client import TelethonClient
    from app.repositories.message import MessageRepository

    async def _run() -> dict:
        from app.core.database import dispose_engine
        await dispose_engine()
        settings = get_settings()
        if not (settings.API_ID and settings.API_HASH and settings.SESSION_STRING):
            logger.debug("enrich_lead_profile_task: Telethon not configured, skipping")
            return {"message_id": message_id, "enriched": False}

        async with TelethonClient(
            api_id=settings.API_ID,
            api_hash=settings.API_HASH,
            session_string=settings.SESSION_STRING,
        ) as client:
            profile = await client.get_user_profile(sender_id)

        if profile is None:
            logger.debug("enrich_lead_profile_task: no profile for sender_id=%d", sender_id)
            return {"message_id": message_id, "enriched": False}

        async with AsyncSessionLocal() as db:
            await MessageRepository.update_sender_profile(
                db, message_id, bio=profile.bio, phone=profile.phone
            )

        logger.info(
            "enrich_lead_profile_task: enriched message_id=%d sender_id=%d phone=%s",
            message_id, sender_id, bool(profile.phone),
        )
        return {"message_id": message_id, "enriched": True}

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("enrich_lead_profile_task failed for message_id=%d: %s", message_id, exc)
        raise self.retry(exc=exc)


async def _notify_lead(message_id: int, user_id: int) -> None:
    """Fetch lead data and send Telegram notification to owner."""
    try:
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode

        from app.bot.handlers.notifications import send_lead_notification
        from app.core.config import get_settings
        from app.core.database import AsyncSessionLocal, dispose_engine
        from app.repositories.lead import LeadRepository

        settings = get_settings()

        await dispose_engine()
        async with AsyncSessionLocal() as db:
            lead = await LeadRepository.get_by_message_id_with_details(db, message_id)
            if lead is None:
                return

            msg = lead.message
            src = msg.source if msg else None
            lead_data = {
                "id": lead.id,
                "score": lead.score,
                "fit": lead.fit,
                "reason": lead.reason,
                "signals": lead.signals,
                "status": lead.status,
                "scored_at": lead.scored_at.isoformat() if lead.scored_at else None,
                "message": {
                    "id": msg.id if msg else None,
                    "text": msg.text if msg else None,
                    "sender_name": msg.sender_name if msg else None,
                    "sender_username": msg.sender_username if msg else None,
                    "sender_bio": msg.sender_bio if msg else None,
                    "tg_date": msg.tg_date.isoformat() if msg and msg.tg_date else None,
                },
                "source": {
                    "id": src.id if src else None,
                    "url": src.url if src else None,
                    "name": src.name if src else None,
                },
            }

        bot = Bot(
            token=settings.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            await send_lead_notification(bot, lead_data)
        finally:
            await bot.session.close()

    except Exception as exc:
        logger.error("_notify_lead failed for message_id=%d: %s", message_id, exc)
