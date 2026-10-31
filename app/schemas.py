from pydantic import BaseModel, Field, ConfigDict
from typing import Literal

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ChatRequest(StrictModel):
    session_id: str = Field(min_length=20, max_length=80)
    message: str = Field(min_length=1, max_length=4000)

class ChatResponse(BaseModel):
    reply: str
    sources: list[str] = Field(default_factory=list)
    decision: Literal["answer", "clarify", "escalate", "refuse"] = "answer"
    verification_required: bool = False
    ticket_created: bool = False
    ticket_id: str | None = None

class OrderStartRequest(StrictModel):
    session_id: str = Field(min_length=20, max_length=80)
    order_id: str = Field(min_length=3, max_length=80)

class OrderStartResponse(BaseModel):
    started: bool
    message: str

class OrderVerifyRequest(StrictModel):
    session_id: str = Field(min_length=20, max_length=80)
    verification_type: Literal["phone_suffix", "delivery_pincode"]
    verification_value: str = Field(min_length=4, max_length=6)

class OrderVerifyResponse(BaseModel):
    verified: bool
    message: str
    attempts_remaining: int = 0

class TicketRequest(StrictModel):
    session_id: str = Field(min_length=20, max_length=80)
    subject: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5, max_length=3000)
    category: str = Field(default="general", min_length=2, max_length=80)
    order_id: str | None = Field(default=None, min_length=3, max_length=80)


class TicketResponse(BaseModel):
    created: bool
    ticket_id: str | None = None
    message: str
