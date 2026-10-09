"""Validated topic records and task configuration."""

from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Paper(BaseModel):
    paper_id: str
    title: str
    authors: list[str]
    abstract: str
    published: date
    url: HttpUrl


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=24000)


class TopicDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=500)
    research_question: str = Field(min_length=1, max_length=12000)
    innovation_points: list[str] = Field(min_length=1, max_length=12)
    experiment_plan: str = Field(min_length=1, max_length=12000)
    resources: str = Field(min_length=1, max_length=12000)


class TaskConfiguration(BaseModel):
    language: Literal["zh", "en"] = "zh"
    purpose: Literal["submission", "thesis", "research"] = "research"
    target: str = Field(default="", max_length=500)
    formats: list[Literal["docx", "latex", "pdf", "markdown"]] = Field(
        default_factory=lambda: ["markdown"], min_length=1, max_length=4
    )
    execution: Literal["local", "remote"] = "local"
    max_minutes: int | None = Field(default=None, gt=0)
    max_experiments: int | None = Field(default=None, gt=0)
    max_model_calls: int | None = Field(default=None, gt=0)


class TopicSession(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    existing_title: str | None = Field(default=None, min_length=1, max_length=500)
    messages: list[ChatMessage] = Field(default_factory=list)
    papers: list[Paper] = Field(default_factory=list)
    draft: TopicDraft | None = None
    confirmed: bool = False
    configuration: TaskConfiguration = Field(default_factory=TaskConfiguration)


class SearchQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=500)


class DiscussionResult(BaseModel):
    reply: str = Field(min_length=1, max_length=24000)
    draft: TopicDraft | None


class CreateTopicRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    existing_title: str | None = Field(default=None, min_length=1, max_length=500)


class DiscussRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=6000)
