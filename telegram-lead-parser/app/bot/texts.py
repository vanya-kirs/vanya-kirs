# All bot message texts as constants

# --- Start / Help ---
WELCOME = (
    "Привет, {first_name}!\n"
    "Я помогу найти лидов в Telegram.\n"
    "Используй меню для управления."
)
HELP_TEXT = (
    "Доступные разделы:\n\n"
    "Лиды — просматривать и управлять найденными лидами\n"
    "Статистика — общая сводка системы\n"
    "Запустить парсинг — собрать новые сообщения прямо сейчас\n\n"
    "Команды:\n"
    "/start — главное меню\n"
    "/help — эта справка"
)

# --- Stats ---
STATS_TEXT = (
    "Мои лиды:\n\n"
    "Всего найдено: {total_leads}\n"
    "Новых (не просмотрено): {new}\n"
    "Просмотрено: {viewed}\n"
    "Принято: {contacted}\n"
    "Отклонено: {rejected}"
)
PARSE_ALL_STARTED = "Парсинг запущен для {count} источников"
PARSE_ALL_NO_SOURCES = "Нет активных источников. Сначала добавь источник."

# --- Sources ---
SOURCE_MENU_TITLE = "Управление источниками:"
SOURCE_ADD_PROMPT = (
    "Отправь ссылку на Telegram чат или канал.\n"
    "Форматы: https://t.me/name или @name"
)
SOURCE_URL_INVALID = (
    "Неверный формат. Отправь ссылку вида:\n"
    "https://t.me/name или @name"
)
SOURCE_VALIDATING = "Проверяю доступность чата..."
SOURCE_NOT_FOUND = "Чат не найден или недоступен: {error}"
SOURCE_FOUND = (
    "Чат найден: {title} ({members_count} участников)\n"
    "Теперь дай название этому источнику:"
)
SOURCE_NAME_PROMPT = "Введи название источника:"
SOURCE_ADDED = "Источник {name} добавлен!"
SOURCE_LIST_EMPTY = "Источников нет. Добавь первый!"
SOURCE_ITEM = "{name} — {url}\nПоследний парсинг: {last_parsed_at}"
SOURCE_PARSE_STARTED = "Парсинг запущен!\ntask_id: {task_id}"
SOURCE_DETAIL = (
    "Источник: {name}\n"
    "Ссылка: {url}\n"
    "Парсинг: {parsing_status}\n"
    "Последний парсинг: {last_parsed_at}"
)
SOURCE_DETAIL_WITH_STATS = (
    "Источник: {name}\n"
    "Ссылка: {url}\n"
    "Парсинг: {parsing_status}\n"
    "Последний парсинг: {last_parsed_at}\n\n"
    "За всё время:\n"
    "  Постов: {total_messages}\n"
    "  Дошло до ИИ: {scored_messages}\n"
    "  Лидов: {leads_found}\n\n"
    "Сегодня:\n"
    "  Постов: {messages_today}\n"
    "  Дошло до ИИ: {scored_today}\n"
    "  Лидов: {leads_today}"
)
ADMIN_PARSE_STATS = (
    "Статистика парсера за сегодня:\n\n"
    "Постов просмотрено: {messages_today}\n"
    "Дошло до ИИ: {scored_today}\n"
    "Лидов найдено: {leads_today}\n\n"
    "{sources_lines}"
)
ADMIN_PARSE_RUN_STARTED = "Парсинг запущен для {count} источников."
ADMIN_PARSE_RUN_EMPTY = "Нет активных источников для парсинга."
ADMIN_PARSE_RUN_ERROR = "Не удалось запустить парсинг. Попробуй позже."
SOURCES_EXPORT_CAPTION = "Список каналов (вручную + автопоиск)"
SOURCES_EXPORT_ERROR = "Не удалось выгрузить каналы. Попробуй позже."
REJECTED_SOURCES_MENU = (
    "Отклонённые каналы:\n\n"
    "Всего: {total}\n"
    "Мало участников: {too_small}\n"
    "Широковещательные (не группа): {broadcast}"
)
REJECTED_SOURCES_EMPTY = "Отклонённых каналов пока нет. Они появятся после запуска задач расширения."
REJECTED_SOURCES_EXPORT_CAPTION = "Отклонённые каналы (мало участников + каналы без чата)"
REJECTED_SOURCES_EXPORT_ERROR = "Не удалось выгрузить отклонённые каналы. Попробуй позже."
GLOBAL_SEARCH_MENU = "Глобальный поиск по ключевым словам:"
GLOBAL_SEARCH_TRIGGERED = "Поиск запущен в фоне. Найденные каналы появятся в разделе «Найденные каналы»."
GLOBAL_SEARCH_TRIGGER_ERROR = "Не удалось запустить поиск. Попробуй позже."
GLOBAL_SEARCH_EMPTY = "Найденных каналов пока нет. Запусти поиск."
GLOBAL_SEARCH_LIST = "Найденные каналы (стр. {page}/{total}):\nВсего: {total_count}"
SOURCE_DELETE_CONFIRM = "Удалить источник \"{name}\"?\nЛиды сохранятся."
SOURCE_DELETED = "Источник удалён"
SOURCE_ERROR = "Ошибка при работе с источником. Попробуй позже."
SOURCE_IMPORT_PROMPT = (
    "Отправь файл CSV или Excel (.xlsx) со списком источников.\n\n"
    "Формат: первый столбец — ссылка (@name или https://t.me/name), "
    "второй столбец — название (необязательно).\n\n"
    "Пример строки:\n@some_channel, Крутой канал"
)
SOURCE_IMPORT_PROCESSING = "Обрабатываю файл..."
SOURCE_IMPORT_DONE = (
    "Импорт завершён:\n\n"
    "Добавлено: {imported}\n"
    "Пропущено (уже есть): {skipped}\n"
    "Ошибок: {errors}"
)
SOURCE_IMPORT_EMPTY = "Не найдено корректных URL. Проверь формат файла."
SOURCE_IMPORT_UNSUPPORTED = "Поддерживаются только файлы .csv и .xlsx"

