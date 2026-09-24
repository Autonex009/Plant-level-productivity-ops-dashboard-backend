"""The dashboard's chat assistant - a thin, server-side proxy to DeepSeek.

The API key lives only in this process's environment. The browser sends
conversation turns here and gets a reply back; it never sees the key and
never talks to DeepSeek directly.

Data-aware since v2: every request gets a fresh, compact text snapshot of
today's KPIs, stage status, machine states and active alerts - the same
service functions the Overview and Machine Monitoring pages call - injected
as a system message. This is context injection, not tool-calling: one
snapshot, one request, no back-and-forth. It answers "what's today's output"
fine; it can't chase a question the snapshot doesn't cover, and the prompt
tells it to say so rather than guess.
"""

import json
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.enums import Stage
from app.services.dashboard import alerts as alerts_service
from app.services.dashboard import plant as plant_service
from app.services.dashboard.bands import load_bands
from app.services.dashboard.ranges import RangeMode, resolve_range
from app.services.dashboard.stage import KPI_BUILDERS
from app.services.dashboard.status import STAGE_LABELS, machine_states

router = APIRouter(prefix="/chat", tags=["chat"])

# This demo runs one plant; every other dashboard call is scoped to it the
# same way (the frontend's VITE_PLANT_ID defaults to 1 too).
PLANT_ID = 1

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
REQUEST_TIMEOUT_SECONDS = 30
MAX_REPLY_TOKENS = 600
ALERT_CAP = 5


class RateLimiter:
    """A basic in-memory sliding window - good enough to stop one browser
    tab (or one bad actor) from hammering a paid API key, not a distributed
    limiter. It only sees traffic that lands on this process, so it resets
    on a cold start and doesn't coordinate across concurrent instances -
    acceptable here because the global cap below still bounds worst-case
    spend per warm instance, which is the actual thing being protected."""

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return False
            hits.append(now)
            return True


# Per caller: enough for a real back-and-forth conversation, not enough to
# script a loop against the key. Global: a hard ceiling on this instance's
# spend regardless of how many distinct IPs show up.
_per_ip_limiter = RateLimiter(max_requests=8, window_seconds=60)
_global_limiter = RateLimiter(max_requests=60, window_seconds=60)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

SYSTEM_PROMPT = (
    "You are the assistant embedded in the operations dashboard for Shree "
    "Balaji Packaging, a corrugated-box plant (boarding/corrugating, "
    "printing, bundling). Answer briefly and practically, like a colleague "
    "on the shop floor.\n\n"
    "Scope: you help with THIS plant and THIS dashboard only - production, "
    "machines, KPIs, waste, orders, alerts, and how to use the dashboard's "
    "pages. If asked anything unrelated (general knowledge, coding, other "
    "companies, personal topics, or any other off-topic request), decline "
    "in one short sentence and say you only handle questions about this "
    "plant - do not answer the off-topic question even partially.\n\n"
    "Data: below is a live snapshot of today's KPIs, machine states and "
    "active alerts, generated fresh for this message - it is sample/demo "
    "data, so answer directly and plainly from it like you would state any "
    "other fact. Do not caveat that the data is mock, provisional, stale, "
    "or based on old readings, and do not comment on data quality or "
    "machine reporting status unless the user specifically asks about it. "
    "The snapshot covers today only: if asked about a longer period, a "
    "specific past shift, or a figure the snapshot doesn't contain, say in "
    "one short sentence that you don't have it and point at the relevant "
    "dashboard page (Overview, Production Efficiency, Machine Monitoring, "
    "Analytics) instead of guessing."
)


def _fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "no data"
    if unit == "INR":
        return f"₹{value:,.0f}"
    if unit == "%":
        return f"{value:.1f}%"
    return f"{value:g} {unit}"


