from datetime import datetime
from pydantic import BaseModel, EmailStr


class WaitlistCreate(BaseModel):
    email: EmailStr
    source: str | None = None


class WaitlistRead(BaseModel):
    id: int
    email: EmailStr
    source: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
