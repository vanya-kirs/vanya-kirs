import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.api_client import BotApiClient
from app.bot.keyboards import (
    LeadCallback,
    LeadPageCallback,
    LeadViewCallback,
    NavCallback,
    lead_card_kb,
    lead_nav_only_kb,
    leads_menu_kb,
)
from app.bot.texts import (
    API_UNAVAILABLE,
    LEAD_ACCEPTED,
    LEAD_ERROR,
    LEAD_REJECTED,
    LEADS_CONTACTED_EMPTY,
    LEADS_EMPTY,
    LEADS_EXPORT_CAPTION,
    LEADS_EXPORT_ERROR,
    LEADS_MENU_TITLE,
    LEADS_REJECTED_EMPTY,
    LEADS_TOP_EMPTY,
)
from app.bot.utils import format_lead_card, format_lead_contact, format_lead_message

logger = logging.getLogger(__name__)
router = Router()


def _with_position(text: str, offset: int, total: int) -> str:
    """Append lead position inside current filtered list."""
    if total <= 0:
        return text
    return f"{text}\n\nПозиция: {offset + 1} из {total}"


async def _safe_edit_text(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> None:
    """Edit callback message and ignore no-op Telegram updates."""
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            logger.debug("Skip no-op edit for callback message")
            return
        raise


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _get_user_min_score(api: BotApiClient) -> int:
    """Return user's active criteria min_score, falling back to 40."""
    try:
        criteria = await api.get_active_criteria()
        if criteria:
            return int(criteria.get("min_score", 40))
    except Exception:
        pass
    return 40


@router.message(F.text == "Лиды")
async def text_leads(message: Message, api: BotApiClient) -> None:
    min_score = await _get_user_min_score(api)
    try:
        stats = await api.get_stats()
        by_status = stats.get("leads_by_status") or {}
        text = LEADS_MENU_TITLE.format(
            new=by_status.get("new", 0),
            viewed=by_status.get("viewed", 0),
            contacted=by_status.get("contacted", 0),
            rejected=by_status.get("rejected", 0),
        )
    except Exception as exc:
        logger.error("get_stats for leads error: %s", exc)
        text = "Лиды:"
    await message.answer(text, reply_markup=leads_menu_kb(min_score))


@router.callback_query(NavCallback.filter(F.to == "leads"))
async def cb_back_to_leads(callback: CallbackQuery, api: BotApiClient) -> None:
    min_score = await _get_user_min_score(api)
    try:
        stats = await api.get_stats()
        by_status = stats.get("leads_by_status") or {}
        text = LEADS_MENU_TITLE.format(
            new=by_status.get("new", 0),
            viewed=by_status.get("viewed", 0),
            contacted=by_status.get("contacted", 0),
            rejected=by_status.get("rejected", 0),
        )
    except Exception:
        text = "Лиды:"
    await callback.message.edit_text(text, reply_markup=leads_menu_kb(min_score))
    await callback.answer()


# ---------------------------------------------------------------------------
# Lead card — one at a time, auto-advance on action
# ---------------------------------------------------------------------------

async def _show_lead(
    callback: CallbackQuery,
    api: BotApiClient,
    offset: int,
    status: str,
    min_score: int,
    view: str = "card",
    answer: bool = True,
) -> None:
    """Fetch one lead and edit the current message to show it."""
    api_status: str | None = None
    if status in ("new", "rejected", "contacted"):
        api_status = status

    try:
        leads = await api.get_leads(
            min_score=min_score or None,
            status=api_status,
            limit=2 if status == "contacted" else 1,
            offset=offset,
        )
        total = await api.get_leads_count(
            min_score=min_score or None,
            status=api_status,
        )
    except Exception as exc:
        logger.error("get_leads error: %s", exc)
        await callback.answer(API_UNAVAILABLE, show_alert=True)
        return

    if not leads:
        if status == "top":
            empty = LEADS_TOP_EMPTY
        elif status == "rejected":
            empty = LEADS_REJECTED_EMPTY
        elif status == "contacted":
            empty = LEADS_CONTACTED_EMPTY
        else:
            empty = LEADS_EMPTY
        try:
            await callback.message.edit_text(empty, reply_markup=leads_menu_kb(min_score))
        except Exception:
            pass
        if answer:
            await callback.answer()
        return

    lead = leads[0]
    if status == "contacted":
        text = format_lead_message(lead) if view == "message" else format_lead_contact(lead)
        text = _with_position(text, offset, total)
        kb = lead_nav_only_kb(
            offset=offset,
            status=status,
            has_prev=offset > 0,
            has_next=len(leads) > 1,
            min_score=min_score,
            lead_id=lead["id"],
            view=view,
        )
        parse_mode = "HTML"
    else:
        text = _with_position(format_lead_card(lead), offset, total)
        kb = lead_card_kb(
            lead_id=lead["id"],
            offset=offset,
            status=status,
            min_score=min_score,
            has_prev=offset > 0,
            has_next=offset + 1 < total,
        )
        parse_mode = None

    await _safe_edit_text(callback, text, reply_markup=kb, parse_mode=parse_mode)
    if answer:
        await callback.answer()


@router.callback_query(LeadPageCallback.filter())
async def cb_lead_page(
    callback: CallbackQuery, callback_data: LeadPageCallback, api: BotApiClient
) -> None:
    await _show_lead(
        callback, api,
        offset=callback_data.offset,
        status=callback_data.status,
        min_score=callback_data.min_score,
    )


@router.callback_query(LeadViewCallback.filter())
async def cb_lead_toggle_view(
    callback: CallbackQuery, callback_data: LeadViewCallback, api: BotApiClient
) -> None:
    if callback_data.status == "contacted":
        await _show_lead(
            callback,
            api,
            offset=callback_data.offset,
            status=callback_data.status,
            min_score=callback_data.min_score,
            view=callback_data.view,
            answer=False,
        )
        await callback.answer()
        return

    try:
        lead = await api.get_lead(callback_data.lead_id)
    except Exception as exc:
        logger.error("get_lead error in toggle: %s", exc)
        await callback.answer(API_UNAVAILABLE, show_alert=True)
        return

    kb = lead_card_kb(
        lead_id=callback_data.lead_id,
        offset=callback_data.offset,
        status=callback_data.status,
        min_score=callback_data.min_score,
        view=callback_data.view,
    )

    if callback_data.view == "message":
        text = format_lead_message(lead)
        parse_mode = "HTML"
    else:
        text = format_lead_card(lead)
        parse_mode = None

    await _safe_edit_text(callback, text, reply_markup=kb, parse_mode=parse_mode)
    await callback.answer()


# ---------------------------------------------------------------------------
# Lead actions — all edit the current message
# ---------------------------------------------------------------------------

@router.callback_query(LeadCallback.filter(F.action == "accept"))
async def cb_lead_accept(
    callback: CallbackQuery, callback_data: LeadCallback, api: BotApiClient
) -> None:
    try:
        await api.update_lead_status(callback_data.id, "contacted")
        lead = await api.get_lead(callback_data.id)
    except Exception as exc:
        logger.error("lead accept error: %s", exc)
        await callback.answer(LEAD_ERROR, show_alert=True)
        return

    contact_text = format_lead_contact(lead)
    next_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="→ Следующий лид",
            callback_data=LeadPageCallback(
                offset=callback_data.offset,
                status=callback_data.status,
                min_score=callback_data.min_score,
            ).pack(),
        ),
        InlineKeyboardButton(text="К списку", callback_data=NavCallback(to="leads").pack()),
    ]])
    await callback.message.edit_text(contact_text, reply_markup=next_kb, parse_mode="HTML")
    await callback.answer(LEAD_ACCEPTED)


