"""add printing standard to orders and ink check metrics

Revision ID: f2c8a1b45d77
Revises: e1d4b7c92f30
Create Date: 2026-09-23 10:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f2c8a1b45d77'
down_revision: Union[str, Sequence[str], None] = 'e1d4b7c92f30'
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

# The spec's Level 3 printing panel is the ink check log - "viscosity by Ford cup
# No. 4, pH; each check timestamped, with overdue checks flagged" - but the
# catalog had no entry for either, so there was nothing to record a check against.
INK_METRICS = [
    dict(
        code="ink_viscosity",
        name="Ink viscosity",
        definition="Ford cup No. 4 efflux time, checked per job and per shift",
        unit="s",
        category="parameters",
        stage="printing",
    ),
    dict(
        code="ink_ph",
        name="Ink pH",
        definition="Water-based ink pH, checked per job and per shift",
        unit="pH",
        category="parameters",
        stage="printing",
    ),
]


def upgrade() -> None:
    # One job has two different throughput standards, because the corrugator is a
    # continuous machine measured in m/min and a printer is a batch machine
    # measured in sheets/hr. Order.standard_speed carries the corrugator's;
    # without a second column the printing KPI was dividing sheets per hour by a
    # metres-per-minute figure and reporting efficiencies in the thousands.
    op.add_column(
        "orders",
        sa.Column("printing_standard_sheets_per_hr", sa.Float(), nullable=True),
    )
    op.bulk_insert(metric_definitions_table, INK_METRICS)


def downgrade() -> None:
    op.execute(
        metric_definitions_table.delete().where(
            metric_definitions_table.c.code.in_([m["code"] for m in INK_METRICS])
        )
    )
    op.drop_column("orders", "printing_standard_sheets_per_hr")