# --- Criteria ---
CRITERIA_MENU_TITLE = "Управление критериями:"
CRITERIA_ACTIVE_INFO = "Активный профиль: {name} (score >= {min_score})"
CRITERIA_NO_ACTIVE = "Активного профиля нет. Создай первый!"
CRITERIA_ADD_NAME = (
    "Введи название профиля критериев.\n"
    "Пример: Предприниматели"
)
CRITERIA_ADD_DESC = (
    "Опиши целевую аудиторию своими словами.\n"
    "Кого ищем? Какие признаки важны?\n\n"
    "Пример: Предприниматели с опытом, которым тесно "
    "в текущей нише и хотят масштаба"
)
CRITERIA_ADD_SCORE = (
    "Минимальный score для лида? (40-80)\n"
    "Рекомендую 60 — отправь 60 или своё значение"
)
CRITERIA_SCORE_INVALID = "Введи число от 40 до 80:"
CRITERIA_CREATED = "Профиль создан! Сделать его активным?"
CRITERIA_ACTIVATED = "Профиль создан и активирован!"
CRITERIA_CREATED_NOT_ACTIVE = "Профиль создан (не активирован)."
CRITERIA_LIST_EMPTY = "Профилей нет. Создай первый!"
CRITERIA_ITEM = "{active_mark}{name}\nScore порог: {min_score}\n{description}"
CRITERIA_ACTIVATE_DONE = "Профиль активирован!"
CRITERIA_ERROR = "Ошибка при работе с критериями. Попробуй позже."

# --- Leads ---
LEADS_MENU_TITLE = (
    "Лиды:\n\n"
    "Новых: {new}\n"
    "Просмотрено: {viewed}\n"
    "Контакт: {contacted}\n"
    "Отклонено: {rejected}"
)
LEADS_EMPTY = "Новых лидов нет."
LEADS_TOP_EMPTY = "Лидов с оценкой 80+ нет."
LEADS_REJECTED_EMPTY = "Отклонённых лидов нет."
LEADS_CONTACTED_EMPTY = "Принятых лидов нет."

