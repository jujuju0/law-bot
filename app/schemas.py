"""`/ask`·`/health` 요청·응답 스키마 (DESIGN §6)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """질문 요청."""

    question: str = Field(
        ..., min_length=1, max_length=1000, examples=["고영향 인공지능이란 무엇인가요?"]
    )
    debug: bool = Field(
        False, description="검색 후보·단계별 점수·warnings·토큰 사용량 포함"
    )


class SourceOut(BaseModel):
    """근거 1건."""

    article: str = Field(..., examples=["제31조"])
    source_type: str = Field(
        ..., examples=["law"], description="law | decree | annex | admrul | term | expc"
    )
    citation: str = Field(..., examples=["법 제31조 제2항"])
    doc_title: str
    content: str
    score: float
    cited: bool = Field(..., description="답변에서 실제로 인용했는지")
    added_by: str = Field(..., description="search | router | ref | delegation")


class AskResponse(BaseModel):
    """질문 응답 (RFP 스키마 + notice·grounded·data_snapshot)."""

    answer: str
    sources: list[SourceOut]
    notice: str = Field(..., description="AI 생성 표시 (법 제31조)")
    grounded: bool = Field(
        ..., description="유효 인용이 있고 근거 없는 숫자가 없거나, 거절"
    )
    data_snapshot: str | None = Field(None, description="법령 데이터 수집 일자")
    debug: dict[str, Any] | None = Field(
        None, description="debug=true일 때만: 후보·점수·warnings·usage"
    )


class HealthResponse(BaseModel):
    """서비스 상태."""

    status: str = Field(..., examples=["ok", "degraded"])
    qdrant: bool
    collection: str
    points_by_source: dict[str, int]
    preset: str
    data_snapshot: str | None
