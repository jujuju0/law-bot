"""AI 기본법 근거 기반 QA API (DESIGN §6). 런타임에 law.go.kr을 호출하지 않는다.

실행: uv run uvicorn app.main:app --reload  (:8000/docs)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from qdrant_client import models

from app.schemas import AskRequest, AskResponse, HealthResponse
from common.config import SERVICE_RETRIEVAL_PRESET
from common.qdrant import get_qdrant_client
from rag import pipeline
from rag.config import get_preset
from rag.retriever import warmup

logger = logging.getLogger(__name__)
SOURCE_TYPES = ("law", "decree", "annex", "admrul", "term", "expc")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """기동 시 서비스 프리셋을 확정하고 BM25·chunk store·reranker 등을 미리 로딩한다."""
    app.state.cfg = get_preset(SERVICE_RETRIEVAL_PRESET)
    warmup(app.state.cfg)
    logger.info("서비스 프리셋 %s 로딩 완료", app.state.cfg.name)
    yield


app = FastAPI(
    title="AI 기본법 QA",
    description="「인공지능 발전과 신뢰 기반 조성 등에 관한 기본법」과 하위 법령 근거 기반 질의응답",
    version="0.1.0",
    lifespan=lifespan,
)


@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    """질문 → 근거 기반 답변. 근거가 없으면 거절 문구, 답변에는 citation과 AI 생성 표시가 붙는다."""
    try:
        result = await run_in_threadpool(
            pipeline.answer, req.question, app.state.cfg, debug=req.debug
        )
    except Exception as e:  # Qdrant·임베딩·LLM 게이트웨이 오류를 503으로 통일 (re-raise)
        logger.exception("답변 생성 실패")
        raise HTTPException(
            status_code=503,
            detail=f"검색·생성 백엔드 오류({type(e).__name__}). /health로 Qdrant 상태를 확인하세요.",
        ) from e
    body = asdict(result)
    if req.debug and body["debug"] is not None:
        body["debug"]["warnings"] = body["warnings"]
    body.pop("warnings")
    return AskResponse(**body)


def _points_by_source(collection: str) -> dict[str, int]:
    client = get_qdrant_client()
    counts = {}
    for s in SOURCE_TYPES:
        flt = models.Filter(
            must=[
                models.FieldCondition(
                    key="source_type", match=models.MatchValue(value=s)
                )
            ]
        )
        if n := client.count(collection, count_filter=flt, exact=True).count:
            counts[s] = n
    return counts


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Qdrant 연결, 원천별 포인트 수, 서비스 프리셋, 데이터 수집 일자."""
    cfg = app.state.cfg
    try:
        counts = await run_in_threadpool(_points_by_source, cfg.collection)
        ok = True
    except Exception as e:  # noqa: BLE001 — 상태 점검은 어떤 연결 오류든 degraded로 보고
        logger.warning("Qdrant 상태 확인 실패: %s", e)
        counts, ok = {}, False
    missing = [s for s in cfg.sources if s not in counts]
    return HealthResponse(
        status="ok" if ok and not missing else "degraded",
        qdrant=ok,
        collection=cfg.collection,
        points_by_source=counts,
        preset=cfg.name,
        data_snapshot=pipeline.data_snapshot(),
    )
