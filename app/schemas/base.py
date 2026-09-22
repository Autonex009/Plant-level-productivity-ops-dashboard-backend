from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TimestampedRead(ORMBase):
    id: int
    created_at: datetime
    updated_at: datetime
