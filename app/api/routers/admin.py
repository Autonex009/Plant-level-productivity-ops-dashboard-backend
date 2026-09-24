from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db

router = APIRouter(tags=["admin"])


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
    if not settings.cron_secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET is not configured")
    if authorization != f"Bearer {settings.cron_secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    from scripts.seed_demo import advance_to_today

    return advance_to_today(db, datetime.now())
