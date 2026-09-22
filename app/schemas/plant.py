from app.models.enums import LineType
from app.schemas.base import ORMBase, TimestampedRead


class PlantBase(ORMBase):
    name: str
    location: str | None = None
    line_type: LineType


class PlantCreate(PlantBase):
    pass


class PlantUpdate(ORMBase):
    name: str | None = None
    location: str | None = None
    line_type: LineType | None = None


class PlantRead(PlantBase, TimestampedRead):
    pass
