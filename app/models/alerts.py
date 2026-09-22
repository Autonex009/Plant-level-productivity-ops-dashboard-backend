from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class AlertAcknowledgement(Base, TimestampMixin):
    """Records that a human took ownership of a drift alert.

    Alerts themselves are never stored: they are derived from the fact tables on
    every read, so an alert auto-clears the moment its condition clears. What does
    need persisting is the acknowledgement, because the spec makes it the thing
    that stops escalation - "acknowledged means owned; unacknowledged for 60
    minutes, the alert is promoted to Level 1".

    alert_key is the deterministic identity the alert engine derives for a
    condition (type + machine + subject), so the same live condition matches its
    acknowledgement across reads.
    """

    __tablename__ = "alert_acknowledgements"

    id: Mapped[int] = mapped_column(primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), nullable=False)
    alert_key: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    acknowledged_by: Mapped[str | None] = mapped_column(String(255))
    acknowledged_at: Mapped[datetime] = mapped_column(nullable=False)

    plant: Mapped["Plant"] = relationship()
