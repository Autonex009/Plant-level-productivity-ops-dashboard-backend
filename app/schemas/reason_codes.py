from app.models.enums import Stage, TimeCategory
from app.schemas.base import ORMBase, TimestampedRead


class DowntimeReasonCodeBase(ORMBase):
    category: TimeCategory
    code: str
    description: str


class DowntimeReasonCodeCreate(DowntimeReasonCodeBase):
    pass


class DowntimeReasonCodeUpdate(ORMBase):
    category: TimeCategory | None = None
    code: str | None = None
    description: str | None = None


class DowntimeReasonCodeRead(DowntimeReasonCodeBase, TimestampedRead):
    pass


class DefectReasonCodeBase(ORMBase):
    stage: Stage
    code: str
    description: str


class DefectReasonCodeCreate(DefectReasonCodeBase):
    pass


class DefectReasonCodeUpdate(ORMBase):
    stage: Stage | None = None
    code: str | None = None
    description: str | None = None


class DefectReasonCodeRead(DefectReasonCodeBase, TimestampedRead):
    pass