@router.callback_query(LeadCallback.filter(F.action == "reject"))
async def cb_lead_reject(
    callback: CallbackQuery, callback_data: LeadCallback, api: BotApiClient
) -> None:
    try:
        await api.update_lead_status(callback_data.id, "rejected")
    except Exception as exc:
        logger.error("lead reject error: %s", exc)
        await callback.answer(LEAD_ERROR, show_alert=True)
        return

    await callback.answer(LEAD_REJECTED)
    # Same offset — the rejected lead is gone, next one slides into its place
    await _show_lead(callback, api,
                     offset=callback_data.offset,
                     status=callback_data.status,
                     min_score=callback_data.min_score,
                     answer=False)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@router.callback_query(LeadCallback.filter(F.action == "export"))
async def cb_leads_export(
    callback: CallbackQuery, callback_data: LeadCallback, api: BotApiClient
) -> None:
    await callback.answer()
    min_score = callback_data.min_score or 40
    try:
        xlsx_bytes = await api.export_leads_xlsx(min_score=min_score)
    except Exception as exc:
        logger.error("export_leads_xlsx error: %s", exc)
        await callback.message.answer(LEADS_EXPORT_ERROR)
        return
    from datetime import datetime as _dt
    filename = f"leads_{_dt.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    await callback.message.answer_document(
        BufferedInputFile(xlsx_bytes, filename=filename),
        caption=LEADS_EXPORT_CAPTION,
    )
