from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=6000)
    conversation_id: str | None = Field(default=None, max_length=36)
    personality: str | None = Field(default=None, max_length=40)


class ChatResponse(BaseModel):
    answer: str
    conversation_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    tool_executions: list[dict[str, Any]] = Field(default_factory=list)


class MessageView(BaseModel):
    role: str
    content: str
    created_at: datetime


class ConversationView(BaseModel):
    conversation_id: str
    title: str
    personality: str
    messages: list[MessageView]
