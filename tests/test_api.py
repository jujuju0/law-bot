"""app/main.py API 테스트 (파이프라인·Qdrant는 가짜로 대체)."""

import pytest
from fastapi.testclient import TestClient

from app import main
from rag.pipeline import AskResult, Source
from rag.prompts import NOTICE, REFUSAL

SOURCE = Source(
    article="제31조",
    source_type="law",
    citation="법 제31조 제2항",
    doc_title="인공지능 발전과 신뢰 기반 조성 등에 관한 기본법",
    content="② 인공지능사업자는 생성형 인공지능 ...",
    score=0.91,
    cited=True,
    added_by="search",
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "warmup", lambda cfg: None)
    calls = []

    def fake_answer(question, cfg, *, debug=False):
        calls.append((question, cfg.name, debug))
        if "날씨" in question:
            return AskResult(REFUSAL, [], NOTICE, True, "2026-10-08")
        return AskResult(
            answer="생성형 AI 결과물임을 표시해야 합니다 [법 제31조 제2항].",
            sources=[SOURCE],
            notice=NOTICE,
            grounded=True,
            data_snapshot="2026-10-08",
            warnings=["근거 텍스트에 없는 숫자: 30일"] if debug else [],
            debug={"latency_ms": 12.3} if debug else None,
        )

    monkeypatch.setattr(main.pipeline, "answer", fake_answer)
    with TestClient(main.app) as c:
        c.calls = calls
        yield c


def test_ask_schema(client) -> None:
    r = client.post("/ask", json={"question": "AI로 만든 이미지에 표시해야 하나요?"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "answer",
        "sources",
        "notice",
        "grounded",
        "data_snapshot",
        "debug",
    }
    assert body["sources"][0] == {
        "article": "제31조",
        "source_type": "law",
        "citation": "법 제31조 제2항",
        "doc_title": SOURCE.doc_title,
        "content": SOURCE.content,
        "score": 0.91,
        "cited": True,
        "added_by": "search",
    }
    assert body["notice"] == NOTICE and body["grounded"] is True
    assert body["data_snapshot"] == "2026-10-08" and body["debug"] is None
    assert client.calls[0][1] == main.SERVICE_RETRIEVAL_PRESET


def test_ask_debug_includes_warnings(client) -> None:
    body = client.post("/ask", json={"question": "질문", "debug": True}).json()
    assert body["debug"]["latency_ms"] == 12.3
    assert body["debug"]["warnings"] == ["근거 텍스트에 없는 숫자: 30일"]


def test_ask_refusal(client) -> None:
    body = client.post("/ask", json={"question": "내일 날씨 어때?"}).json()
    assert body["answer"] == REFUSAL and body["sources"] == []


@pytest.mark.parametrize("payload", [{}, {"question": ""}, {"question": "x" * 1001}])
def test_ask_validation(client, payload) -> None:
    assert client.post("/ask", json=payload).status_code == 422


def test_health(client, monkeypatch) -> None:
    sources = client.app.state.cfg.sources
    monkeypatch.setattr(
        main, "_points_by_source", lambda col: dict.fromkeys(sources, 5)
    )
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["qdrant"] is True
    assert body["preset"] == main.SERVICE_RETRIEVAL_PRESET
    assert body["data_snapshot"] == "2026-10-08"


def test_health_degraded_when_qdrant_down(client, monkeypatch) -> None:
    def down(col):
        raise ConnectionError("refused")

    monkeypatch.setattr(main, "_points_by_source", down)
    body = client.get("/health").json()
    assert body["status"] == "degraded" and body["qdrant"] is False


def test_ask_backend_error_is_503(client, monkeypatch) -> None:
    def broken(question, cfg, *, debug=False):
        raise ConnectionError("qdrant down")

    monkeypatch.setattr(main.pipeline, "answer", broken)
    r = client.post("/ask", json={"question": "질문"})
    assert r.status_code == 503 and "ConnectionError" in r.json()["detail"]
