import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.api_client import BotApiClient
from app.bot.keyboards import NavCallback, ProfileCallback, ScoreCallback, profile_kb, score_selector_kb
from app.bot.texts import (
    API_UNAVAILABLE,
    PROFILE_PARSING_TOGGLED_OFF,
    PROFILE_PARSING_TOGGLED_ON,
    PROFILE_SCORE_PROMPT,
    PROFILE_SCORE_SET,
    PROFILE_SUB_ACTIVE,
    PROFILE_SUB_INACTIVE,
    PROFILE_SUBSCRIBED,
    PROFILE_TEXT,
    PROFILE_PARSING_ON,
    PROFILE_PARSING_OFF,
)

logger = logging.getLogger(__name__)
router = Router()


def _format_date(iso_str: str | None) -> str:
    if not iso_str:
        return ""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return iso_str


def _build_profile_text(profile: dict, min_score: int | None = None) -> str:
    username = profile.get("username") or f"id{profile.get('telegram_id', '—')}"
    sub_active = profile.get("subscription_active", False)
    sub_until = profile.get("subscription_until")
    parsing = profile.get("parsing_enabled", True)

    if sub_active and sub_until:
        sub_status = PROFILE_SUB_ACTIVE.format(date=_format_date(sub_until))
    else:
        sub_status = PROFILE_SUB_INACTIVE

    parsing_status = PROFILE_PARSING_ON if parsing else PROFILE_PARSING_OFF
    min_score_text = str(min_score) if min_score is not None else "не задан"

    return PROFILE_TEXT.format(
        username=username,
        subscription_status=sub_status,
        parsing_status=parsing_status,
        min_score=min_score_text,
    )


async def _fetch_min_score(api: BotApiClient) -> int | None:
    try:
        criteria = await api.get_active_criteria()
        return criteria.get("min_score") if criteria else None
    except Exception:
        return None


@router.message(F.text == "Профиль")
async def text_profile(message: Message, api: BotApiClient) -> None:
    try:
        profile = await api.get_profile()
    except Exception as exc:
        logger.error("get_profile error: %s", exc)
        await message.answer(API_UNAVAILABLE)
        return

    min_score = await _fetch_min_score(api)
    parsing_enabled = profile.get("parsing_enabled", True)
    await message.answer(
        _build_profile_text(profile, min_score=min_score),
        reply_markup=profile_kb(parsing_enabled=parsing_enabled),
    )


@router.callback_query(ProfileCallback.filter(F.action == "subscribe"))
async def cb_subscribe(callback: CallbackQuery, api: BotApiClient) -> None:
    try:
        profile = await api.extend_subscription()
    except Exception as exc:
        logger.error("extend_subscription error: %s", exc)
        await callback.answer(API_UNAVAILABLE, show_alert=True)
        return

    min_score = await _fetch_min_score(api)
    date_str = _format_date(profile.get("subscription_until"))
    await callback.message.edit_text(
        _build_profile_text(profile, min_score=min_score),
        reply_markup=profile_kb(parsing_enabled=profile.get("parsing_enabled", True)),
    )
    await callback.answer(PROFILE_SUBSCRIBED.format(date=date_str), show_alert=True)


@router.callback_query(ProfileCallback.filter(F.action == "toggle_parsing"))
async def cb_toggle_parsing(callback: CallbackQuery, api: BotApiClient) -> None:
    try:
        current = await api.get_profile()
        new_state = not current.get("parsing_enabled", True)
        profile = await api.set_parsing_enabled(new_state)
    except Exception as exc:
        logger.error("toggle_parsing error: %s", exc)
        await callback.answer(API_UNAVAILABLE, show_alert=True)
        return

    min_score = await _fetch_min_score(api)
    await callback.message.edit_text(
        _build_profile_text(profile, min_score=min_score),
        reply_markup=profile_kb(parsing_enabled=profile.get("parsing_enabled", True)),
    )
    msg = PROFILE_PARSING_TOGGLED_ON if profile.get("parsing_enabled") else PROFILE_PARSING_TOGGLED_OFF
    await callback.answer(msg)


@router.callback_query(ProfileCallback.filter(F.action == "set_score"))
async def cb_set_score_menu(callback: CallbackQuery, api: BotApiClient) -> None:
    min_score = await _fetch_min_score(api)
    await callback.message.edit_text(
        PROFILE_SCORE_PROMPT,
        reply_markup=score_selector_kb(current=min_score or 0),
    )
    await callback.answer()


@router.callback_query(ScoreCallback.filter())
async def cb_score_selected(
    callback: CallbackQuery, callback_data: ScoreCallback, api: BotApiClient
) -> None:
    score = callback_data.value
    try:
        await api.set_min_score(score)
    except Exception as exc:
        logger.error("set_min_score error: %s", exc)
        await callback.answer(API_UNAVAILABLE, show_alert=True)
        return

    try:
        profile = await api.get_profile()
    except Exception as exc:
        logger.error("get_profile after score set: %s", exc)
        await callback.answer(PROFILE_SCORE_SET.format(score=score), show_alert=True)
        return

    await callback.message.edit_text(
        _build_profile_text(profile, min_score=score),
        reply_markup=profile_kb(parsing_enabled=profile.get("parsing_enabled", True)),
    )
    await callback.answer(PROFILE_SCORE_SET.format(score=score))


@router.callback_query(NavCallback.filter(F.to == "profile"))
async def cb_back_to_profile(callback: CallbackQuery, api: BotApiClient) -> None:
    try:
        profile = await api.get_profile()
    except Exception as exc:
        logger.error("get_profile error: %s", exc)
        await callback.answer(API_UNAVAILABLE, show_alert=True)
        return

    min_score = await _fetch_min_score(api)
    await callback.message.edit_text(
        _build_profile_text(profile, min_score=min_score),
        reply_markup=profile_kb(parsing_enabled=profile.get("parsing_enabled", True)),
    )
    await callback.answer()
