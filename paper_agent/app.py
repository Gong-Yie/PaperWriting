"""Local web application for the first, topic-selection development stage."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .clients import ArxivClient, ExternalServiceError, ModelClient, Settings
from .models import (
    CreateTopicRequest,
    DiscussRequest,
    TaskConfiguration,
    TopicDraft,
    TopicSession,
)
from .service import TopicService
from .store import TopicNotFoundError, TopicStateError, TopicStore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_ROOT = Path(__file__).resolve().parent / "static"
logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    data_directory: Path | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        resolved = settings or Settings.from_env(PROJECT_ROOT / ".env")
        store = TopicStore(data_directory or PROJECT_ROOT / "data" / "topics")
        async with httpx.AsyncClient(timeout=90, transport=transport) as client:
            application.state.service = TopicService(
                store, ModelClient(resolved, client), ArxivClient(client)
            )
            logger.info("论文研究工作台已启动，选题档案保存于 %s", store.directory)
            yield

    application = FastAPI(title="论文研究工作台", lifespan=lifespan)
    application.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")

    @application.exception_handler(TopicNotFoundError)
    async def topic_not_found(request: Request, exc: TopicNotFoundError) -> Response:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @application.exception_handler(TopicStateError)
    async def topic_state_error(request: Request, exc: TopicStateError) -> Response:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @application.exception_handler(ExternalServiceError)
    async def external_error(request: Request, exc: ExternalServiceError) -> Response:
        # Report only the domain message; upstream payloads can contain private data.
        logger.warning("选题外部服务请求失败：%s", exc)
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @application.get("/", response_class=FileResponse)
    def index() -> FileResponse:
        return FileResponse(STATIC_ROOT / "index.html")

    @application.get("/api/topics", response_model=list[TopicSession])
    def list_topics(request: Request) -> list[TopicSession]:
        service: TopicService = request.app.state.service
        return service.store.list_topics()

    @application.post("/api/topics", response_model=TopicSession, status_code=201)
    def create_topic(body: CreateTopicRequest, request: Request) -> TopicSession:
        service: TopicService = request.app.state.service
        return service.create(body.existing_title)

    @application.get("/api/topics/{topic_id}", response_model=TopicSession)
    def get_topic(topic_id: UUID, request: Request) -> TopicSession:
        service: TopicService = request.app.state.service
        return service.store.get(topic_id)

    @application.post("/api/topics/{topic_id}/messages", response_model=TopicSession)
    async def discuss_topic(
        topic_id: UUID, body: DiscussRequest, request: Request
    ) -> TopicSession:
        service: TopicService = request.app.state.service
        return await service.discuss(topic_id, body.message)

    @application.post("/api/topics/{topic_id}/confirm", response_model=TopicSession)
    async def confirm_topic(
        topic_id: UUID, body: TopicDraft, request: Request
    ) -> TopicSession:
        service: TopicService = request.app.state.service
        return await service.confirm(topic_id, body)

    @application.put("/api/topics/{topic_id}/configuration", response_model=TopicSession)
    async def configure_topic(
        topic_id: UUID, body: TaskConfiguration, request: Request
    ) -> TopicSession:
        service: TopicService = request.app.state.service
        return await service.configure(topic_id, body)

    return application


app = create_app()
