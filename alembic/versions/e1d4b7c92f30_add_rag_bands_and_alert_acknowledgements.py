"""add RAG bands to plant metric targets and alert acknowledgements

Revision ID: e1d4b7c92f30
Revises: fd5a50657702
Create Date: 2026-09-23 09:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1d4b7c92f30'
down_revision: Union[str, Sequence[str], None] = 'fd5a50657702'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A target alone cannot colour a number: green/amber/red needs the amber-to-red
    # boundary too, and operating parameters need a two-sided control band with the
    # monsoon variants the spec requires for the season-sensitive metrics.
    op.add_column("plant_metric_targets", sa.Column("red_line_value", sa.Float(), nullable=True))
    op.add_column("plant_metric_targets", sa.Column("band_low", sa.Float(), nullable=True))
    op.add_column("plant_metric_targets", sa.Column("band_high", sa.Float(), nullable=True))
    op.add_column("plant_metric_targets", sa.Column("monsoon_band_low", sa.Float(), nullable=True))
    op.add_column("plant_metric_targets", sa.Column("monsoon_band_high", sa.Float(), nullable=True))

    op.create_table(
        "alert_acknowledgements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plant_id", sa.Integer(), nullable=False),
        sa.Column("alert_key", sa.String(length=255), nullable=False),
        sa.Column("acknowledged_by", sa.String(length=255), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_acknowledgements_alert_key", "alert_acknowledgements", ["alert_key"])


def downgrade() -> None:
    op.drop_index("ix_alert_acknowledgements_alert_key", table_name="alert_acknowledgements")
    op.drop_table("alert_acknowledgements")
    op.drop_column("plant_metric_targets", "monsoon_band_high")
    op.drop_column("plant_metric_targets", "monsoon_band_low")
    op.drop_column("plant_metric_targets", "band_high")
    op.drop_column("plant_metric_targets", "band_low")
    op.drop_column("plant_metric_targets", "red_line_value")
