from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, ConfigDict


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

    model_config = ConfigDict(from_attributes=True)


class FollowUpCreate(BaseModel):
    content: str
    next_action: Optional[str] = None


class FollowUpOut(FollowUpCreate):
    id: int
    customer_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AIResult(BaseModel):
    result: str


class RagAsk(BaseModel):
    question: str


class RagSource(BaseModel):
    filename: str
    chunk_index: int
    content: str


class RagAnswer(BaseModel):
    answer: str
    sources: List[RagSource]


class AgentAnalyzeRequest(BaseModel):
    customer_id: int
    task: Optional[str] = "帮我分析这个客户下一步怎么跟进"


class AgentAnalyzeResult(BaseModel):
    steps: List[str]
    result: str
    sources: List[RagSource]


class RagDocument(BaseModel):
    filename: str
    chunks: int
