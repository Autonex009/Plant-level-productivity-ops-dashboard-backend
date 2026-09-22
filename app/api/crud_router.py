from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db


def build_crud_router(
    *,
    model: type,
    create_schema: type[BaseModel],
    update_schema: type[BaseModel],
    read_schema: type[BaseModel],
    prefix: str,
    tags: list[str],
) -> APIRouter:
    """Builds the id-keyed CRUD operations (get one, create, update, delete) that
    are identical across every entity. Each router module adds its own `list`
    endpoint on top, since useful filters differ per entity."""

    router = APIRouter(prefix=prefix, tags=tags)

    def get_or_404(db: Session, item_id: int) -> Any:
        obj = db.get(model, item_id)
        if obj is None:
            raise HTTPException(status_code=404, detail=f"{model.__name__} {item_id} not found")
        return obj

    @router.get("/{item_id}", response_model=read_schema)
    def get_item(item_id: int, db: Session = Depends(get_db)) -> Any:
        return get_or_404(db, item_id)

    @router.post("", response_model=read_schema, status_code=201)
    def create_item(payload: create_schema, db: Session = Depends(get_db)) -> Any:  # type: ignore[valid-type]
        obj = model(**payload.model_dump())
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    @router.patch("/{item_id}", response_model=read_schema)
    def update_item(item_id: int, payload: update_schema, db: Session = Depends(get_db)) -> Any:  # type: ignore[valid-type]
        obj = get_or_404(db, item_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, field, value)
        db.commit()
        db.refresh(obj)
        return obj

    @router.delete("/{item_id}", status_code=204)
    def delete_item(item_id: int, db: Session = Depends(get_db)) -> None:
        obj = get_or_404(db, item_id)
        db.delete(obj)
        db.commit()

    return router
