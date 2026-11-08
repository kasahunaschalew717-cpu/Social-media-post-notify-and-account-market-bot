from celery import Celery
from celery.schedules import crontab
from core.config import settings

celery_app = Celery(
    "dual_engine_bot_workers",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)

# Celery Beat Periodic Schedule
celery_app.conf.beat_schedule = {
    "poll-active-social-sources": {
        "task": "workers.tasks.poll_all_social_sources",
        "schedule": crontab(minute="*/15"),  # every 15 minutes
    },
    "recheck-pending-ownership-verifications": {
        "task": "workers.tasks.check_pending_ownership_verifications",
        "schedule": crontab(minute="*/5"),  # every 5 minutes
    },
    "monitor-escrow-inspection-deadlines": {
        "task": "workers.tasks.check_escrow_inspection_timeouts",
        "schedule": crontab(minute="*/30"),  # every 30 minutes
    },
    "expire-stale-marketplace-listings": {
        "task": "workers.tasks.expire_stale_listings",
        "schedule": crontab(hour="3", minute="0"),  # daily at 03:00 UTC
    },
}

