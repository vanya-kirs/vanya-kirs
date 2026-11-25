import asyncio
import json
import logging
import re
from datetime import datetime, timezone

import anthropic

from app.core.config import get_settings
from app.scoring.prompts import PromptBuilder
from app.scoring.schemas import MessageToScore, ScoringResult

logger = logging.getLogger(__name__)

_BALANCE_KEYWORDS = ("credit balance", "billing", "payment", "insufficient", "quota exceeded")


class ClaudeBalanceError(Exception):
    """Raised when Anthropic API reports that the account has no credits."""


def _is_balance_error(exc: anthropic.APIStatusError) -> bool:
    msg = str(exc).lower()
    return exc.status_code in (402, 403) and any(kw in msg for kw in _BALANCE_KEYWORDS)


class ClaudeClient:
    MODEL = "claude-haiku-4-5-20251001"
    MAX_TOKENS = 500
    MAX_TEXT_LENGTH = 2000
    _RATE_LIMIT_WAIT = 60
    _MAX_RETRIES = 3

    def __init__(self, api_key: str) -> None:
        import httpx

        settings = get_settings()
        proxy_url = settings.PROXY_URL or None
        http_client = httpx.AsyncClient(proxy=proxy_url) if proxy_url else None
        self._client = anthropic.AsyncAnthropic(api_key=api_key, http_client=http_client)
        self._rate_limit_wait = settings.CLAUDE_RATE_LIMIT_WAIT_SECONDS
        self._batch_item_delay = settings.CLAUDE_BATCH_ITEM_DELAY_SECONDS

    async def score_message(
        self,
        message_text: str,
        sender_name: str,
        sender_bio: str | None,
        criteria_description: str | None = None,
        source_context: str | None = None,
    ) -> ScoringResult | None:
        truncated = message_text[: self.MAX_TEXT_LENGTH]
        user_msg = PromptBuilder.build_user_message(
            message_text=truncated,
            sender_name=sender_name,
            sender_bio=sender_bio,
            criteria_description=criteria_description,
            source_context=source_context,
        )

        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                response = await self._client.messages.create(
                    model=self.MODEL,
                    max_tokens=self.MAX_TOKENS,
                    system=PromptBuilder.SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_msg}],
                )
                raw_text = response.content[0].text
                logger.debug("Claude raw response: %s", raw_text)
                return self._parse_response(raw_text, message_id=0)

            except anthropic.RateLimitError as exc:
                logger.warning(
                    "RateLimitError on attempt %d/%d, waiting %ds: %s",
                    attempt,
                    self._MAX_RETRIES,
                    self._rate_limit_wait,
                    exc,
                )
                if attempt < self._MAX_RETRIES:
                    await asyncio.sleep(self._rate_limit_wait)
                else:
                    logger.error("All retries exhausted after RateLimitError")
                    return None

            except anthropic.APIStatusError as exc:
                if _is_balance_error(exc):
                    raise ClaudeBalanceError(str(exc)) from exc
                logger.error("Claude APIStatusError: %s", exc)
                return None
            except anthropic.APIError as exc:
                logger.error("Claude APIError: %s", exc)
                return None

        return None

    async def score_message_for_id(
        self,
        msg: MessageToScore,
        criteria_description: str | None = None,
        source_context: str | None = None,
    ) -> ScoringResult | None:
        truncated = msg.text[: self.MAX_TEXT_LENGTH]
        user_content = PromptBuilder.build_user_message(
            message_text=truncated,
            sender_name=msg.sender_name,
            sender_bio=msg.sender_bio,
            criteria_description=criteria_description,
            source_context=source_context,
        )

        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                response = await self._client.messages.create(
                    model=self.MODEL,
                    max_tokens=self.MAX_TOKENS,
                    system=PromptBuilder.SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_content}],
                )
                raw_text = response.content[0].text
                logger.debug("Claude raw response for msg_id=%d: %s", msg.message_id, raw_text)
                return self._parse_response(raw_text, message_id=msg.message_id)

            except anthropic.RateLimitError as exc:
                logger.warning(
                    "RateLimitError for msg_id=%d attempt %d/%d, waiting %ds: %s",
                    msg.message_id,
                    attempt,
                    self._MAX_RETRIES,
                    self._rate_limit_wait,
                    exc,
                )
                if attempt < self._MAX_RETRIES:
                    await asyncio.sleep(self._rate_limit_wait)
                else:
                    logger.error(
                        "All retries exhausted for msg_id=%d", msg.message_id
                    )
                    return None

            except anthropic.APIError as exc:
                logger.error("Claude APIError for msg_id=%d: %s", msg.message_id, exc)
                return None

        return None

    async def score_batch(
        self,
        messages: list[MessageToScore],
        criteria_description: str | None = None,
        source_context: str | None = None,
    ) -> list[ScoringResult]:
        results: list[ScoringResult] = []
        for msg in messages:
            try:
                result = await self.score_message_for_id(
                    msg,
                    criteria_description=criteria_description,
                    source_context=source_context,
                )
                if result is not None:
                    results.append(result)
                else:
                    results.append(
                        ScoringResult(
                            message_id=msg.message_id,
                            fit=False,
                            score=0,
                            reason="Ошибка при скоринге",
                            signals=[],
                            raw_response={},
                            scored_at=datetime.now(tz=timezone.utc),
                            error="Claude returned None",
                        )
                    )
            except ClaudeBalanceError:
                raise  # let the caller (service) handle unclaim + alert
            except Exception as exc:
                logger.error("Unexpected error scoring msg_id=%d: %s", msg.message_id, exc)
                results.append(
                    ScoringResult(
                        message_id=msg.message_id,
                        fit=False,
                        score=0,
                        reason="Неожиданная ошибка",
                        signals=[],
                        raw_response={},
                        scored_at=datetime.now(tz=timezone.utc),
                        error=str(exc),
                    )
                )
            await asyncio.sleep(self._batch_item_delay)
        return results

    @staticmethod
    def _parse_response(raw_text: str, message_id: int) -> ScoringResult:
        scored_at = datetime.now(tz=timezone.utc)
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    data = None
            else:
                data = None

        if data is None:
            logger.error("Failed to parse Claude response for msg_id=%d: %s", message_id, raw_text)
            return ScoringResult(
                message_id=message_id,
                fit=False,
                score=0,
                reason="Ошибка парсинга ответа",
                signals=[],
                raw_response={"raw": raw_text},
                scored_at=scored_at,
                error="JSON parse error",
            )

        return ScoringResult(
            message_id=message_id,
            fit=bool(data.get("fit", False)),
            score=int(data.get("score", 0)),
            reason=str(data.get("reason", "")),
            signals=list(data.get("signals", [])),
            raw_response=data,
            scored_at=scored_at,
        )
