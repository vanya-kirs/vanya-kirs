import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.api_client import BotApiClient
from app.bot.keyboards import (
    CriteriaCallback,
    criteria_actions_kb,
    criteria_activate_confirm_kb,
    criteria_menu_kb,
)
from app.bot.states import CriteriaStates
from app.bot.texts import (
    API_UNAVAILABLE,
    CRITERIA_ACTIVATE_DONE,
    CRITERIA_ACTIVATED,
    CRITERIA_ADD_DESC,
    CRITERIA_ADD_NAME,
    CRITERIA_ADD_SCORE,
    CRITERIA_ACTIVE_INFO,
    CRITERIA_CREATED,
    CRITERIA_CREATED_NOT_ACTIVE,
    CRITERIA_ERROR,
    CRITERIA_ITEM,
    CRITERIA_LIST_EMPTY,
    CRITERIA_MENU_TITLE,
    CRITERIA_NO_ACTIVE,
    CRITERIA_SCORE_INVALID,
)
from app.bot.utils import truncate

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.text == "Критерии")
async def text_criteria(message: Message, api: BotApiClient) -> None:
    try:
        active = await api.get_active_criteria()
        if active:
            info = CRITERIA_ACTIVE_INFO.format(
                name=active.get("name"), min_score=active.get("min_score")
            )
        else:
            info = CRITERIA_NO_ACTIVE
    except Exception as exc:
        logger.error("get_active_criteria error: %s", exc)
        info = ""

    await message.answer(
        f"{CRITERIA_MENU_TITLE}\n\n{info}" if info else CRITERIA_MENU_TITLE,
        reply_markup=criteria_menu_kb(),
    )


@router.callback_query(CriteriaCallback.filter(F.action == "add"))
async def cb_criteria_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer(CRITERIA_ADD_NAME)
    await state.set_state(CriteriaStates.waiting_name)
    await callback.answer()


@router.message(CriteriaStates.waiting_name)
async def state_criteria_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    await state.update_data(name=name)
    await message.answer(CRITERIA_ADD_DESC)
    await state.set_state(CriteriaStates.waiting_description)


@router.message(CriteriaStates.waiting_description)
async def state_criteria_description(message: Message, state: FSMContext) -> None:
    description = (message.text or "").strip()
    await state.update_data(description=description)
    await message.answer(CRITERIA_ADD_SCORE)
    await state.set_state(CriteriaStates.waiting_min_score)


@router.message(CriteriaStates.waiting_min_score)
async def state_criteria_min_score(
    message: Message, state: FSMContext, api: BotApiClient
) -> None:
    text = (message.text or "").strip()
    try:
        min_score = int(text)
        if not 40 <= min_score <= 80:
            raise ValueError
    except ValueError:
        await message.answer(CRITERIA_SCORE_INVALID)
        return

    data = await state.get_data()
    try:
        profile = await api.create_criteria(
            name=data["name"],
            description=data["description"],
            min_score=min_score,
        )
    except Exception as exc:
        logger.error("create_criteria error: %s", exc)
        await message.answer(CRITERIA_ERROR)
        await state.clear()
        return

    await state.update_data(new_criteria_id=profile["id"])
    await message.answer(
        CRITERIA_CREATED,
        reply_markup=criteria_activate_confirm_kb(profile["id"]),
    )
    await state.set_state(CriteriaStates.confirming_activate)


@router.callback_query(CriteriaCallback.filter(F.action == "act_yes"))
async def cb_criteria_act_yes(
    callback: CallbackQuery, callback_data: CriteriaCallback, state: FSMContext, api: BotApiClient
) -> None:
    try:
        await api.activate_criteria(callback_data.id)
    except Exception as exc:
        logger.error("activate_criteria error: %s", exc)
        await callback.answer(CRITERIA_ERROR, show_alert=True)
        await state.clear()
        return

    await callback.message.answer(CRITERIA_ACTIVATED, reply_markup=criteria_menu_kb())
    await state.clear()
    await callback.answer()


@router.callback_query(CriteriaCallback.filter(F.action == "act_no"))
async def cb_criteria_act_no(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer(CRITERIA_CREATED_NOT_ACTIVE, reply_markup=criteria_menu_kb())
    await state.clear()
    await callback.answer()


@router.callback_query(CriteriaCallback.filter(F.action == "list"))
async def cb_criteria_list(callback: CallbackQuery, api: BotApiClient) -> None:
    try:
        profiles = await api.get_criteria()
    except Exception as exc:
        logger.error("get_criteria error: %s", exc)
        await callback.message.answer(API_UNAVAILABLE)
        await callback.answer()
        return

    if not profiles:
        await callback.message.answer(CRITERIA_LIST_EMPTY, reply_markup=criteria_menu_kb())
        await callback.answer()
        return

    for p in profiles:
        active_mark = "АКТИВНЫЙ " if p.get("is_active") else ""
        text = CRITERIA_ITEM.format(
            active_mark=active_mark,
            name=p.get("name"),
            min_score=p.get("min_score"),
            description=truncate(p.get("description"), 100),
        )
        await callback.message.answer(
            text,
            reply_markup=criteria_actions_kb(p["id"], p.get("is_active", False)),
        )

    await callback.answer()


@router.callback_query(CriteriaCallback.filter(F.action == "activate"))
async def cb_criteria_activate(
    callback: CallbackQuery, callback_data: CriteriaCallback, api: BotApiClient
) -> None:
    try:
        await api.activate_criteria(callback_data.id)
    except Exception as exc:
        logger.error("activate_criteria error: %s", exc)
        await callback.answer(CRITERIA_ERROR, show_alert=True)
        return

    await callback.answer(CRITERIA_ACTIVATE_DONE, show_alert=True)
    # Refresh the list
    try:
        profiles = await api.get_criteria()
        for p in profiles:
            active_mark = "АКТИВНЫЙ " if p.get("is_active") else ""
            text = CRITERIA_ITEM.format(
                active_mark=active_mark,
                name=p.get("name"),
                min_score=p.get("min_score"),
                description=truncate(p.get("description"), 100),
            )
            await callback.message.answer(
                text,
                reply_markup=criteria_actions_kb(p["id"], p.get("is_active", False)),
            )
    except Exception:
        pass
