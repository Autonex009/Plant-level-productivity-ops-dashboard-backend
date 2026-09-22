"""seed metric definitions

Revision ID: c0a6ff5c40f2
Revises: ac102b52a7d6
Create Date: 2026-09-22 13:03:48.764687

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0a6ff5c40f2'
down_revision: Union[str, Sequence[str], None] = 'ac102b52a7d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


metric_definitions_table = sa.table(
    "metric_definitions",
    sa.column("code", sa.String),
    sa.column("name", sa.String),
    sa.column("definition", sa.String),
    sa.column("unit", sa.String),
    sa.column("category", sa.String),
    sa.column("stage", sa.String),
)

# One row per metric enumerated in the spec's per-stage tables, plus the
# plant-level rollup numbers. stage=None marks a plant-level metric.
METRICS: list[dict] = [
    # Stage 1: Board manufacturing (corrugator)
    dict(code="paper_yield_pct", name="Paper yield", definition="Board output (kg) / paper consumed (kg)", unit="%", category="material", stage="board_manufacturing"),
    dict(code="deckle_utilisation_pct", name="Deckle utilisation", definition="Combined order width / deckle width used", unit="%", category="material", stage="board_manufacturing"),
    dict(code="starch_consumption_per_area", name="Starch consumption (control view)", definition="Starch used / board area", unit="g/m2", category="material", stage="board_manufacturing"),
    dict(code="starch_consumption_per_tonne", name="Starch consumption (cost view)", definition="Starch used per tonne of board", unit="kg/t", category="material", stage="board_manufacturing"),
    dict(code="average_running_speed", name="Average running speed", definition="Lineal metres / running minutes", unit="m/min", category="throughput", stage="board_manufacturing"),
    dict(code="production_area", name="Production (area)", definition="Dry-end counter, area basis", unit="k m2", category="throughput", stage="board_manufacturing"),
    dict(code="production_weight", name="Production (weight)", definition="Dry-end counter, weight basis", unit="tonnes/shift", category="throughput", stage="board_manufacturing"),
    dict(code="order_changes_count", name="Order changes (count)", definition="Number of order changes per shift", unit="count", category="throughput", stage="board_manufacturing"),
    dict(code="order_changes_avg_time", name="Order changes (avg time)", definition="Average time per order change", unit="min", category="throughput", stage="board_manufacturing"),
    dict(code="first_pass_good_board_pct", name="First-pass good board", definition="Good sheets / total sheets stacked", unit="%", category="quality", stage="board_manufacturing"),
    dict(code="warp", name="Warp", definition="QA sampling per order", unit="mm", category="quality", stage="board_manufacturing"),
    dict(code="moisture_pct", name="Moisture content", definition="QA sampling per order; requires season-adjusted control bands", unit="%", category="quality", stage="board_manufacturing"),
    dict(code="pin_adhesion", name="Pin adhesion", definition="QA sampling per order; resistance to ply delamination", unit="N", category="quality", stage="board_manufacturing"),
    dict(code="bursting_strength", name="Bursting strength (BS)", definition="QA sampling per order; prevailing basis of specification", unit="kgf/cm2", category="quality", stage="board_manufacturing"),
    dict(code="edge_crush_test", name="Edge crush test (ECT)", definition="QA sampling per order", unit="kN/m", category="quality", stage="board_manufacturing"),
    dict(code="caliper", name="Caliper", definition="QA sampling per order", unit="mm", category="quality", stage="board_manufacturing"),
    dict(code="uptime_pct", name="Uptime", definition="Running time / scheduled time", unit="%", category="time", stage="board_manufacturing"),
    dict(code="roll_temperature", name="Corrugating roll temperature", definition="Live from PLC/HMI; drift precedes warp and delamination", unit="C", category="parameters", stage="board_manufacturing"),
    dict(code="steam_pressure", name="Steam pressure", definition="Live from PLC/HMI", unit="kg/cm2", category="parameters", stage="board_manufacturing"),
    dict(code="glue_gap", name="Glue gap", definition="Live from PLC/HMI", unit="mm", category="parameters", stage="board_manufacturing"),

    # Stage 2: Printing
    dict(code="conversion_waste_pct", name="Conversion waste", definition="(Sheets in - good sheets out) / sheets in", unit="%", category="material", stage="printing"),
    dict(code="ink_consumption_per_1000_sheets", name="Ink consumption", definition="Ink used per 1,000 sheets, by job", unit="kg", category="material", stage="printing"),
    dict(code="run_rate_efficiency_pct", name="Run rate efficiency", definition="Actual sheets/hr / standard for the job", unit="%", category="throughput", stage="printing"),
    dict(code="setups_count", name="Setups (count)", definition="Number of setups (job changeovers) per shift", unit="count", category="throughput", stage="printing"),
    dict(code="setups_avg_time", name="Setups (avg time)", definition="Average setup time per changeover", unit="min", category="throughput", stage="printing"),
    dict(code="first_pass_good_printed_pct", name="First-pass good (printed)", definition="Good sheets / printed sheets", unit="%", category="quality", stage="printing"),
    dict(code="caliper_retention_pct", name="Caliper retention (crush)", definition="Caliper after / caliper before printing", unit="%", category="quality", stage="printing"),

    # Stage 3: Bundling
    dict(code="bundles_per_hour", name="Bundles per hour", definition="Bundles produced per hour", unit="bundles/hr", category="throughput", stage="bundling"),
    dict(code="output_per_worker_shift", name="Output per worker per shift", definition="Output per worker per shift", unit="kg", category="throughput", stage="bundling"),
    dict(code="count_accuracy_pct", name="Count accuracy", definition="Verified through random audits", unit="%", category="quality", stage="bundling"),
    dict(code="starvation_minutes", name="Starvation time", definition="Minutes bundling stood idle awaiting material from printing", unit="min", category="time", stage="bundling"),

    # Plant-level rollup (stage=None)
    dict(code="overall_yield_pct", name="Overall yield", definition="Good output dispatched / paper consumed", unit="%", category="material", stage=None),
    dict(code="plant_productivity_pct", name="Plant productivity", definition="Utilization x rate efficiency x quality", unit="%", category="throughput", stage=None),
    dict(code="utilization_pct", name="Utilization", definition="Running minutes / scheduled minutes", unit="%", category="time", stage=None),
    dict(code="rate_efficiency_pct", name="Rate efficiency", definition="Actual running speed / job standard speed", unit="%", category="throughput", stage=None),
    dict(code="quality_pct", name="Quality", definition="Good output / total output, plant-wide", unit="%", category="quality", stage=None),
    dict(code="cost_of_waste_inr", name="Cost of waste", definition="Waste kg x paper rate + starch + power share", unit="INR", category="material", stage=None),
    dict(code="power_per_tonne_kwh", name="Power per tonne", definition="Total power consumed / tonnes of board produced", unit="kWh/t", category="parameters", stage=None),
    dict(code="grid_power_share_pct", name="Grid power share", definition="Grid kWh / total kWh (grid + DG)", unit="%", category="parameters", stage=None),
]


def upgrade() -> None:
    op.bulk_insert(metric_definitions_table, METRICS)


def downgrade() -> None:
    codes = [m["code"] for m in METRICS]
    op.execute(
        metric_definitions_table.delete().where(
            metric_definitions_table.c.code.in_(codes)
        )
    )
