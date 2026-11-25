import logging

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

celery_app = Celery(
    "telegram_lead_parser",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.parse",
        "app.tasks.cleanup",
        "app.tasks.expand",
        "app.tasks.joining",
        "app.tasks.author_monitor",
        "app.tasks.score",
    ],
)

import app.tasks.author_monitor  # noqa: F401
import app.tasks.cleanup         # noqa: F401 — ensure tasks are registered on import
import app.tasks.expand          # noqa: F401
import app.tasks.joining         # noqa: F401
import app.tasks.parse           # noqa: F401 — ensure tasks are registered on import
import app.tasks.score           # noqa: F401


def _cron(cron_str: str) -> crontab:
    """Parse '5-part cron string' into a celery crontab."""
    minute, hour, dom, moy, dow = cron_str.split()
    return crontab(minute=minute, hour=hour, day_of_month=dom, month_of_year=moy, day_of_week=dow)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_concurrency=2,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "schedule-parse-every-minute": {
            "task": "app.tasks.parse.schedule_parse_task",
            "schedule": crontab(minute="*"),
        },
        "process-join-queue-every-5-minutes": {
            "task": "app.tasks.parse.process_join_queue_task",
            "schedule": crontab(minute=f"*/{settings.PROCESS_JOIN_QUEUE_EVERY_MINUTES}"),
        },
        "cleanup-expired-leads-daily": {
            "task": "app.tasks.cleanup.cleanup_expired_leads",
            "schedule": crontab(hour=3, minute=0),
        },
        "export-skipped-messages-daily": {
            "task": "app.tasks.cleanup.export_skipped_messages",
            "schedule": crontab(hour=22, minute=0),
        },
        "parse-digest-4x-daily": {
            "task": "app.tasks.cleanup.send_parse_digest",
            "schedule": crontab(hour="10,14,18,22", minute=0),
        },
        "expand-from-recommendations": {
            "task": "app.tasks.expand.expand_from_recommendations",
            "schedule": _cron(settings.EXPAND_RECOMMENDATIONS_CRON),
        },
        "expand-from-forwards": {
            "task": "app.tasks.expand.expand_from_forwards",
            "schedule": _cron(settings.EXPAND_FORWARDS_CRON),
        },
        "expand-from-mentions": {
            "task": "app.tasks.expand.expand_from_mentions",
            "schedule": _cron(settings.EXPAND_MENTIONS_CRON),
        },
        "expand-from-search": {
            "task": "app.tasks.expand.expand_from_search",
            "schedule": _cron(settings.EXPAND_SEARCH_CRON),
        },
        "expand-from-tgstat": {
            "task": "app.tasks.expand.expand_from_tgstat",
            "schedule": _cron(settings.EXPAND_TGSTAT_CRON),
        },
        "score-all-sources-every-5-minutes": {
            "task": "app.tasks.score.score_all_sources_task",
            "schedule": crontab(minute="*/5"),
            "kwargs": {"user_id": settings.DEFAULT_USER_ID},
        },
        "process-pending-sources": {
            "task": "app.tasks.joining.process_pending_sources",
            "schedule": crontab(minute="*/30"),
        },
        "monitor-lead-authors": {
            "task": "app.tasks.author_monitor.monitor_lead_authors",
            "schedule": crontab(minute=0),
        },
    },
)
