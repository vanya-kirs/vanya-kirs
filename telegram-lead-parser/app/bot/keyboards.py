from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ---------------------------------------------------------------------------
# CallbackData factories
# ---------------------------------------------------------------------------

class NavCallback(CallbackData, prefix="nav"):
    to: str  # "menu" | "admin"


class AdminCallback(CallbackData, prefix="adm"):
    action: str  # sources


class ProfileCallback(CallbackData, prefix="prof"):
    action: str  # subscribe | toggle_parsing


class SourceCallback(CallbackData, prefix="src"):
    action: str  # add | detail | toggle | delete | del_yes | del_no | import
    id: int = 0
    page: int = 0  # list page to return to


class SourcePageCallback(CallbackData, prefix="srcp"):
    page: int = 0


class CriteriaCallback(CallbackData, prefix="crit"):
    action: str  # add | list | activate | act_yes | act_no
    id: int = 0


class ScoreCallback(CallbackData, prefix="score"):
    value: int


class LeadCallback(CallbackData, prefix="lead"):
    action: str   # accept | reject | restore | export
    id: int = 0
    offset: int = 0
    status: str = "new"
    min_score: int = 0


class LeadPageCallback(CallbackData, prefix="lp"):
    offset: int
    status: str   # "new" | "top" | "rejected"
    min_score: int = 0


class LeadViewCallback(CallbackData, prefix="lvw"):
    lead_id: int
    view: str       # "card" | "message"
    offset: int
    status: str
    min_score: int = 0


class JoinQueueCallback(CallbackData, prefix="jq"):
    action: str   # list | detail | priority | remove
    source_id: int = 0
    priority: int = 0


class GlobalSearchCallback(CallbackData, prefix="gsr"):
    action: str  # view | trigger | page
    page: int = 0


# ---------------------------------------------------------------------------
# Reply keyboards
# ---------------------------------------------------------------------------

def main_menu_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="Лиды"), KeyboardButton(text="Статистика")],
        [KeyboardButton(text="Профиль")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="Администрирование")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def admin_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Источники", callback_data=AdminCallback(action="sources"))
    builder.button(text="📊 Статистика парсера", callback_data=AdminCallback(action="parse_stats"))
    builder.button(text="📤 Экспорт каналов", callback_data=AdminCallback(action="export_sources"))
    builder.button(text="🔍 Найденные каналы", callback_data=AdminCallback(action="global_search"))
    builder.button(text="📋 Очередь вступлений", callback_data=AdminCallback(action="join_queue"))
    builder.button(text="🚫 Отклонённые каналы", callback_data=AdminCallback(action="rejected_sources"))
    builder.button(text="🔴 Деактивированные", callback_data=AdminCallback(action="inactive_sources"))
    builder.button(text="Назад в меню", callback_data=NavCallback(to="menu"))
    builder.adjust(1)
    return builder.as_markup()


def global_search_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Найденные каналы", callback_data=GlobalSearchCallback(action="view"))
    builder.button(text="← Назад", callback_data=NavCallback(to="admin"))
    builder.adjust(1)
    return builder.as_markup()


def global_search_sources_kb(sources: list, page: int = 0) -> InlineKeyboardMarkup:
    start = page * _SOURCES_PER_PAGE
    page_sources = sources[start : start + _SOURCES_PER_PAGE]
    total_pages = max(1, (len(sources) + _SOURCES_PER_PAGE - 1) // _SOURCES_PER_PAGE)

    rows: list[list[InlineKeyboardButton]] = []
    for src in page_sources:
        icon = "✅" if src.get("parsing_enabled", True) else "❌"
        rows.append([
            InlineKeyboardButton(
                text=f"{icon} {src['name']}",
                callback_data=SourceCallback(action="detail", id=src["id"], page=page).pack(),
            )
        ])

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="← Пред", callback_data=GlobalSearchCallback(action="page", page=page - 1).pack()))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="След →", callback_data=GlobalSearchCallback(action="page", page=page + 1).pack()))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="← Назад", callback_data=AdminCallback(action="global_search").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Inline keyboards
# ---------------------------------------------------------------------------

_SOURCES_PER_PAGE = 5


