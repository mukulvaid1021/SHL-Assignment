# models.py
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"


class Message(BaseModel):
    role: MessageRole
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]


class Recommendation(BaseModel):
    name: str
    url: str
    test_type: str


class ChatResponse(BaseModel):
    reply: str
    recommendations: List[Recommendation] = Field(default_factory=list)
    end_of_conversation: bool = False


class HealthResponse(BaseModel):
    status: str = "ok"


class CatalogItem(BaseModel):
    name: str
    url: str
    test_type: str  # K=Knowledge, P=Personality, A=Ability, S=Skills, B=Behavior, C=Competency
    description: str = ""
    duration: Optional[str] = None
    remote_testing: Optional[str] = None  # "Yes" or "No"
    adaptive_testing: Optional[str] = None  # "Yes" or "No"
    categories: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    full_text: str = ""  # Combined text for search