def _context_snapshot(db: Session, now: datetime) -> str:
    spec = resolve_range(RangeMode.TODAY, today=now.date())
    overview = plant_service.plant_overview(db, PLANT_ID, spec, now=now)

    lines = [f"Live snapshot as of {now:%d %b %Y, %H:%M} (today, provisional).", "", "KPIs today:"]
    for card in overview["rollups"]:
        lines.append(f"- {card['label']}: {_fmt(card['value'], card['unit'])} (status: {card['rag']})")

    lines.append("")
    lines.append("Stage status, right now:")
    for row in overview["status_line"]:
        live = _fmt(row.get("live_value"), row.get("live_unit") or "") if row.get("live_value") is not None else "not running"
        worst = row.get("worst_machine") or "n/a"
        lines.append(f"- {row['label']}: {row['status']} - {live} (worst machine: {worst})")

    # The Production Efficiency page's actual numbers (rate/run-rate
    # efficiency, uptime, yield, etc.) - not just the four plant-wide
    # rollups - since "production efficiency" means this page to a reader.
    bands = load_bands(db, PLANT_ID, on_date=spec.end)
    lines.append("")
    lines.append("Per-stage efficiency KPIs (today, from the Production Efficiency page):")
    for stage in (Stage.BOARD_MANUFACTURING, Stage.PRINTING, Stage.BUNDLING):
        kpis = KPI_BUILDERS[stage](db, PLANT_ID, spec, bands, now=now)
        parts = [f"{kpi['label']} {_fmt(kpi['value'], kpi['unit'])}" for kpi in kpis]
        lines.append(f"- {STAGE_LABELS[stage]}: " + "; ".join(parts))

    lines.append("")
    lines.append("Machines:")
    for tile in machine_states(db, PLANT_ID, now=now):
        rate = _fmt(tile["rate"], tile["rate_unit"])
        reason = f", reason: {tile['reason_code']['description']}" if tile["reason_code"] else ""
        lines.append(f"- {tile['machine_code']} ({tile['name']}): {tile['state']} - {rate}{reason}")

    live_alerts = [
        *alerts_service.event_alerts(db, PLANT_ID, now=now),
        *alerts_service.breach_alerts(overview["rollups"]),
    ]
    capped = alerts_service.rank_and_cap(live_alerts, level=1, cap=ALERT_CAP)
    lines.append("")
    if capped:
        lines.append("Active alerts:")
        for alert in capped:
            how_long = f", {alert['how_long']}" if alert.get("how_long") else ""
            lines.append(f"- {alert['what']} - {alert['where']}{how_long}")
    else:
        lines.append("Active alerts: none right now.")

    return "\n".join(lines)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)


class ChatResponse(BaseModel):
    reply: str


@router.post("", response_model=ChatResponse)
def chat(request: ChatRequest, http_request: Request, db: Session = Depends(get_db)) -> ChatResponse:
    if not settings.deepseek_api_key:
        raise HTTPException(status_code=503, detail="Chat is not configured (missing DEEPSEEK_API_KEY).")

    if not _global_limiter.allow("global"):
        raise HTTPException(
            status_code=429,
            detail="The assistant is getting a lot of questions right now. Please try again shortly.",
        )
    if not _per_ip_limiter.allow(_client_ip(http_request)):
        raise HTTPException(
            status_code=429,
            detail="You're sending messages a bit fast - please wait a moment and try again.",
        )

    now = datetime.now()
    try:
        snapshot = _context_snapshot(db, now)
    except Exception:
        # A snapshot failure should degrade to plain Q&A, not take the whole
        # assistant down - the system prompt already tells it not to guess at
        # numbers it wasn't given.
        snapshot = "Live snapshot unavailable right now."

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": snapshot},
        ]
        + [{"role": m.role, "content": m.content} for m in request.messages],
        "stream": False,
        "max_tokens": MAX_REPLY_TOKENS,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        DEEPSEEK_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.deepseek_api_key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:300]
        raise HTTPException(status_code=502, detail=f"DeepSeek error ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=504, detail="Could not reach DeepSeek.") from exc

    try:
        reply = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="Unexpected response from DeepSeek.") from exc

    return ChatResponse(reply=reply)
