import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.api_client import BotApiClient
from app.bot.keyboards import (
    SourceCallback,
    source_actions_kb,
    source_delete_confirm_kb,
    sources_menu_kb,
)
from app.bot.states import SourceStates
from app.bot.texts import (
    API_UNAVAILABLE,
    SOURCE_ADD_PROMPT,
    SOURCE_ADDED,
    SOURCE_DELETE_CONFIRM,
    SOURCE_DELETED,
    SOURCE_ERROR,
    SOURCE_FOUND,
    SOURCE_ITEM,
    SOURCE_LIST_EMPTY,
    SOURCE_MENU_TITLE,
    SOURCE_NAME_PROMPT,
    SOURCE_NOT_FOUND,
    SOURCE_PARSE_STARTED,
    SOURCE_URL_INVALID,
    SOURCE_VALIDATING,
)
from app.bot.utils import format_datetime

logger = logging.getLogger(__name__)
router = Router()

_URL_PREFIXES = ("@", "https://t.me/")


def _is_valid_url(url: str) -> bool:
    return url.strip().startswith(_URL_PREFIXES)


@router.message(F.text == "Источники")
async def text_sources(message: Message) -> None:
    await message.answer(SOURCE_MENU_TITLE, reply_markup=sources_menu_kb())


@router.callback_query(SourceCallback.filter(F.action == "add"))
async def cb_source_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer(SOURCE_ADD_PROMPT)
    await state.set_state(SourceStates.waiting_url)
    await callback.answer()


@router.message(SourceStates.waiting_url)
async def state_source_url(message: Message, state: FSMContext, api: BotApiClient) -> None:
    url = (message.text or "").strip()
    if not _is_valid_url(url):
        await message.answer(SOURCE_URL_INVALID)
        return

    wait_msg = await message.answer(SOURCE_VALIDATING)
    try:
        result = await api.validate_source(url)
    except Exception as exc:
        logger.error("validate_source error: %s", exc)
        await wait_msg.delete()
        await message.answer(API_UNAVAILABLE)
        await state.clear()
        return

    await wait_msg.delete()

    if not result.get("is_valid"):
        await message.answer(
            SOURCE_NOT_FOUND.format(error=result.get("error", "неизвестная ошибка"))
        )
        await state.clear()
        return

    title = result.get("title") or url
    members = result.get("members_count") or 0
    await message.answer(SOURCE_FOUND.format(title=title, members_count=members))
    await state.update_data(url=url, title=title)
    await state.set_state(SourceStates.waiting_name)


@router.message(SourceStates.waiting_name)
async def state_source_name(message: Message, state: FSMContext, api: BotApiClient) -> None:
    name = (message.text or "").strip()
    data = await state.get_data()
    url = data.get("url", "")

    try:
        await api.create_source(url=url, name=name)
    except Exception as exc:
        logger.error("create_source error: %s", exc)
        await message.answer(SOURCE_ERROR)
        await state.clear()
        return

    await message.answer(SOURCE_ADDED.format(name=name), reply_markup=sources_menu_kb())
    await state.clear()


@router.callback_query(SourceCallback.filter(F.action == "list"))
async def cb_source_list(callback: CallbackQuery, api: BotApiClient) -> None:
    try:
        sources = await api.get_sources()
    except Exception as exc:
        logger.error("get_sources error: %s", exc)
        await callback.message.answer(API_UNAVAILABLE)
        await callback.answer()
        return

    if not sources:
        await callback.message.answer(SOURCE_LIST_EMPTY, reply_markup=sources_menu_kb())
        await callback.answer()
        return

    for src in sources:
        text = SOURCE_ITEM.format(
            name=src.get("name"),
            url=src.get("url"),
            last_parsed_at=format_datetime(src.get("last_parsed_at")),
        )
        await callback.message.answer(text, reply_markup=source_actions_kb(src["id"]))

    await callback.answer()


@router.callback_query(SourceCallback.filter(F.action == "parse"))
async def cb_source_parse(
    callback: CallbackQuery, callback_data: SourceCallback, api: BotApiClient
) -> None:
    try:
        result = await api.run_parse(callback_data.id)
    except Exception as exc:
        logger.error("run_parse error: %s", exc)
        await callback.answer(API_UNAVAILABLE, show_alert=True)
        return

    task_id = result.get("task_id", "—")
    await callback.message.answer(SOURCE_PARSE_STARTED.format(task_id=task_id))
    await callback.answer()


@router.callback_query(SourceCallback.filter(F.action == "delete"))
async def cb_source_delete(
    callback: CallbackQuery, callback_data: SourceCallback, state: FSMContext
) -> None:
    await callback.message.answer(
        SOURCE_DELETE_CONFIRM,
        reply_markup=source_delete_confirm_kb(callback_data.id),
    )
    await state.set_state(SourceStates.confirming_delete)
    await callback.answer()


@router.callback_query(SourceCallback.filter(F.action == "del_yes"))
async def cb_source_delete_confirm(
    callback: CallbackQuery, callback_data: SourceCallback, state: FSMContext, api: BotApiClient
) -> None:
    try:
        await api.delete_source(callback_data.id)
    except Exception as exc:
        logger.error("delete_source error: %s", exc)
        await callback.answer(SOURCE_ERROR, show_alert=True)
        await state.clear()
        return

    await callback.message.answer(SOURCE_DELETED, reply_markup=sources_menu_kb())
    await state.clear()
    await callback.answer()


@router.callback_query(SourceCallback.filter(F.action == "del_no"))
async def cb_source_delete_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(SOURCE_MENU_TITLE, reply_markup=sources_menu_kb())
    await callback.answer()
