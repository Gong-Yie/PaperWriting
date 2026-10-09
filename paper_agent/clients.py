"""Responses API JSON output and rate-limited arXiv search."""

import asyncio
import json
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, TypedDict
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, Field, ValidationError

from .models import Paper


class ExternalServiceError(RuntimeError):
    """A model or literature service could not return a usable result."""


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str

    @classmethod
    def from_env(cls, path: Path) -> "Settings":
        values = dotenv_values(path)
        resolved = {
            name: os.environ.get(name) or values.get(name)
            for name in ("API_KEY", "BASE_URL", "MODEL")
        }
        missing = [name for name, value in resolved.items() if not value]
        if missing:
            raise ValueError(f"请在 .env 配置以下项目：{', '.join(missing)}")
        return cls(
            api_key=str(resolved["API_KEY"]),
            base_url=str(resolved["BASE_URL"]),
            model=str(resolved["MODEL"]),
        )


class ModelMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class ResponseContentPart(BaseModel):
    type: str
    text: str | None = None


class ResponseOutputItem(BaseModel):
    type: str
    role: str | None = None
    content: list[ResponseContentPart] = Field(default_factory=list)


class ModelResponse(BaseModel):
    status: str
    output: list[ResponseOutputItem]


class ModelClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client

    async def complete[T: BaseModel](
        self, messages: list[ModelMessage], result_type: type[T]
    ) -> T:
        schema_message: ModelMessage = {
            "role": "system",
            "content": "只输出 JSON，必须满足以下结构："
            + json.dumps(result_type.model_json_schema(), ensure_ascii=False),
        }
        try:
            response = await self.client.post(
                f"{self.settings.base_url.rstrip('/')}/responses",
                headers={"Authorization": f"Bearer {self.settings.api_key}"},
                json={
                    "model": self.settings.model,
                    "input": [schema_message, *messages],
                    "text": {"format": {"type": "json_object"}},
                    "max_output_tokens": 4096,
                    "store": False,
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ExternalServiceError(
                f"模型接口返回 HTTP {exc.response.status_code}，请检查模型配置或账户。"
            ) from exc
        except httpx.RequestError as exc:
            raise ExternalServiceError("模型请求未完成，请检查网络后重新发送。") from exc
        try:
            result = ModelResponse.model_validate_json(response.content)
            if result.status == "failed":
                raise ExternalServiceError("模型服务未能完成请求，请检查服务状态。")
            if result.status != "completed":
                raise ExternalServiceError("模型回复未完整生成，请重新发送或缩小问题范围。")
            text_parts: list[str] = []
            for item in result.output:
                if item.type != "message" or item.role != "assistant":
                    continue
                for part in item.content:
                    if part.type == "refusal":
                        raise ExternalServiceError("模型拒绝了该请求，请调整研究问题。")
                    if part.type == "output_text" and part.text is not None:
                        text_parts.append(part.text)
            output_text = "".join(text_parts)
            if not output_text:
                raise ExternalServiceError("模型没有返回文本结果，请重新发送。")
            return result_type.model_validate_json(output_text)
        except ValidationError as exc:
            raise ExternalServiceError("模型回复不符合选题档案结构，请重新发送。") from exc


class ArxivClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self._lock = asyncio.Lock()
        self._last_request: float | None = None

    async def search(self, query: str) -> list[Paper]:
        # arXiv asks clients to space consecutive requests by at least 3 seconds.
        async with self._lock:
            if self._last_request is not None:
                await asyncio.sleep(max(0, 3 - (time.monotonic() - self._last_request)))
            self._last_request = time.monotonic()
            try:
                response = await self.client.get(
                    "https://export.arxiv.org/api/query",
                    params={
                        "search_query": query,
                        "start": 0,
                        "max_results": 6,
                        "sortBy": "relevance",
                        "sortOrder": "descending",
                    },
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ExternalServiceError(
                    f"arXiv 检索返回 HTTP {exc.response.status_code}，请稍后再试。"
                ) from exc
            except httpx.RequestError as exc:
                raise ExternalServiceError("arXiv 检索未完成，请检查网络后重新发送。") from exc
        return self._parse(response.content)

    @staticmethod
    def _parse(content: bytes) -> list[Paper]:
        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        papers: list[Paper] = []
        try:
            feed = ET.fromstring(content)
            if feed.tag != "{http://www.w3.org/2005/Atom}feed":
                raise ValueError("Expected an Atom feed")
            for entry in feed.findall("atom:entry", namespace):
                url = entry.findtext("atom:id", default="", namespaces=namespace)
                parsed_url = urlsplit(url)
                if parsed_url.hostname != "arxiv.org" or not parsed_url.path.startswith(
                    "/abs/"
                ):
                    raise ValueError("Unexpected arXiv entry identifier")
                papers.append(
                    Paper(
                        paper_id=parsed_url.path.removeprefix("/abs/"),
                        title=" ".join(
                            entry.findtext(
                                "atom:title", default="", namespaces=namespace
                            ).split()
                        ),
                        authors=[
                            author.findtext(
                                "atom:name", default="", namespaces=namespace
                            )
                            for author in entry.findall("atom:author", namespace)
                        ],
                        abstract=entry.findtext(
                            "atom:summary", default="", namespaces=namespace
                        ).strip(),
                        published=date.fromisoformat(
                            entry.findtext(
                                "atom:published", default="", namespaces=namespace
                            )[:10]
                        ),
                        url=f"https://arxiv.org{parsed_url.path}",
                    )
                )
        except (ET.ParseError, ValueError, ValidationError) as exc:
            raise ExternalServiceError("arXiv 返回了无法解析的论文记录。") from exc
        return papers
