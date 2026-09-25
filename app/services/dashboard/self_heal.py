"""Keeps the live screens live without an external scheduler.

Machine Monitoring greys a machine out once its newest time log is older than
STALE_AFTER, which is correct: a dead feed must never be drawn as a running
machine. With a real MES that rule protects the reader. With *demo* data it
means the screens are blank except for the few minutes after whatever job last
topped the dataset up - and every scheduler available to top it up frequently
enough has turned out to be unreliable or paid:

  - Vercel Cron on Hobby allows one run a day.
  - A GitHub Actions `*/5` schedule is best-effort and was observed running
    roughly every three hours, nowhere near often enough for a 20-minute window.

So the read heals itself instead. When a live screen is requested and the data
has gone stale, the request tops the current shift up before answering. There is
no schedule to miss: opening the page is the trigger.

This is a demo affordance and is off unless `demo_self_heal` is set, because a
deployment with a real feed must never have its API inventing production. When
it is off, nothing here runs and a stale feed stays honestly grey.
"""

from datetime import datetime, timedelta

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import MachineRun, Machine, Shift, TimeLog

# Heal a little before the status line would go grey, so a reader never catches
# the screen mid-gap.
HEAL_WHEN_OLDER_THAN = timedelta(minutes=10)

# One writer at a time. Two requests arriving together would otherwise both see
# the same gap and both fill it, doubling that stretch of the shift.
_ADVISORY_LOCK_KEY = 20260925


def newest_log_age(db: Session, plant_id: int, now: datetime) -> timedelta | None:
    """How far behind the clock this plant's most recent activity is."""
    newest = (
        db.query(func.max(TimeLog.end_time))
        .join(MachineRun, MachineRun.id == TimeLog.machine_run_id)
        .join(Machine, Machine.id == MachineRun.machine_id)
        .join(Shift, Shift.id == MachineRun.shift_id)
        .filter(Shift.plant_id == plant_id, TimeLog.start_time <= now)
        .scalar()
    )
    return None if newest is None else now - newest


def heal_if_stale(db: Session, plant_id: int, now: datetime) -> dict | None:
    """Tops the current shift up to `now` when the data has fallen behind.

    Returns None when nothing was done - which is the common case, because once
    a request has healed the gap every request for the next ten minutes finds
    the data already fresh.
    """
    if not settings.demo_self_heal:
        return None

    age = newest_log_age(db, plant_id, now)
    if age is None or age < HEAL_WHEN_OLDER_THAN:
        return None

    # Skip rather than queue: if another request is already filling this gap,
    # this one should answer from what is there rather than wait on a lock.
    if not db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _ADVISORY_LOCK_KEY}).scalar():
        return None

    try:
        from scripts.top_up_live import top_up_live

        return top_up_live(db, now, commit=True)
    finally:
        db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _ADVISORY_LOCK_KEY})
        db.commit()
