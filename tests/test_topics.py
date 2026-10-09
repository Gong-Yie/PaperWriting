"""Behavior tests: retrieval, complete archives, state boundaries and failures."""

import json
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from paper_agent.app import create_app
from paper_agent.clients import Settings
from paper_agent.models import TopicDraft

SETTINGS = Settings("fake-test-key", "https://model.test", "test-model")
ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2601.00001v1</id>
    <title>Research on small models</title>
    <summary>A real-looking test abstract about evaluating small models.</summary>
    <published>2026-01-01T00:00:00Z</published>
    <author><name>Test Author</name></author>
  </entry>
</feed>"""
EMPTY_FEED = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'


@pytest.fixture
def draft() -> TopicDraft:
    return TopicDraft(
        title="小模型推理研究",
        research_question="有限资源下如何衡量小模型的推理能力？",
        innovation_points=["比较不同资源约束下的推理表现"],
        experiment_plan="在固定数据划分上比较基线和候选方法。",
        resources="GPU 型号和数据集需要在任务配置时确认。",
    )


def completion(payload: str, finish_reason: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"content": payload}, "finish_reason": finish_reason}
            ]
        },
    )


@pytest.mark.parametrize("existing_title", [None, "已经确定的研究题目"])
def test_discuss_confirm_configure_and_reload_complete_archive(
    tmp_path: Path, draft: TopicDraft, existing_title: str | None
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "export.arxiv.org":
            assert request.url.params["search_query"] == 'all:"small models"'
            return httpx.Response(200, text=ATOM_FEED)
        payload = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer fake-test-key"
        if len(requests) == 1:
            return completion(json.dumps({"query": 'all:"small models"'}))
        assert "2601.00001v1" in payload["messages"][1]["content"]
        return completion(
            json.dumps(
                {
                    "reply": "结合 arXiv:2601.00001v1，建议进一步验证该研究问题。",
                    "draft": draft.model_dump(),
                }
            )
        )

    app = create_app(SETTINGS, tmp_path, httpx.MockTransport(handle))
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        topic = client.post(
            "/api/topics", json={"existing_title": existing_title}
        ).json()
        topic_id = topic["id"]
        response = client.post(
            f"/api/topics/{topic_id}/messages", json={"message": "想研究小模型推理"}
        )
        assert response.status_code == 200
        result = response.json()
        assert result["draft"]["title"] == (existing_title or draft.title)
        assert [message["role"] for message in result["messages"]] == [
            "user", "assistant"
        ]
        assert result["papers"][0]["authors"] == ["Test Author"]
        assert result["papers"][0]["url"] == "https://arxiv.org/abs/2601.00001v1"
        assert not result["confirmed"]
        final_draft = result["draft"]
        final_draft["research_question"] = "用户修订后的研究问题"
        saved = client.post(f"/api/topics/{topic_id}/confirm", json=final_draft)
        assert saved.status_code == 200
        assert saved.json()["confirmed"]
        configuration = {
            "language": "en",
            "purpose": "submission",
            "target": "Test Conference",
            "formats": ["docx", "latex", "pdf", "markdown"],
            "execution": "remote",
            "max_minutes": 120,
            "max_experiments": 3,
            "max_model_calls": 20,
        }
        configured = client.put(
            f"/api/topics/{topic_id}/configuration", json=configuration
        )
        assert configured.status_code == 200
        assert configured.json()["configuration"] == configuration

    with TestClient(create_app(SETTINGS, tmp_path)) as restarted:
        restored = restarted.get(f"/api/topics/{topic_id}").json()
        assert restored["draft"]["research_question"] == "用户修订后的研究问题"
        assert restored["configuration"] == configuration
        assert restored["messages"] == result["messages"]
        assert restored["papers"] == result["papers"]
        assert restarted.get("/api/topics").json() == [restored]
    assert len(requests) == 3
    assert "fake-test-key" not in (tmp_path / f"{topic_id}.json").read_text(
        encoding="utf-8"
    )


def test_no_results_and_followup_clear_outdated_draft(
    tmp_path: Path, draft: TopicDraft, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_calls = 0
    monkeypatch.setattr("paper_agent.clients.asyncio.sleep", AsyncMock())

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal model_calls
        if request.url.host == "export.arxiv.org":
            return httpx.Response(200, text=EMPTY_FEED)
        model_calls += 1
        if model_calls % 2:
            return completion('{"query":"all:example"}')
        return completion(
            json.dumps(
                {
                    "reply": "暂无检索结果，请补充研究要求。",
                    "draft": draft.model_dump() if model_calls == 2 else None,
                }
            )
        )

    with TestClient(
        create_app(SETTINGS, tmp_path, httpx.MockTransport(handle))
    ) as client:
        topic_id = client.post("/api/topics", json={}).json()["id"]
        first = client.post(
            f"/api/topics/{topic_id}/messages", json={"message": "原研究方向"}
        )
        assert first.status_code == 200
        assert first.json()["papers"] == []
        assert first.json()["draft"] is not None
        followup = client.post(
            f"/api/topics/{topic_id}/messages", json={"message": "改成另一研究方向"}
        )
        assert followup.status_code == 200
        assert followup.json()["draft"] is None
        assert len(followup.json()["messages"]) == 4


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("model_http", "模型接口返回 HTTP 401"),
        ("model_timeout", "模型请求未完成"),
        ("model_json", "模型回复不符合"),
        ("model_truncated", "模型回复未完整生成"),
        ("arxiv_http", "arXiv 检索返回 HTTP 503"),
        ("arxiv_xml", "arXiv 返回了无法解析"),
    ],
)
def test_upstream_failure_is_explicit_and_does_not_save_fake_results(
    tmp_path: Path, failure: str, expected: str
) -> None:
    request_count = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request.url.host == "export.arxiv.org":
            if failure == "arxiv_http":
                return httpx.Response(503)
            return httpx.Response(200, text="<not-valid-xml")
        if failure == "model_http":
            return httpx.Response(401)
        if failure == "model_timeout":
            raise httpx.ReadTimeout("test timeout", request=request)
        if failure == "model_json":
            return completion("not JSON")
        if failure == "model_truncated":
            return completion('{"query":"example"}', finish_reason="length")
        return completion('{"query":"all:example"}')

    with TestClient(
        create_app(SETTINGS, tmp_path, httpx.MockTransport(handle))
    ) as client:
        topic_id = client.post("/api/topics", json={}).json()["id"]
        response = client.post(
            f"/api/topics/{topic_id}/messages", json={"message": "研究方向"}
        )
        assert response.status_code == 502
        assert expected in response.json()["detail"]
        restored = client.get(f"/api/topics/{topic_id}").json()
        assert restored["messages"] == []
        assert restored["papers"] == []
        assert restored["draft"] is None
    assert request_count == (2 if failure.startswith("arxiv") else 1)


@pytest.mark.parametrize("state", ["missing", "unconfirmed", "confirmed", "invalid"])
def test_state_and_validation_boundaries(
    tmp_path: Path, draft: TopicDraft, state: str
) -> None:
    def no_network(request: httpx.Request) -> httpx.Response:
        pytest.fail("State and validation failures must not call external services")

    with TestClient(
        create_app(SETTINGS, tmp_path, httpx.MockTransport(no_network))
    ) as client:
        if state == "missing":
            assert client.get(f"/api/topics/{uuid4()}").status_code == 404
            return
        topic_id = client.post("/api/topics", json={}).json()["id"]
        if state == "unconfirmed":
            assert client.put(
                f"/api/topics/{topic_id}/configuration", json={}
            ).status_code == 409
            return
        if state == "invalid":
            assert client.post(
                f"/api/topics/{topic_id}/messages", json={"message": "   "}
            ).status_code == 422
            assert client.put(
                f"/api/topics/{topic_id}/configuration", json={"max_minutes": 0}
            ).status_code == 422
            assert client.post(
                f"/api/topics/{topic_id}/confirm", json={"title": "只有标题"}
            ).status_code == 422
            return
        assert client.post(
            f"/api/topics/{topic_id}/confirm", json=draft.model_dump()
        ).status_code == 200
        assert client.post(
            f"/api/topics/{topic_id}/messages", json={"message": "再讨论"}
        ).status_code == 409
        assert client.post(
            f"/api/topics/{topic_id}/confirm", json=draft.model_dump()
        ).status_code == 409
