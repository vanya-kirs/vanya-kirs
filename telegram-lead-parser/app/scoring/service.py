import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.repositories.criteria import CriteriaRepository
from app.repositories.lead import LeadRepository
from app.repositories.message import MessageRepository
from app.repositories.source import SourceRepository
from app.scoring.claude_client import ClaudeBalanceError, ClaudeClient
from app.scoring.schemas import MessageToScore, ScoringBatchResult, ScoringResult

logger = logging.getLogger(__name__)

_BALANCE_FLAG = "claude:balance_exhausted"


async def _set_balance_exhausted(redis_url: str) -> None:
    import redis.asyncio as aioredis
    r = aioredis.from_url(redis_url, decode_responses=True)
    try:
        await r.set(_BALANCE_FLAG, "1")
    finally:
        await r.aclose()


async def _clear_balance_flag(redis_url: str) -> None:
    import redis.asyncio as aioredis
    r = aioredis.from_url(redis_url, decode_responses=True)
    try:
        await r.delete(_BALANCE_FLAG)
    finally:
        await r.aclose()


async def _is_balance_exhausted(redis_url: str) -> bool:
    import redis.asyncio as aioredis
    r = aioredis.from_url(redis_url, decode_responses=True)
    try:
        return bool(await r.get(_BALANCE_FLAG))
    finally:
        await r.aclose()


