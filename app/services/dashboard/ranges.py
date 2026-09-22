"""Resolves the header time selector into concrete date windows.

Section 4 of the spec: one selector switches the time base of the whole screen,
and a part-period is only ever compared with the same days of the prior period
("Sep 1-21 versus Aug 1-21, never with a full prior period"). That comparison
fairness rule lives here so every caller inherits it.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum


class RangeMode(str, Enum):
    TODAY = "today"
    WEEK = "week"
    MONTH = "month"
    CUSTOM = "custom"


class Granularity(str, Enum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"


# The Indian monsoon months, during which the spec requires season-adjusted
# control bands for moisture, warp, and yield rather than fixed limits.
MONSOON_MONTHS = {6, 7, 8, 9}


@dataclass(frozen=True)
class RangeSpec:
    mode: RangeMode
    start: date
    end: date
    label: str
    granularity: Granularity

    # The same span of days one period earlier, for the delta arrows. None when
    # no fair comparison exists (Custom hides deltas by default).
    prev_start: date | None
    prev_end: date | None

    # A range that includes today cannot be fully reconciled, so every figure
    # derived from it carries the provisional marker (~).
    includes_today: bool

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def is_monsoon(self) -> bool:
        return self.start.month in MONSOON_MONTHS


def _shift_months(anchor: date, months: int) -> date:
    """Same day-of-month, `months` earlier, clamped to the shorter month."""
    month_index = (anchor.month - 1) - months
    year = anchor.year + month_index // 12
    month = month_index % 12 + 1
    last_day = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(anchor.day, last_day))


def resolve_range(
    mode: RangeMode | str,
    *,
    today: date,
    date_from: date | None = None,
    date_to: date | None = None,
) -> RangeSpec:
    mode = RangeMode(mode)

    if mode is RangeMode.TODAY:
        return RangeSpec(
            mode=mode,
            start=today,
            end=today,
            label=today.strftime("%d %b %Y"),
            granularity=Granularity.HOURLY,
            prev_start=today - timedelta(days=1),
            prev_end=today - timedelta(days=1),
            includes_today=True,
        )

    if mode is RangeMode.WEEK:
        # Calendar week, Monday to today - week-to-date, not a rolling 7 days.
        start = today - timedelta(days=today.weekday())
        return RangeSpec(
            mode=mode,
            start=start,
            end=today,
            label=f"{start.strftime('%d %b')} - {today.strftime('%d %b')}",
            granularity=Granularity.DAILY,
            prev_start=start - timedelta(days=7),
            prev_end=today - timedelta(days=7),
            includes_today=True,
        )

    if mode is RangeMode.MONTH:
        start = today.replace(day=1)
        return RangeSpec(
            mode=mode,
            start=start,
            end=today,
            label=today.strftime("%B %Y"),
            granularity=Granularity.DAILY,
            # Same days of last month, never a full prior month.
            prev_start=_shift_months(start, 1),
            prev_end=_shift_months(today, 1),
            includes_today=True,
        )

    if date_from is None or date_to is None:
        raise ValueError("Custom range requires both date_from and date_to")
    if date_to < date_from:
        date_from, date_to = date_to, date_from

    span = (date_to - date_from).days + 1
    return RangeSpec(
        mode=mode,
        start=date_from,
        end=date_to,
        label=f"{date_from.strftime('%d %b')} - {date_to.strftime('%d %b %Y')}",
        # Daily rows stay readable to about a month; beyond that they become weekly.
        granularity=Granularity.DAILY if span <= 31 else Granularity.WEEKLY,
        # Custom hides deltas by default; the preceding period of equal length is
        # carried here so the UI can offer it as an opt-in.
        prev_start=date_from - timedelta(days=span),
        prev_end=date_from - timedelta(days=1),
        includes_today=date_from <= today <= date_to,
    )


def day_span(spec: RangeSpec) -> list[date]:
    return [spec.start + timedelta(days=offset) for offset in range(spec.days)]
