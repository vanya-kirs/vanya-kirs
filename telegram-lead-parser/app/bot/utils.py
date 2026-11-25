import html
import re
from datetime import datetime, timezone


def format_datetime(dt: datetime | str | None) -> str:
    if dt is None:
        return "никогда"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return dt
    return dt.strftime("%d.%m.%Y %H:%M")


def format_time_ago(dt_str: str | None) -> str:
    """Return human-readable 'X дней/часов/минут назад'."""
    if not dt_str:
        return "неизвестно"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt
        total_seconds = int(diff.total_seconds())
        if total_seconds < 60:
            return "только что"
        if total_seconds < 3600:
            m = total_seconds // 60
            return f"{m} мин. назад"
        if total_seconds < 86400:
            h = total_seconds // 3600
            return f"{h} ч. назад"
        d = total_seconds // 86400
        return f"{d} дн. назад"
    except Exception:
        return dt_str


def truncate(text: str | None, length: int) -> str:
    if not text:
        return "не указан"
    if len(text) <= length:
        return text
    return text[:length] + "..."


def escape_md(text: str) -> str:
    """Escape special characters for MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return re.sub(r"([" + re.escape(special) + r"])", r"\\\1", text)


def format_lead_card(lead: dict) -> str:
    from app.bot.texts import LEAD_CARD

    signals = lead.get("signals") or []

    return LEAD_CARD.format(
        id=lead.get("id"),
        score=lead.get("score"),
        reason=lead.get("reason") or "—",
        signals=", ".join(signals) if signals else "—",
        time_ago=format_time_ago(lead.get("scored_at")),
    )


def format_lead_message(lead: dict) -> str:
    from app.bot.texts import LEAD_MESSAGE_VIEW

    msg = lead.get("message", {}) or {}
    src = lead.get("source", {}) or {}
    raw_text = (msg.get("text") or "").strip()
    if not raw_text:
        message_text = "текст недоступен"
    elif len(raw_text) > 3800:
        message_text = html.escape(raw_text[:3800]) + "…"
    else:
        message_text = html.escape(raw_text)
    tg_date = msg.get("tg_date") or ""
    if tg_date:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(tg_date)
            tg_date = dt.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
        except Exception:
            pass

    return LEAD_MESSAGE_VIEW.format(
        id=lead.get("id"),
        score=lead.get("score", "—"),
        source_name=src.get("name") or src.get("url") or "канала",
        message_text=message_text,
        tg_date=tg_date or "неизвестно",
        time_ago=format_time_ago(lead.get("scored_at")),
    )


def format_lead_contact(lead: dict) -> str:
    from app.bot.texts import LEAD_CONTACT_CARD

    msg = lead.get("message", {}) or {}
    src = lead.get("source", {}) or {}
    username = msg.get("sender_username")
    sender_id = msg.get("sender_id")
    phone = msg.get("sender_phone")
    raw_text = (msg.get("text") or "").strip()
    if not raw_text:
        message_text = "текст недоступен"
    elif len(raw_text) > 3500:
        message_text = html.escape(raw_text[:3500]) + "…"
    else:
        message_text = html.escape(raw_text)

    tg_link = f"tg://user?id={sender_id}" if sender_id else "—"

    return LEAD_CONTACT_CARD.format(
        id=lead.get("id"),
        score=lead.get("score", "—"),
        source_name=src.get("name") or src.get("url") or "канала",
        message_text=message_text,
        sender_name=msg.get("sender_name") or "не указано",
        sender_username=f"@{username}" if username else "не указан",
        sender_phone=phone or "не указан",
        tg_link=tg_link,
        time_ago=format_time_ago(lead.get("scored_at")),
    )


def format_stats(stats: dict) -> str:
    from app.bot.texts import STATS_TEXT

    by_status = stats.get("leads_by_status") or {}
    total = sum(by_status.values()) if by_status else stats.get("total_leads", 0)
    return STATS_TEXT.format(
        total_leads=total,
        new=by_status.get("new", 0),
        viewed=by_status.get("viewed", 0),
        contacted=by_status.get("contacted", 0),
        rejected=by_status.get("rejected", 0),
    )
