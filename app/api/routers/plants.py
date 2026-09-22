from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.database import get_db
from app.models import Plant
from app.schemas.plant import PlantCreate, PlantRead, PlantUpdate

router = build_crud_router(
    model=Plant,
    create_schema=PlantCreate,
    update_schema=PlantUpdate,
    read_schema=PlantRead,
    prefix="/plants",
    tags=["plants"],
)


@router.get("", response_model=list[PlantRead])
def list_plants(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)) -> list[Plant]:
    return db.query(Plant).offset(skip).limit(limit).all()
