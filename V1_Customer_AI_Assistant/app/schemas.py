from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CustomerCreate(BaseModel):
    name: str
    company: str
    phone: Optional[str] = None
    email: Optional[str] = None
    industry: Optional[str] = None
    level: Optional[str] = None
    intention: Optional[str] = None
    cooperation_status: Optional[str] = None


class CustomerOut(CustomerCreate):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class FollowUpCreate(BaseModel):
    content: str
    next_action: Optional[str] = None


class FollowUpOut(FollowUpCreate):
    id: int
    customer_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class AIResult(BaseModel):
    result: str
