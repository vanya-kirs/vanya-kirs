import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.api_client import BotApiClient
from app.bot.keyboards import (
    AdminCallback,
    GlobalSearchCallback,
    JoinQueueCallback,
    NavCallback,
    SourceCallback,
    SourcePageCallback,
    admin_menu_kb,
    global_search_menu_kb,
    global_search_sources_kb,
    join_queue_channel_kb,
    join_queue_list_kb,
    source_delete_confirm_kb,
    source_detail_kb,
    sources_list_kb,
)
from app.bot.states import JoinQueueStates, SourceStates
from aiogram.types import Document
from app.bot.texts import (
    ADMIN_MENU_TITLE,
    ADMIN_ONLY,
    ADMIN_PARSE_STATS,
    API_UNAVAILABLE,
    GLOBAL_SEARCH_EMPTY,
    GLOBAL_SEARCH_LIST,
    GLOBAL_SEARCH_MENU,
    INACTIVE_SOURCE_ITEM,
    INACTIVE_SOURCES_EMPTY,
    INACTIVE_SOURCES_TITLE,
    REJECTED_SOURCES_EMPTY,
    REJECTED_SOURCES_EXPORT_CAPTION,
    REJECTED_SOURCES_EXPORT_ERROR,
    REJECTED_SOURCES_MENU,
    SOURCES_EXPORT_CAPTION,
    SOURCES_EXPORT_ERROR,
    JOIN_QUEUE_CHANNEL,
    JOIN_QUEUE_EMPTY,
    JOIN_QUEUE_PRIORITY_INVALID,
    JOIN_QUEUE_PRIORITY_PROMPT,
    JOIN_QUEUE_TITLE,
    SOURCE_ADD_PROMPT,
    SOURCE_ADDED,
    SOURCE_DELETE_CONFIRM,
    SOURCE_DELETED,
    SOURCE_DETAIL,
    SOURCE_DETAIL_WITH_STATS,
    SOURCE_ERROR,
    SOURCE_FOUND,
    SOURCE_IMPORT_DONE,
    SOURCE_IMPORT_EMPTY,
    SOURCE_IMPORT_PROCESSING,
    SOURCE_IMPORT_PROMPT,
    SOURCE_IMPORT_UNSUPPORTED,
    SOURCE_LIST_EMPTY,
    SOURCE_NOT_FOUND,
    SOURCE_URL_INVALID,
    SOURCE_VALIDATING,
)
from app.bot.utils import format_datetime
from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = Router()

_URL_PREFIXES = ("@", "https://t.me/")
_SOURCES_PER_PAGE = 5


def _is_admin(telegram_id: int) -> bool:
    return telegram_id in get_settings().admin_ids


def _is_valid_url(url: str) -> bool:
    return url.strip().startswith(_URL_PREFIXES)