def sources_list_kb(sources: list, page: int = 0) -> InlineKeyboardMarkup:
    """Paginated source list: up to 5 sources as buttons, nav row, add + back."""
    start = page * _SOURCES_PER_PAGE
    page_sources = sources[start : start + _SOURCES_PER_PAGE]
    total_pages = max(1, (len(sources) + _SOURCES_PER_PAGE - 1) // _SOURCES_PER_PAGE)

    rows: list[list[InlineKeyboardButton]] = []
    for src in page_sources:
        icon = "✅" if src.get("parsing_enabled", True) else "❌"
        rows.append([
            InlineKeyboardButton(
                text=f"{icon} {src['name']}",
                callback_data=SourceCallback(action="detail", id=src["id"], page=page).pack(),
            )
        ])

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="← Пред", callback_data=SourcePageCallback(page=page - 1).pack()))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="След →", callback_data=SourcePageCallback(page=page + 1).pack()))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="Добавить источник", callback_data=SourceCallback(action="add").pack())])
    rows.append([InlineKeyboardButton(text="📎 Импорт из CSV/Excel", callback_data=SourceCallback(action="import").pack())])
    rows.append([InlineKeyboardButton(text="← Назад в меню", callback_data=NavCallback(to="admin").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def source_detail_kb(source_id: int, parsing_enabled: bool, page: int = 0) -> InlineKeyboardMarkup:
    """Single source actions: toggle parsing, delete, back to list."""
    toggle_label = "Парсинг: ВКЛ → выключить" if parsing_enabled else "Парсинг: ВЫКЛ → включить"
    builder = InlineKeyboardBuilder()
    builder.button(text=toggle_label, callback_data=SourceCallback(action="toggle", id=source_id, page=page))
    builder.button(text="Удалить источник", callback_data=SourceCallback(action="delete", id=source_id, page=page))
    builder.button(text="← К списку", callback_data=SourcePageCallback(page=page))
    builder.adjust(1)
    return builder.as_markup()


def source_delete_confirm_kb(source_id: int, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, удалить", callback_data=SourceCallback(action="del_yes", id=source_id, page=page))
    builder.button(text="Отмена", callback_data=SourceCallback(action="del_no", id=source_id, page=page))
    builder.adjust(2)
    return builder.as_markup()


def criteria_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Создать профиль", callback_data=CriteriaCallback(action="add"))
    builder.button(text="Мои профили", callback_data=CriteriaCallback(action="list"))
    builder.button(text="Назад", callback_data=NavCallback(to="menu"))
    builder.adjust(1)
    return builder.as_markup()


def criteria_actions_kb(criteria_id: int, is_active: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not is_active:
        builder.button(
            text="Сделать активным",
            callback_data=CriteriaCallback(action="activate", id=criteria_id),
        )
    builder.button(text="Назад к списку", callback_data=CriteriaCallback(action="list"))
    builder.adjust(1)
    return builder.as_markup()


def criteria_activate_confirm_kb(criteria_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Да, активировать",
        callback_data=CriteriaCallback(action="act_yes", id=criteria_id),
    )
    builder.button(
        text="Нет",
        callback_data=CriteriaCallback(action="act_no"),
    )
    builder.adjust(2)
    return builder.as_markup()


def leads_menu_kb(min_score: int = 40) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"Новые лиды (от {min_score})",
        callback_data=LeadPageCallback(offset=0, status="new", min_score=min_score),
    )
    builder.button(
        text="Топ лиды (80+)",
        callback_data=LeadPageCallback(offset=0, status="top", min_score=80),
    )
    builder.button(
        text="Принятые лиды",
        callback_data=LeadPageCallback(offset=0, status="contacted", min_score=min_score),
    )
    builder.button(
        text=f"Отклонённые (от {min_score})",
        callback_data=LeadPageCallback(offset=0, status="rejected", min_score=min_score),
    )
    builder.button(
        text="Экспорт CSV",
        callback_data=LeadCallback(action="export", min_score=min_score),
    )
    builder.button(text="Назад", callback_data=NavCallback(to="menu"))
    builder.adjust(1)
    return builder.as_markup()


def lead_card_kb(
    lead_id: int,
    offset: int,
    status: str,
    min_score: int = 0,
    view: str = "card",
    has_prev: bool = False,
    has_next: bool = False,
) -> InlineKeyboardMarkup:
    """Lead card keyboard: action buttons + prev/next nav + view toggle + back to list."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text="Лид подходит ✅",
        callback_data=LeadCallback(
            action="accept", id=lead_id, offset=offset, status=status, min_score=min_score
        ),
    )
    if status != "rejected":
        builder.button(
            text="Не подходит ❌",
            callback_data=LeadCallback(
                action="reject", id=lead_id, offset=offset, status=status, min_score=min_score
            ),
        )
        builder.adjust(2)
    else:
        builder.adjust(1)

    nav_row: list[InlineKeyboardButton] = []
    if has_prev:
        nav_row.append(
            InlineKeyboardButton(
                text="← Пред",
                callback_data=LeadPageCallback(
                    offset=offset - 1, status=status, min_score=min_score
                ).pack(),
            )
        )
    if has_next:
        nav_row.append(
            InlineKeyboardButton(
                text="След →",
                callback_data=LeadPageCallback(
                    offset=offset + 1, status=status, min_score=min_score
                ).pack(),
            )
        )

    next_view = "message" if view == "card" else "card"
    toggle_text = "📄 Сообщение" if view == "card" else "🤖 Вывод ИИ"
    bottom_row = [
        InlineKeyboardButton(
            text=toggle_text,
            callback_data=LeadViewCallback(
                lead_id=lead_id, view=next_view,
                offset=offset, status=status, min_score=min_score,
            ).pack(),
        ),
        InlineKeyboardButton(
            text="К списку",
            callback_data=NavCallback(to="leads").pack(),
        ),
    ]

    current_kb = builder.export()
    if nav_row:
        current_kb.append(nav_row)
    current_kb.append(bottom_row)
    return InlineKeyboardMarkup(inline_keyboard=current_kb)


def lead_nav_only_kb(
    offset: int,
    status: str,
    has_prev: bool,
    has_next: bool,
    min_score: int = 0,
    lead_id: int | None = None,
    view: str = "card",
) -> InlineKeyboardMarkup:
    """Navigation keyboard with optional card/message toggle."""
    nav = []
    if has_prev:
        nav.append(
            InlineKeyboardButton(
                text="← Пред",
                callback_data=LeadPageCallback(
                    offset=offset - 1, status=status, min_score=min_score
                ).pack(),
            )
        )
    if has_next:
        nav.append(
            InlineKeyboardButton(
                text="След →",
                callback_data=LeadPageCallback(
                    offset=offset + 1, status=status, min_score=min_score
                ).pack(),
            )
        )
    nav.append(
        InlineKeyboardButton(
            text="К списку",
            callback_data=NavCallback(to="leads").pack(),
        )
    )
    rows = [nav]
    if lead_id is not None:
        next_view = "message" if view == "card" else "card"
        toggle_text = "📄 Сообщение" if view == "card" else "🤖 Вывод ИИ"
        rows.append([
            InlineKeyboardButton(
                text=toggle_text,
                callback_data=LeadViewCallback(
                    lead_id=lead_id,
                    view=next_view,
                    offset=offset,
                    status=status,
                    min_score=min_score,
                ).pack(),
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def score_selector_kb(current: int = 0) -> InlineKeyboardMarkup:
    scores = [40, 50, 60, 70, 80]
    builder = InlineKeyboardBuilder()
    for s in scores:
        label = f"{'✓ ' if s == current else ''}{s}"
        builder.button(text=label, callback_data=ScoreCallback(value=s))
    builder.adjust(4)
    builder.row(InlineKeyboardButton(text="Назад", callback_data=NavCallback(to="profile").pack()))
    return builder.as_markup()


def profile_kb(parsing_enabled: bool) -> InlineKeyboardMarkup:
    parsing_label = "Парсинг: ВКЛ  →  выключить" if parsing_enabled else "Парсинг: ВЫКЛ  →  включить"
    builder = InlineKeyboardBuilder()
    builder.button(text="Оплатить подписку (30 дней)", callback_data=ProfileCallback(action="subscribe"))
    builder.button(text=parsing_label, callback_data=ProfileCallback(action="toggle_parsing"))
    builder.button(text="Настроить порог лидов", callback_data=ProfileCallback(action="set_score"))
    builder.button(text="Назад", callback_data=NavCallback(to="menu"))
    builder.adjust(1)
    return builder.as_markup()


def join_queue_list_kb(
    queue_items: list[tuple[int, str, int]],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for source_id, name, priority in queue_items:
        fire = " 🔥" if priority <= 10 else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{name} [приоритет: {priority}]{fire}",
                callback_data=JoinQueueCallback(
                    action="detail", source_id=source_id, priority=priority
                ).pack(),
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="← Назад", callback_data=NavCallback(to="admin").pack()
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def join_queue_channel_kb(source_id: int, priority: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔥 Срочно (1)",
        callback_data=JoinQueueCallback(action="priority", source_id=source_id, priority=1),
    )
    builder.button(
        text="→ Обычный (50)",
        callback_data=JoinQueueCallback(action="priority", source_id=source_id, priority=50),
    )
    builder.button(
        text="⬇ Последний (99)",
        callback_data=JoinQueueCallback(action="priority", source_id=source_id, priority=99),
    )
    builder.button(
        text="✏️ Свой приоритет",
        callback_data=JoinQueueCallback(action="priority", source_id=source_id, priority=0),
    )
    builder.button(
        text="✕ Убрать",
        callback_data=JoinQueueCallback(action="remove", source_id=source_id),
    )
    builder.button(
        text="← Назад",
        callback_data=JoinQueueCallback(action="list"),
    )
    builder.adjust(3, 1, 1, 1)
    return builder.as_markup()
