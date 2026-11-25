import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.api_client import BotApiClient
from app.bot.keyboards import NavCallback, main_menu_kb
from app.bot.texts import (
    API_UNAVAILABLE,
    HELP_TEXT,
    PARSE_ALL_NO_SOURCES,
    PARSE_ALL_STARTED,
    WELCOME,
)
from app.bot.utils import format_stats
from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = Router()


def _is_admin(telegram_id: int) -> bool:
    return telegram_id in get_settings().admin_ids


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    first_name = message.from_user.first_name if message.from_user else "пользователь"
    is_admin = _is_admin(message.from_user.id) if message.from_user else False
    await message.answer(
        WELCOME.format(first_name=first_name),
        reply_markup=main_menu_kb(is_admin=is_admin),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(F.text == "Статистика")
async def text_stats(message: Message, api: BotApiClient) -> None:
    try:
        stats = await api.get_stats()
        await message.answer(format_stats(stats))
    except Exception as exc:
        logger.error("Stats error: %s", exc)
        await message.answer(API_UNAVAILABLE)


@router.message(F.text == "Запустить парсинг")
async def text_parse_all(message: Message, api: BotApiClient) -> None:
    try:
        tasks = await api.run_parse_all()
        if not tasks:
            await message.answer(PARSE_ALL_NO_SOURCES)
        else:
            await message.answer(PARSE_ALL_STARTED.format(count=len(tasks)))
    except Exception as exc:
        logger.error("Parse all error: %s", exc)
        await message.answer(API_UNAVAILABLE)


@router.callback_query(NavCallback.filter(F.to == "menu"))
async def cb_back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    is_admin = _is_admin(callback.from_user.id) if callback.from_user else False
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb(is_admin=is_admin))
    await callback.answer()