LEAD_CARD = (
    "Лид #{id} | Оценка: {score}/100\n\n"
    "Проблема:\n{reason}\n\n"
    "Сигналы: {signals}\n\n"
    "Найдено: {time_ago}"
)

LEAD_CONTACT_CARD = (
    "Лид #{id} | Оценка: {score}/100\n\n"
    "Сообщение из {source_name}:\n"
    "<i>{message_text}</i>\n\n"
    "Имя: {sender_name}\n"
    "Username: {sender_username}\n"
    "Телефон: {sender_phone}\n"
    "Telegram: {tg_link}\n"
    "Найдено: {time_ago}"
)

LEAD_MESSAGE_VIEW = (
    "Лид #{id} | Оценка: {score}/100\n\n"
    "Сообщение из {source_name}:\n"
    "<i>{message_text}</i>\n\n"
    "Дата: {tg_date}\n"
    "Найдено: {time_ago}"
)

LEAD_ACCEPTED = "Лид принят"
LEAD_REJECTED = "Лид отклонён. Его можно найти в разделе Отклоненные лиды."
LEAD_RESTORED = "Лид восстановлен"
LEADS_EXPORT_CAPTION = "Экспорт лидов"
LEADS_EXPORT_ERROR = "Ошибка при экспорте. Попробуй позже."
LEAD_ERROR = "Ошибка при работе с лидами. Попробуй позже."

# Deprecated (kept for compat)
LEAD_VIEWED = "Отмечен как просмотренный"
LEAD_CONTACTED = "Контакт установлен!"

# --- Profile ---
PROFILE_TEXT = (
    "Профиль\n\n"
    "Пользователь: {username}\n"
    "Подписка: {subscription_status}\n"
    "Парсинг: {parsing_status}\n"
    "Мин. score лидов: {min_score}"
)
PROFILE_SUB_ACTIVE = "Активна до {date}"
PROFILE_SUB_INACTIVE = "Не активна"
PROFILE_PARSING_ON = "Включен"
PROFILE_PARSING_OFF = "Выключен"
PROFILE_SUBSCRIBED = "Подписка продлена на 30 дней!\nАктивна до {date}"
PROFILE_PARSING_TOGGLED_ON = "Парсинг включён"
PROFILE_PARSING_TOGGLED_OFF = "Парсинг выключен"
PROFILE_MIN_SCORE = "Минимальный порог: {min_score}/100"
PROFILE_SCORE_SET = "Порог лидов установлен: {score}/100"
PROFILE_SCORE_PROMPT = (
    "Выбери минимальный score лидов:\n\n"
    "Рекомендуемый диапазон: 50–60\n"
    "Чем выше — тем меньше, но точнее лиды."
)

# --- Admin ---
ADMIN_MENU_TITLE = "Панель администратора:"
ADMIN_ONLY = "Эта функция доступна только администраторам."

# --- Join Queue ---
JOIN_QUEUE_TITLE = "📋 Очередь вступлений ({count} каналов)\n\nВступлений сегодня: {join_count}/5  |  Запросов в час: {req_count}/30"
JOIN_QUEUE_EMPTY = "📋 Очередь вступлений пуста"
JOIN_QUEUE_CHANNEL = "@{name}  [приоритет: {priority}]"
JOIN_QUEUE_PRIORITY_PROMPT = "Введи число от 1 до 99:"
JOIN_QUEUE_PRIORITY_INVALID = "Неверный формат. Введи число от 1 до 99:"
JOIN_QUEUE_PRIORITY_SET = "Приоритет {priority} установлен для {name}"
JOIN_QUEUE_REMOVED = "Источник {name} убран из очереди"

# --- Inactive sources ---
INACTIVE_SOURCES_TITLE = "🔴 Деактивированные источники ({count}):\n\n{list}"
INACTIVE_SOURCES_EMPTY = "Деактивированных источников нет."
INACTIVE_SOURCE_ITEM = "• <code>{url}</code> — {name} (статус: {status})"

# --- System ---
API_UNAVAILABLE = "Сервис временно недоступен. Попробуй позже."
BOT_STARTED = "Бот запущен"
BACK_BTN = "Назад"
YES_BTN = "Да"
NO_BTN = "Нет"
