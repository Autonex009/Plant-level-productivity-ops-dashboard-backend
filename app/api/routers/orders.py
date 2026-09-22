from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.database import get_db
from app.models import Order
from app.schemas.order import OrderCreate, OrderRead, OrderUpdate

router = build_crud_router(
    model=Order,
    create_schema=OrderCreate,
    update_schema=OrderUpdate,
    read_schema=OrderRead,
    prefix="/orders",
    tags=["orders"],
)


@router.get("", response_model=list[OrderRead])
def list_orders(
    plant_id: int | None = None,
    order_number: str | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[Order]:
    query = db.query(Order)
    if plant_id is not None:
        query = query.filter(Order.plant_id == plant_id)
    if order_number is not None:
        query = query.filter(Order.order_number == order_number)
    return query.offset(skip).limit(limit).all()
