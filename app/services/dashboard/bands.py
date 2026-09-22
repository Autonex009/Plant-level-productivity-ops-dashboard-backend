"""Turns a bare number into a number with a verdict.

Design principle 3 of the spec: "Every number carries its target and a verdict.
Values are always shown against targets with a green/amber/red (RAG) status
derived from the plant's own baseline." Section 7.1 fixes the logic: green is at
or better than target, amber sits between target and the red line, red is worse
than the red line, and the bands are always the plant's own - never imported
industry figures.
"""

from dataclasses import dataclass, replace
from datetime import date

from sqlalchemy.orm import Session

from app.models import MetricDefinition, PlantMetricTarget
from app.services.dashboard.ranges import MONSOON_MONTHS

# Metrics where a smaller number is the better number. Everything not listed is
# higher-is-better. This drives both the RAG direction and the colour of the
# period-comparison delta arrow (rising waste is a red arrow).
LOWER_IS_BETTER = frozenset(
    {
        "cost_of_waste_inr",
        "power_per_tonne_kwh",
        "conversion_waste_pct",
        "starvation_minutes",
        "setups_avg_time",
        "setups_count",
        "order_changes_avg_time",
        "ink_consumption_per_1000_sheets",
        "starch_consumption_per_area",
        "starch_consumption_per_tonne",
        "warp",
    }
)

# Metrics that accumulate over the selected range rather than describing a rate.
# A target for these is set per day, so judging a month-to-date total against it
# would paint every month red by the second of the month. Their band is scaled by
# the number of days in the range instead.
CUMULATIVE_METRICS = frozenset({"cost_of_waste_inr", "production_weight"})

# Metrics the spec calls out as season-sensitive: "moisture and warp therefore
# require season-adjusted control bands rather than fixed limits", and yield
# carries a monsoon marker on its trend.
SEASON_ADJUSTED = frozenset({"moisture_pct", "warp", "paper_yield_pct", "overall_yield_pct"})


class Rag(str):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"
    GREY = "grey"


@dataclass(frozen=True)
class Band:
    metric_code: str
    unit: str
    label: str
    target: float | None
    red_line: float | None
    band_low: float | None
    band_high: float | None
    lower_is_better: bool
    season_adjusted: bool


def _fallback_red_line(target: float, lower_is_better: bool) -> float:
    """Used only when a plant has set a target but not yet an amber/red boundary.

    Deliberately conservative - a tenth off target - so an unconfigured metric
    never shouts red on day one. The spec's real red line (worse than the
    trailing 90-day median) is set per plant at onboarding.
    """
    return round(target * (1.10 if lower_is_better else 0.90), 4)


def load_bands(db: Session, plant_id: int, *, on_date: date) -> dict[str, Band]:
    """Every configured band for a plant, keyed by metric code.

    Targets are versioned by effective_from, so the row that applies is the most
    recent one that has already taken effect.
    """
    rows = (
        db.query(PlantMetricTarget, MetricDefinition)
        .join(MetricDefinition, MetricDefinition.id == PlantMetricTarget.metric_definition_id)
        .filter(
            PlantMetricTarget.plant_id == plant_id,
            PlantMetricTarget.effective_from <= on_date,
        )
        .order_by(PlantMetricTarget.effective_from)
        .all()
    )

    monsoon = on_date.month in MONSOON_MONTHS
    bands: dict[str, Band] = {}
    for target_row, definition in rows:  # later effective_from overwrites earlier
        lower_is_better = definition.code in LOWER_IS_BETTER
        low, high = target_row.band_low, target_row.band_high
        if monsoon and definition.code in SEASON_ADJUSTED:
            low = target_row.monsoon_band_low if target_row.monsoon_band_low is not None else low
            high = target_row.monsoon_band_high if target_row.monsoon_band_high is not None else high

        bands[definition.code] = Band(
            metric_code=definition.code,
            unit=definition.unit,
            label=definition.name,
            target=target_row.target_value,
            red_line=(
                target_row.red_line_value
                if target_row.red_line_value is not None
                else _fallback_red_line(target_row.target_value, lower_is_better)
            ),
            band_low=low,
            band_high=high,
            lower_is_better=lower_is_better,
            season_adjusted=monsoon and definition.code in SEASON_ADJUSTED,
        )
    return bands


def scale_for_days(band: Band | None, days: int) -> Band | None:
    """Stretches a per-day band across the selected range.

    Only cumulative metrics move: a percentage or a rate means the same thing
    over a day as over a month, but a rupee total does not.
    """
    if band is None or days <= 1 or band.metric_code not in CUMULATIVE_METRICS:
        return band
    return replace(
        band,
        target=None if band.target is None else band.target * days,
        red_line=None if band.red_line is None else band.red_line * days,
    )


def rag_for(value: float | None, band: Band | None) -> str:
    """Grey is not a failure colour: it means we cannot judge, because the value
    is missing or the plant has not set a band for this metric yet."""
    if value is None or band is None or band.target is None:
        return Rag.GREY

    target, red_line = band.target, band.red_line
    if band.lower_is_better:
        if value <= target:
            return Rag.GREEN
        if red_line is None or value <= red_line:
            return Rag.AMBER
        return Rag.RED

    if value >= target:
        return Rag.GREEN
    if red_line is None or value >= red_line:
        return Rag.AMBER
    return Rag.RED


def band_position(value: float | None, band: Band | None) -> str:
    """Where a live parameter reading sits against its two-sided control band.

    Operating parameters are not judged against a target but against a band:
    "value-in-band strip with drift arrow". Returns in_band / below / above / unknown.
    """
    if value is None or band is None or band.band_low is None or band.band_high is None:
        return "unknown"
    if value < band.band_low:
        return "below"
    if value > band.band_high:
        return "above"
    return "in_band"


def delta_direction(current: float | None, previous: float | None, band: Band | None) -> str | None:
    """Colours a period-over-period delta by direction-of-good, independently of
    the RAG pill: "rising waste is a red arrow" even while the value is still
    inside target."""
    if current is None or previous is None:
        return None
    if current == previous:
        return "flat"
    rising = current > previous
    lower_is_better = band.lower_is_better if band else False
    good = (not rising) if lower_is_better else rising
    return "up_good" if (rising and good) else "up_bad" if rising else "down_good" if good else "down_bad"