class ScoringService:
    def __init__(self) -> None:
        settings = get_settings()
        self._claude = ClaudeClient(api_key=settings.ANTHROPIC_API_KEY)

    async def score_source_messages(
        self,
        db: AsyncSession,
        source_id: int,
        user_id: int,
        limit: int = 100,
    ) -> ScoringBatchResult:
        start = time.monotonic()
        settings = get_settings()

        # Skip scoring if Claude balance is known to be exhausted — messages
        # stay unscored and accumulate until balance is restored.
        if await _is_balance_exhausted(settings.REDIS_URL):
            logger.warning(
                "score_source_messages: Claude balance exhausted flag set — skipping source_id=%d",
                source_id,
            )
            return ScoringBatchResult(
                total=0, scored=0, leads_found=0, errors=0, duration_seconds=0.0
            )

        criteria = await CriteriaRepository.get_active(db, user_id)
        if criteria is None:
            logger.warning(
                "No active CriteriaProfile for user_id=%d, skipping scoring", user_id
            )
            return ScoringBatchResult(
                total=0, scored=0, leads_found=0, errors=0, duration_seconds=0.0
            )

        source = await SourceRepository.get_by_id(db, source_id)
        source_context = source.url if source else None

        candidates = await MessageRepository.get_unscored(db, source_id=source_id, limit=limit)
        if not candidates:
            logger.info("No unscored messages for source_id=%d", source_id)
            return ScoringBatchResult(
                total=0, scored=0, leads_found=0, errors=0, duration_seconds=0.0
            )

        # Deduplication BEFORE claiming — messages still have is_scored=False here,
        # so has_scored_text_hash only matches previously-scored messages, not the current batch.
        from app.scoring.dedup import jaccard, text_hash as compute_text_hash
        dedup_skipped = 0
        dedup_skipped_ids: list[int] = []
        unique_messages: list = []
        for msg in candidates:
            if not msg.text:
                unique_messages.append(msg)
                continue
            # 1. Exact duplicate across any source
            if await MessageRepository.has_scored_text_hash(db, compute_text_hash(msg.text)):
                logger.debug(
                    "dedup: message_id=%d is exact repost, skipping", msg.id
                )
                dedup_skipped += 1
                dedup_skipped_ids.append(msg.id)
                continue
            # 2. Same sender already produced a lead on a similar topic
            if msg.sender_id:
                prior_texts = await MessageRepository.get_lead_texts_by_sender(db, msg.sender_id)
                if any(jaccard(msg.text, t) >= 0.6 for t in prior_texts):
                    logger.debug(
                        "dedup: message_id=%d sender_id=%d similar topic already a lead, skipping",
                        msg.id, msg.sender_id,
                    )
                    dedup_skipped += 1
                    dedup_skipped_ids.append(msg.id)
                    continue
            unique_messages.append(msg)

        if dedup_skipped_ids:
            await MessageRepository.set_skip_reason_bulk(db, dedup_skipped_ids, "pre_filtered")
        if dedup_skipped:
            logger.info(
                "dedup: skipped %d/%d messages for source_id=%d",
                dedup_skipped, len(candidates), source_id,
            )

        # Keyword pre-filter — skip messages that clearly don't fit before Claude
        from app.scoring.keyword_filter import keyword_prefilter
        kw_skipped = 0
        kw_skipped_ids: list[int] = []
        kw_messages: list = []
        for msg in unique_messages:
            if msg.text:
                should_score, reason = keyword_prefilter(msg.text)
                if not should_score:
                    logger.debug(
                        "keyword_filter: skip message_id=%d reason=%s", msg.id, reason
                    )
                    kw_skipped += 1
                    kw_skipped_ids.append(msg.id)
                    continue
            kw_messages.append(msg)
        if kw_skipped_ids:
            await MessageRepository.set_skip_reason_bulk(db, kw_skipped_ids, "pre_filtered")
        if kw_skipped:
            logger.info(
                "keyword_filter: skipped %d/%d messages for source_id=%d",
                kw_skipped, len(unique_messages), source_id,
            )

        # Atomically claim only messages that passed all pre-filters — set is_scored=True
        # so concurrent workers cannot double-score them.
        claimed_ids = set(
            await MessageRepository.claim_for_scoring(db, [m.id for m in kw_messages])
        )
        messages = [m for m in kw_messages if m.id in claimed_ids]
        if not messages:
            logger.info(
                "All candidates already claimed for source_id=%d, skipping",
                source_id,
            )
            return ScoringBatchResult(
                total=0, scored=0, leads_found=0, errors=0, duration_seconds=0.0
            )

        to_score: list[MessageToScore] = [
            MessageToScore(
                message_id=msg.id,
                text=msg.text or "",
                sender_name=msg.sender_name or "Unknown",
                sender_username=msg.sender_username,
                sender_bio=msg.sender_bio,
                source_url=source_context or "",
            )
            for msg in messages
        ]

        logger.info(
            "Scoring %d messages for source_id=%d with criteria_id=%d",
            len(to_score),
            source_id,
            criteria.id,
        )

        try:
            results: list[ScoringResult] = await self._claude.score_batch(
                messages=to_score,
                criteria_description=criteria.description,
                source_context=source_context,
            )
        except ClaudeBalanceError as exc:
            # Revert claim so these messages are retried when balance is restored.
            await MessageRepository.unclaim_messages(db, list(claimed_ids))
            logger.error(
                "Claude balance exhausted for source_id=%d — unclaimed %d messages: %s",
                source_id, len(claimed_ids), exc,
            )
            await _set_balance_exhausted(settings.REDIS_URL)
            from app.core.alerts import notify_admin
            await notify_admin(
                "⚠️ <b>Баланс Claude исчерпан</b>\n\n"
                "Скоринг приостановлен. Сообщения накапливаются и будут обработаны "
                "автоматически при пополнении баланса.\n\n"
                f"Ошибка: <code>{exc}</code>"
            )
            return ScoringBatchResult(
                total=len(to_score), scored=0, leads_found=0,
                errors=len(to_score), duration_seconds=round(time.monotonic() - start, 2),
            )

        # Successful batch — if balance flag was previously set, clear it and alert.
        flag_was_set = await _is_balance_exhausted(settings.REDIS_URL)
        if flag_was_set:
            await _clear_balance_flag(settings.REDIS_URL)
            from app.core.alerts import notify_admin
            await notify_admin(
                "✅ <b>Баланс Claude восстановлен</b>\n\n"
                "Скоринг возобновлён. Накопившиеся сообщения обрабатываются."
            )
            logger.info("Claude balance flag cleared — scoring resumed")

        scored = 0
        leads_found = 0
        errors = 0
        ai_rejected_ids: list[int] = []

        # Build message_id → sender_id map for enrichment after lead creation
        msg_sender_map = {msg.id: msg.sender_id for msg in messages if msg.sender_id}
        leads_to_enrich: list[tuple[int, int]] = []  # (message_id, sender_id)

        for result in results:
            if result.error:
                errors += 1
            else:
                scored += 1

            if result.fit and result.score >= criteria.min_score and not result.error:
                already_exists = await LeadRepository.exists(db, result.message_id)
                if not already_exists:
                    await LeadRepository.create(db, result, criteria.id)
                    leads_found += 1
                    logger.info(
                        "Lead created for message_id=%d score=%d", result.message_id, result.score
                    )
                    sender_id = msg_sender_map.get(result.message_id)
                    if sender_id:
                        leads_to_enrich.append((result.message_id, sender_id))
            elif not result.error:
                ai_rejected_ids.append(result.message_id)

            # is_scored already set by claim_for_scoring before Claude was called

        if ai_rejected_ids:
            await MessageRepository.set_skip_reason_bulk(db, ai_rejected_ids, "ai_rejected")

        duration = time.monotonic() - start
        batch_result = ScoringBatchResult(
            total=len(to_score),
            scored=scored,
            leads_found=leads_found,
            errors=errors,
            duration_seconds=round(duration, 2),
        )
        logger.info(
            "score_source_messages done: source_id=%d total=%d scored=%d leads=%d errors=%d dur=%.1fs",
            source_id,
            batch_result.total,
            batch_result.scored,
            batch_result.leads_found,
            batch_result.errors,
            batch_result.duration_seconds,
        )

        # Enrich sender profiles only for messages that became leads
        if leads_to_enrich:
            from app.tasks.score import enrich_lead_profile_task
            for msg_id, sid in leads_to_enrich:
                enrich_lead_profile_task.delay(msg_id, sid)
            logger.info("Queued %d profile enrichment tasks", len(leads_to_enrich))

        return batch_result

    async def score_all_sources(
        self,
        db: AsyncSession,
        user_id: int,
        limit_per_source: int = 50,
    ) -> dict[int, ScoringBatchResult]:
        sources = await SourceRepository.get_all_active(db, user_id=user_id)
        results: dict[int, ScoringBatchResult] = {}
        for source in sources:
            results[source.id] = await self.score_source_messages(
                db, source_id=source.id, user_id=user_id, limit=limit_per_source
            )
        return results

    async def rescore_message(
        self,
        db: AsyncSession,
        message_id: int,
        user_id: int,
    ) -> ScoringResult | None:
        from app.models.message import Message
        from sqlalchemy import select

        msg_row = (
            await db.execute(select(Message).where(Message.id == message_id))
        ).scalar_one_or_none()

        if msg_row is None or not msg_row.text:
            logger.warning("Message id=%d not found or has no text", message_id)
            return None

        criteria = await CriteriaRepository.get_active(db, user_id)
        source = await SourceRepository.get_by_id(db, msg_row.source_id)

        to_score = MessageToScore(
            message_id=message_id,
            text=msg_row.text,
            sender_name=msg_row.sender_name or "Unknown",
            sender_username=msg_row.sender_username,
            sender_bio=msg_row.sender_bio,
            source_url=source.url if source else "",
        )

        result = await self._claude.score_message_for_id(
            to_score,
            criteria_description=criteria.description if criteria else None,
            source_context=source.url if source else None,
        )

        if result is None:
            return None

        existing_lead = await LeadRepository.get_by_message_id(db, message_id)
        if existing_lead:
            await LeadRepository.update(
                db,
                lead_id=existing_lead.id,
                score=result.score,
                reason=result.reason,
                signals=result.signals,
                raw_response=result.raw_response,
                fit=result.fit,
            )
            logger.info("Rescored Lead id=%d message_id=%d score=%d", existing_lead.id, message_id, result.score)
        elif result.fit and criteria and result.score >= criteria.min_score:
            await LeadRepository.create(db, result, criteria.id)
            logger.info("Created Lead after rescore for message_id=%d score=%d", message_id, result.score)

        await MessageRepository.mark_scored(db, message_id)
        return result