def _sources_page_text(sources: list, page: int) -> str:
    total_pages = max(1, (len(sources) + _SOURCES_PER_PAGE - 1) // _SOURCES_PER_PAGE)
    start = page * _SOURCES_PER_PAGE
    page_sources = sources[start : start + _SOURCES_PER_PAGE]

    lines = [f"Источники — стр. {page + 1}/{total_pages}:"]
    for i, src in enumerate(page_sources, start=start + 1):
        icon = "✅" if src.get("parsing_enabled", True) else "❌"
        lines.append(f"{i}. {icon} {src['name']} — {src['url']}")
    if page_sources:
        lines.append("\nНажми на кнопку для управления источником:")
    return "\n".join(lines)


def _source_detail_text(src: dict, stats: dict | None = None) -> str:
    parsing_enabled = src.get("parsing_enabled", True)
    icon = "✅" if parsing_enabled else "❌"
    base = {
        "name": src.get("name"),
        "url": src.get("url"),
        "parsing_status": f"{'ВКЛ' if parsing_enabled else 'ВЫКЛ'} {icon}",
        "last_parsed_at": format_datetime(src.get("last_parsed_at")),
    }
    if stats:
        return SOURCE_DETAIL_WITH_STATS.format(
            **base,
            total_messages=stats.get("total_messages", 0),
            scored_messages=stats.get("scored_messages", 0),
            leads_found=stats.get("leads_found", 0),
            messages_today=stats.get("messages_today", 0),
            scored_today=stats.get("scored_today", 0),
            leads_today=stats.get("leads_today", 0),
        )
    return SOURCE_DETAIL.format(**base)


# ---------------------------------------------------------------------------
# Admin entry point
# ---------------------------------------------------------------------------

@router.message(F.text == "Администрирование")
async def text_admin(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer(ADMIN_ONLY)
        return
    await message.answer(ADMIN_MENU_TITLE, reply_markup=admin_menu_kb())


@router.callback_query(NavCallback.filter(F.to == "admin"))
async def cb_back_to_admin(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(ADMIN_MENU_TITLE, reply_markup=admin_menu_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# Sources CSV export
# ---------------------------------------------------------------------------

@router.callback_query(AdminCallback.filter(F.action == "export_sources"))
async def cb_admin_export_sources(callback: CallbackQuery, api: BotApiClient) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return

    await callback.answer()
    try:
        xlsx_bytes = await api.export_sources_xlsx()
    except Exception as exc:
        logger.error("export_sources_xlsx error: %s", exc)
        await callback.message.answer(SOURCES_EXPORT_ERROR)
        return

    from aiogram.types import BufferedInputFile
    from datetime import datetime as _dt
    filename = f"sources_{_dt.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    await callback.message.answer_document(
        BufferedInputFile(xlsx_bytes, filename=filename),
        caption=SOURCES_EXPORT_CAPTION,
    )


# ---------------------------------------------------------------------------
# Rejected sources
# ---------------------------------------------------------------------------

@router.callback_query(AdminCallback.filter(F.action == "rejected_sources"))
async def cb_admin_rejected_sources(callback: CallbackQuery, api: BotApiClient) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return

    await callback.answer()
    try:
        total = await api.get_rejected_sources_count()
        too_small = await api.get_rejected_sources_count(reason="too_small")
        broadcast = await api.get_rejected_sources_count(reason="broadcast")
    except Exception as exc:
        logger.error("get_rejected_sources_count error: %s", exc)
        await callback.message.answer(API_UNAVAILABLE)
        return

    if total == 0:
        from aiogram.utils.keyboard import InlineKeyboardBuilder as KB
        builder = KB()
        builder.button(text="← Назад", callback_data=NavCallback(to="admin"))
        builder.adjust(1)
        await callback.message.edit_text(REJECTED_SOURCES_EMPTY, reply_markup=builder.as_markup())
        return

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from aiogram.utils.keyboard import InlineKeyboardBuilder as KB
    builder = KB()
    builder.button(
        text="📥 Скачать все (XLSX)",
        callback_data=AdminCallback(action="export_rejected"),
    )
    builder.button(
        text="📥 Только малые группы",
        callback_data=AdminCallback(action="export_rejected_small"),
    )
    builder.button(
        text="📥 Только каналы (не группы)",
        callback_data=AdminCallback(action="export_rejected_broadcast"),
    )
    builder.button(text="← Назад", callback_data=NavCallback(to="admin"))
    builder.adjust(1)

    await callback.message.edit_text(
        REJECTED_SOURCES_MENU.format(total=total, too_small=too_small, broadcast=broadcast),
        reply_markup=builder.as_markup(),
    )


async def _export_rejected(
    callback: CallbackQuery,
    api: BotApiClient,
    reason: str | None,
    min_members: int | None = None,
) -> None:
    from aiogram.types import BufferedInputFile
    from datetime import datetime as _dt
    try:
        xlsx_bytes = await api.export_rejected_sources_xlsx(reason=reason, min_members=min_members)
    except Exception as exc:
        logger.error("export_rejected_sources_xlsx error: %s", exc)
        await callback.message.answer(REJECTED_SOURCES_EXPORT_ERROR)
        return

    filename = f"rejected_sources_{_dt.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    await callback.message.answer_document(
        BufferedInputFile(xlsx_bytes, filename=filename),
        caption=REJECTED_SOURCES_EXPORT_CAPTION,
    )


@router.callback_query(AdminCallback.filter(F.action == "export_rejected"))
async def cb_export_rejected_all(callback: CallbackQuery, api: BotApiClient) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return
    await callback.answer()
    await _export_rejected(callback, api, reason=None)


@router.callback_query(AdminCallback.filter(F.action == "export_rejected_small"))
async def cb_export_rejected_small(callback: CallbackQuery, api: BotApiClient) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return
    await callback.answer()
    await _export_rejected(callback, api, reason="too_small")


@router.callback_query(AdminCallback.filter(F.action == "export_rejected_broadcast"))
async def cb_export_rejected_broadcast(callback: CallbackQuery, api: BotApiClient) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return
    await callback.answer()
    await _export_rejected(callback, api, reason="broadcast")


# ---------------------------------------------------------------------------
# Inactive (deactivated) sources
# ---------------------------------------------------------------------------

@router.callback_query(AdminCallback.filter(F.action == "inactive_sources"))
async def cb_admin_inactive_sources(callback: CallbackQuery, api: BotApiClient) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return
    await callback.answer()

    try:
        sources = await api.get_inactive_sources()
    except Exception as exc:
        logger.error("get_inactive_sources error: %s", exc)
        await callback.message.answer(API_UNAVAILABLE)
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder as KB
    builder = KB()
    builder.button(text="← Назад", callback_data=NavCallback(to="admin"))
    builder.adjust(1)

    if not sources:
        await callback.message.edit_text(INACTIVE_SOURCES_EMPTY, reply_markup=builder.as_markup())
        return

    lines = [
        INACTIVE_SOURCE_ITEM.format(
            url=s.get("url", ""),
            name=s.get("name", ""),
            status=s.get("status", "inactive"),
        )
        for s in sources[:50]
    ]
    text = INACTIVE_SOURCES_TITLE.format(count=len(sources), list="\n".join(lines))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Admin parse stats
# ---------------------------------------------------------------------------

@router.callback_query(AdminCallback.filter(F.action == "parse_stats"))
async def cb_admin_parse_stats(callback: CallbackQuery, api: BotApiClient) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return

    try:
        global_stats = await api.get_stats()
        source_stats = await api.get_source_stats()
    except Exception as exc:
        logger.error("get_stats/get_source_stats error: %s", exc)
        await callback.answer(API_UNAVAILABLE, show_alert=True)
        return

    lines = []
    for s in sorted(source_stats, key=lambda x: x.get("messages_today", 0), reverse=True):
        if s.get("messages_today", 0) > 0 or s.get("leads_today", 0) > 0:
            lines.append(
                f"• {s['name']}: просмотрено {s['messages_today']}, "
                f"ИИ {s['scored_today']}, лидов {s['leads_today']}"
            )

    sources_lines = "\n".join(lines) if lines else "Нет активности за сегодня"

    from aiogram.utils.keyboard import InlineKeyboardBuilder as KB
    builder = KB()
    builder.button(text="← Назад", callback_data=NavCallback(to="admin"))
    builder.adjust(1)

    await callback.message.edit_text(
        ADMIN_PARSE_STATS.format(
            messages_today=global_stats.get("messages_today", 0),
            scored_today=global_stats.get("scored_today", 0),
            leads_today=global_stats.get("leads_today", 0),
            sources_lines=sources_lines,
        ),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Global search
# ---------------------------------------------------------------------------

@router.callback_query(AdminCallback.filter(F.action == "global_search"))
async def cb_admin_global_search(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return
    await callback.message.edit_text(GLOBAL_SEARCH_MENU, reply_markup=global_search_menu_kb())
    await callback.answer()


@router.callback_query(GlobalSearchCallback.filter(F.action.in_({"view", "page"})))
async def cb_global_search_view(
    callback: CallbackQuery, callback_data: GlobalSearchCallback, api: BotApiClient
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return

    try:
        sources = await api.get_discovered_sources()
    except Exception as exc:
        logger.error("get_discovered_sources error: %s", exc)
        await callback.answer(API_UNAVAILABLE, show_alert=True)
        return

    if not sources:
        await callback.message.edit_text(
            GLOBAL_SEARCH_EMPTY, reply_markup=global_search_menu_kb()
        )
        await callback.answer()
        return

    page = callback_data.page
    total_pages = max(1, (len(sources) + _SOURCES_PER_PAGE - 1) // _SOURCES_PER_PAGE)
    page = min(page, total_pages - 1)

    text = GLOBAL_SEARCH_LIST.format(page=page + 1, total=total_pages, total_count=len(sources))
    await callback.message.edit_text(text, reply_markup=global_search_sources_kb(sources, page=page))
    await callback.answer()


# ---------------------------------------------------------------------------
# Sources — list
# ---------------------------------------------------------------------------

async def _show_sources_page(
    callback: CallbackQuery, api: BotApiClient, page: int, edit: bool = True
) -> None:
    """Fetch all sources and render the given page, editing or sending a message."""
    try:
        sources = await api.get_sources()
    except Exception as exc:
        logger.error("get_sources error: %s", exc)
        await callback.answer(API_UNAVAILABLE, show_alert=True)
        return

    if not sources:
        text = SOURCE_LIST_EMPTY
        kb = sources_list_kb([], page=0)
    else:
        # clamp page in case sources were deleted
        max_page = max(0, (len(sources) + _SOURCES_PER_PAGE - 1) // _SOURCES_PER_PAGE - 1)
        page = min(page, max_page)
        text = _sources_page_text(sources, page)
        kb = sources_list_kb(sources, page=page)

    if edit:
        await callback.message.edit_text(text, reply_markup=kb)
    else:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(AdminCallback.filter(F.action == "sources"))
async def cb_admin_sources(callback: CallbackQuery, api: BotApiClient) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return
    await _show_sources_page(callback, api, page=0, edit=True)


@router.callback_query(SourcePageCallback.filter())
async def cb_source_page(
    callback: CallbackQuery, callback_data: SourcePageCallback, api: BotApiClient
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return
    await _show_sources_page(callback, api, page=callback_data.page, edit=True)


# ---------------------------------------------------------------------------
# Sources — detail view
# ---------------------------------------------------------------------------

@router.callback_query(SourceCallback.filter(F.action == "detail"))
async def cb_source_detail(
    callback: CallbackQuery, callback_data: SourceCallback, api: BotApiClient
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return

    try:
        sources = await api.get_sources()
        src = next((s for s in sources if s["id"] == callback_data.id), None)
    except Exception as exc:
        logger.error("get_sources error: %s", exc)
        await callback.answer(API_UNAVAILABLE, show_alert=True)
        return

    if src is None:
        await callback.answer("Источник не найден", show_alert=True)
        return

    stats: dict | None = None
    try:
        all_stats = await api.get_source_stats()
        stats = next((s for s in all_stats if s["id"] == callback_data.id), None)
    except Exception as exc:
        logger.warning("get_source_stats error: %s", exc)

    await callback.message.edit_text(
        _source_detail_text(src, stats),
        reply_markup=source_detail_kb(src["id"], src.get("parsing_enabled", True), page=callback_data.page),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Sources — add (FSM)
# ---------------------------------------------------------------------------

@router.callback_query(SourceCallback.filter(F.action == "add"))
async def cb_source_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return
    await callback.message.answer(SOURCE_ADD_PROMPT)
    await state.set_state(SourceStates.waiting_url)
    await callback.answer()


@router.message(SourceStates.waiting_url)
async def state_source_url(message: Message, state: FSMContext, api: BotApiClient) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer(ADMIN_ONLY)
        await state.clear()
        return

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
    if not _is_admin(message.from_user.id):
        await message.answer(ADMIN_ONLY)
        await state.clear()
        return

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

    await state.clear()

    # Show updated list
    try:
        sources = await api.get_sources()
        last_page = max(0, (len(sources) + _SOURCES_PER_PAGE - 1) // _SOURCES_PER_PAGE - 1)
        text = SOURCE_ADDED.format(name=name) + "\n\n" + _sources_page_text(sources, last_page)
        await message.answer(text, reply_markup=sources_list_kb(sources, page=last_page))
    except Exception:
        await message.answer(SOURCE_ADDED.format(name=name))


# ---------------------------------------------------------------------------
# Sources — CSV/Excel import
# ---------------------------------------------------------------------------

@router.callback_query(SourceCallback.filter(F.action == "import"))
async def cb_source_import(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return
    await callback.message.answer(SOURCE_IMPORT_PROMPT)
    await state.set_state(SourceStates.waiting_import)
    await callback.answer()


@router.message(SourceStates.waiting_import)
async def state_source_import(message: Message, state: FSMContext, api: BotApiClient) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer(ADMIN_ONLY)
        await state.clear()
        return

    if not message.document:
        await message.answer(SOURCE_IMPORT_PROMPT)
        return

    filename = (message.document.file_name or "").lower().strip()
    mime_type = (message.document.mime_type or "").lower().strip()
    is_csv = filename.endswith(".csv") or mime_type in {
        "text/csv",
        "application/csv",
        "text/plain",
    }
    is_xlsx = filename.endswith(".xlsx") or mime_type in {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    }

    # Telegram may omit/normalize filename and MIME inconsistently.
    # If this is not confidently CSV, try parsing it as XLSX.
    if not (is_csv or is_xlsx):
        is_xlsx = True

    wait_msg = await message.answer(SOURCE_IMPORT_PROCESSING)

    import csv
    import io
    from io import BytesIO

    file_data = BytesIO()
    await message.bot.download(message.document, destination=file_data)
    file_data.seek(0)

    items: list[dict] = []
    _TG_PREFIXES = ("@", "https://t.me/", "http://t.me/")

    try:
        if is_csv:
            text = file_data.read().decode("utf-8-sig", errors="replace")
            reader = csv.reader(io.StringIO(text))
            for row in reader:
                if not row:
                    continue
                url = row[0].strip()
                name = row[1].strip() if len(row) > 1 else ""
                if url.startswith(_TG_PREFIXES):
                    items.append({"url": url, "name": name or None})
        else:
            try:
                import openpyxl
            except ModuleNotFoundError:
                logger.exception("openpyxl is not installed in bot runtime")
                await wait_msg.delete()
                await message.answer(
                    "Импорт Excel временно недоступен на сервере (не установлен openpyxl). "
                    "Отправь CSV или обнови окружение."
                )
                await state.clear()
                return
            try:
                wb = openpyxl.load_workbook(file_data, read_only=True, data_only=True)
            except Exception as exc:
                logger.error("xlsx parse error: %s", exc)
                await wait_msg.delete()
                await message.answer(
                    "Не удалось прочитать Excel-файл. "
                    "Проверь, что это настоящий .xlsx (Excel Workbook), "
                    "или отправь файл в CSV."
                )
                await state.clear()
                return
            ws = wb.active
            for row in ws.iter_rows(values_only=True):
                if not row or not row[0]:
                    continue
                url = str(row[0]).strip()
                name = str(row[1]).strip() if len(row) > 1 and row[1] else ""
                if url.startswith(_TG_PREFIXES):
                    items.append({"url": url, "name": name or None})
    except Exception as exc:
        logger.error("import file parse error: %s", exc)
        await wait_msg.delete()
        await message.answer(SOURCE_ERROR)
        await state.clear()
        return

    await wait_msg.delete()

    if not items:
        await message.answer(SOURCE_IMPORT_EMPTY)
        await state.clear()
        return

    try:
        result = await api.import_sources(items)
    except Exception as exc:
        logger.error("import_sources API error: %s", exc)
        await message.answer(API_UNAVAILABLE)
        await state.clear()
        return

    await message.answer(
        SOURCE_IMPORT_DONE.format(
            imported=result.get("imported", 0),
            skipped=result.get("skipped", 0),
            errors=len(result.get("errors", [])),
        )
    )
    await state.clear()

    # Show updated sources list
    try:
        sources = await api.get_sources()
        last_page = max(0, (len(sources) + _SOURCES_PER_PAGE - 1) // _SOURCES_PER_PAGE - 1)
        await message.answer(
            _sources_page_text(sources, last_page),
            reply_markup=sources_list_kb(sources, page=last_page),
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Sources — toggle parsing
# ---------------------------------------------------------------------------

@router.callback_query(SourceCallback.filter(F.action == "toggle"))
async def cb_source_toggle(
    callback: CallbackQuery, callback_data: SourceCallback, api: BotApiClient
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return

    try:
        src = await api.toggle_source_parsing(callback_data.id)
    except Exception as exc:
        logger.error("toggle_source_parsing error: %s", exc)
        await callback.answer(API_UNAVAILABLE, show_alert=True)
        return

    parsing_enabled = src.get("parsing_enabled", True)
    await callback.message.edit_text(
        _source_detail_text(src),
        reply_markup=source_detail_kb(callback_data.id, parsing_enabled, page=callback_data.page),
    )
    await callback.answer(f"Парсинг {'ВКЛ' if parsing_enabled else 'ВЫКЛ'}")


# ---------------------------------------------------------------------------
# Sources — delete (inline confirm)
# ---------------------------------------------------------------------------

@router.callback_query(SourceCallback.filter(F.action == "delete"))
async def cb_source_delete(
    callback: CallbackQuery, callback_data: SourceCallback, api: BotApiClient
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return

    # Fetch name for confirm message
    name = ""
    try:
        sources = await api.get_sources()
        src = next((s for s in sources if s["id"] == callback_data.id), None)
        if src:
            name = src.get("name", "")
    except Exception:
        pass

    await callback.message.edit_text(
        SOURCE_DELETE_CONFIRM.format(name=name or f"#{callback_data.id}"),
        reply_markup=source_delete_confirm_kb(callback_data.id, page=callback_data.page),
    )
    await callback.answer()


@router.callback_query(SourceCallback.filter(F.action == "del_yes"))
async def cb_source_delete_confirm(
    callback: CallbackQuery, callback_data: SourceCallback, api: BotApiClient
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return

    try:
        await api.delete_source(callback_data.id)
    except Exception as exc:
        logger.error("delete_source error: %s", exc)
        await callback.answer(SOURCE_ERROR, show_alert=True)
        return

    await callback.answer(SOURCE_DELETED)
    # Show updated list (source is gone now)
    await _show_sources_page(callback, api, page=callback_data.page, edit=True)


@router.callback_query(SourceCallback.filter(F.action == "del_no"))
async def cb_source_delete_cancel(
    callback: CallbackQuery, callback_data: SourceCallback, api: BotApiClient
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return

    # Return to detail view
    try:
        sources = await api.get_sources()
        src = next((s for s in sources if s["id"] == callback_data.id), None)
    except Exception as exc:
        logger.error("get_sources error: %s", exc)
        await callback.answer(API_UNAVAILABLE, show_alert=True)
        return

    if src is None:
        await _show_sources_page(callback, api, page=callback_data.page, edit=True)
        return

    await callback.message.edit_text(
        _source_detail_text(src),
        reply_markup=source_detail_kb(src["id"], src.get("parsing_enabled", True), page=callback_data.page),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Join queue management
# ---------------------------------------------------------------------------

async def _get_rate_limiter():
    from app.core.config import get_settings
    from app.parser.rate_limiter import ParserRateLimiter
    settings = get_settings()
    return ParserRateLimiter(redis_url=settings.REDIS_URL)


@router.callback_query(AdminCallback.filter(F.action == "join_queue"))
async def cb_admin_join_queue(callback: CallbackQuery, api: BotApiClient) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return
    await _show_join_queue(callback, api)


@router.callback_query(JoinQueueCallback.filter(F.action == "list"))
async def cb_join_queue_list(callback: CallbackQuery, api: BotApiClient) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return
    await _show_join_queue(callback, api)


async def _show_join_queue(callback: CallbackQuery, api: BotApiClient) -> None:
    rate_limiter = await _get_rate_limiter()
    queue_items = await rate_limiter.list_queue()
    join_count = await rate_limiter.get_join_count()
    req_count = await rate_limiter.get_request_count()

    if not queue_items:
        await callback.message.edit_text(
            JOIN_QUEUE_EMPTY,
            reply_markup=admin_menu_kb(),
        )
        await callback.answer()
        return

    try:
        sources = await api.get_sources()
    except Exception:
        await callback.answer(API_UNAVAILABLE, show_alert=True)
        return

    source_map = {s["id"]: s["name"] for s in sources}
    enriched = [
        (sid, source_map.get(sid, f"source#{sid}"), priority)
        for sid, priority in queue_items
    ]

    text = JOIN_QUEUE_TITLE.format(
        count=len(queue_items),
        join_count=join_count,
        req_count=req_count,
    )
    await callback.message.edit_text(text, reply_markup=join_queue_list_kb(enriched))
    await callback.answer()


@router.callback_query(JoinQueueCallback.filter(F.action == "detail"))
async def cb_join_queue_detail(
    callback: CallbackQuery, callback_data: JoinQueueCallback, api: BotApiClient
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return

    try:
        sources = await api.get_sources()
    except Exception:
        await callback.answer(API_UNAVAILABLE, show_alert=True)
        return

    src = next((s for s in sources if s["id"] == callback_data.source_id), None)
    name = src["url"] if src else f"source#{callback_data.source_id}"

    text = JOIN_QUEUE_CHANNEL.format(name=name.lstrip("@"), priority=callback_data.priority)
    await callback.message.edit_text(
        text,
        reply_markup=join_queue_channel_kb(callback_data.source_id, callback_data.priority),
    )
    await callback.answer()


@router.callback_query(JoinQueueCallback.filter(F.action == "priority"))
async def cb_join_queue_set_priority(
    callback: CallbackQuery,
    callback_data: JoinQueueCallback,
    state: FSMContext,
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return

    if callback_data.priority == 0:
        await state.set_state(JoinQueueStates.waiting_priority)
        await state.update_data(source_id=callback_data.source_id)
        await callback.message.answer(JOIN_QUEUE_PRIORITY_PROMPT)
        await callback.answer()
        return

    rate_limiter = await _get_rate_limiter()
    await rate_limiter.set_priority(callback_data.source_id, callback_data.priority)
    logger.info("[BOT] priority=%d for source_id=%d", callback_data.priority, callback_data.source_id)
    await callback.answer(f"Приоритет {callback_data.priority} установлен", show_alert=True)


@router.message(JoinQueueStates.waiting_priority)
async def state_join_queue_priority(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer(ADMIN_ONLY)
        await state.clear()
        return

    text = (message.text or "").strip()
    try:
        priority = int(text)
        if not (1 <= priority <= 99):
            raise ValueError
    except ValueError:
        await message.answer(JOIN_QUEUE_PRIORITY_INVALID)
        return

    data = await state.get_data()
    source_id = data["source_id"]
    await state.clear()

    rate_limiter = await _get_rate_limiter()
    await rate_limiter.set_priority(source_id, priority)
    logger.info("[BOT] priority=%d for source_id=%d", priority, source_id)
    await message.answer(f"Приоритет {priority} установлен для source_id={source_id}")


@router.callback_query(JoinQueueCallback.filter(F.action == "remove"))
async def cb_join_queue_remove(
    callback: CallbackQuery,
    callback_data: JoinQueueCallback,
    api: BotApiClient,
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer(ADMIN_ONLY, show_alert=True)
        return

    rate_limiter = await _get_rate_limiter()
    await rate_limiter.dequeue_join(callback_data.source_id)
    logger.info("[BOT] removed source_id=%d from join queue", callback_data.source_id)
    await callback.answer("Убрано из очереди", show_alert=True)
    await _show_join_queue(callback, api)
