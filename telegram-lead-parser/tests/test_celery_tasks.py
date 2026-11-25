def test_parse_source_task_is_registered():
    """Task is registered in the Celery app."""
    from app.core.celery import celery_app
    assert "app.tasks.parse.parse_source_task" in celery_app.tasks


def test_parse_all_sources_task_is_registered():
    from app.core.celery import celery_app
    assert "app.tasks.parse.parse_all_sources_task" in celery_app.tasks


def test_validate_source_task_is_registered():
    from app.core.celery import celery_app
    assert "app.tasks.parse.validate_source_task" in celery_app.tasks


def test_parse_source_task_max_retries():
    from app.tasks.parse import parse_source_task
    assert parse_source_task.max_retries == 3


def test_celery_beat_schedule_configured():
    from app.core.celery import celery_app
    beat_schedule = celery_app.conf.beat_schedule
    assert "schedule-parse-every-minute" in beat_schedule
    task_name = beat_schedule["schedule-parse-every-minute"]["task"]
    assert task_name == "app.tasks.parse.schedule_parse_task"


def test_process_join_queue_task_in_beat_schedule():
    from app.core.celery import celery_app
    beat_schedule = celery_app.conf.beat_schedule
    assert "process-join-queue-every-5-minutes" in beat_schedule
    entry = beat_schedule["process-join-queue-every-5-minutes"]
    assert entry["task"] == "app.tasks.parse.process_join_queue_task"
