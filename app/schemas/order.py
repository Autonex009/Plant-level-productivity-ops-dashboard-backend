from datetime import date, datetime

from app.schemas.base import ORMBase, TimestampedRead


class OrderBase(ORMBase):
    plant_id: int
    order_number: str
    customer_name: str | None = None
    ply_construction: str | None = None
    flute_profile: str | None = None
    sheet_length_mm: float | None = None
    sheet_width_mm: float | None = None
    paper_gsm: float | None = None
    paper_bf: float | None = None
    quantity_ordered: int | None = None
    due_date: date | None = None
    standard_speed: float | None = None
    standard_speed_unit: str | None = None
    order_complete_staged_at: datetime | None = None


class OrderCreate(OrderBase):
    pass


class OrderUpdate(ORMBase):
    plant_id: int | None = None
    order_number: str | None = None
    customer_name: str | None = None
    ply_construction: str | None = None
    flute_profile: str | None = None
    sheet_length_mm: float | None = None
    sheet_width_mm: float | None = None
    paper_gsm: float | None = None
    paper_bf: float | None = None
    quantity_ordered: int | None = None
    due_date: date | None = None
    standard_speed: float | None = None
    standard_speed_unit: str | None = None
    order_complete_staged_at: datetime | None = None


class OrderRead(OrderBase, TimestampedRead):
    pass
