from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db

router = APIRouter(tags=["admin"])


def _require_cron_auth(authorization: str | None) -> None:
    """Shared by every /internal endpoint.

    Vercel stamps cron-triggered requests with `Authorization: Bearer
    <CRON_SECRET>` when that env var is set on the project, and an external
    pinger can send the same header. None of these endpoints do anything
    destructive - they never truncate or update, only insert - so the blast
    radius of a leaked secret is "the demo data moves forward early", not data
    loss.
    """
    if not settings.cron_secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET is not configured")
    if authorization != f"Bearer {settings.cron_secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/internal/advance-demo-day")
def advance_demo_day(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Tops the demo dataset up to today. Meant to be called once a day by a
    Vercel Cron Job (see vercel.json) rather than by hand - this is what
    keeps the deployed dashboard looking live without a manual reseed.

    Vercel stamps cron-triggered requests with `Authorization: Bearer
    <CRON_SECRET>` when that env var is set on the project, which is the only
    thing that authenticates this endpoint - it does nothing destructive
    (never truncates), so the blast radius of a leaked secret is "the demo
    data advances a day early," not data loss.
    """
    _require_cron_auth(authorization)

    from scripts.seed_demo import advance_to_today

    return advance_to_today(db, datetime.now())


@router.get("/internal/top-up-live")
def top_up_live_endpoint(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Extends the current shift up to this moment, so the live screens have
    something to show.

    `advance-demo-day` fills whole missing days and leaves a day that already
    has shifts alone, which is right for history and useless for "now": the
    current shift stops wherever the last run finished, and Machine Monitoring
    greys every machine out once its newest time log is older than
    STALE_AFTER. This closes that trailing gap, and is meant to be called every
    few minutes rather than daily.

    Strictly additive - it reuses the open shift and each machine's current
    order and only ever inserts new rows, so calling it twice in a row is
    harmless: the second call just finds a smaller gap.

    `datetime.now()` deliberately, not UTC: the dashboard reads the clock the
    same way, so whatever clock this process runs on, the data written and the
    code reading it agree. (On Vercel that clock is UTC.)
    """
    _require_cron_auth(authorization)

    from scripts.top_up_live import top_up_live

    return top_up_live(db, datetime.now(), commit=True)
