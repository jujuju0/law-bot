"""질문 → 검색 → 근거 컨텍스트 → LLM → 후검증 → 응답 (DESIGN §5, T4.2).

서비스(app)·평가(eval --answer)가 같은 `answer()`를 쓴다. LLM 호출은 `common.cache.cached_chat` 경유.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from common.cache import Message, cached_chat
from common.config import SERVICE_RETRIEVAL_PRESET
from common.usage import tracker
from rag.config import RetrievalConfig, get_preset
from rag.grounding import check_answer, match_citation
from rag.loader import load_sources
from rag.prompts import NOTICE, REFUSAL, build_messages, select_context
from rag.retriever import RetrievalTrace, RetrievedChunk, retrieve_with_trace

Chat = Callable[[Sequence[Message]], str]


@dataclass
class Source:
    """응답 근거 1건 (RFP sources 스키마 + 확장 필드)."""

    article: str
    source_type: str
    citation: str
    doc_title: str
    content: str
    score: float
    cited: bool  # 답변에서 실제로 인용했는지
    added_by: str


@dataclass
class AskResult:
    """`/ask` 응답 본문."""

    answer: str
    sources: list[Source]
    notice: str
    grounded: bool
    data_snapshot: str | None
    warnings: list[str] = field(default_factory=list)
    debug: dict[str, Any] | None = None


@lru_cache(maxsize=1)
def data_snapshot() -> str | None:
    """법령 데이터 수집 일자(`data/sources.yaml`의 snapshot_date)."""
    value = load_sources().get("snapshot_date")
    return str(value) if value else None


def _article_label(c: RetrievedChunk) -> str:
    return c.payload.get("article") or c.citation


def _sources(chunks: Sequence[RetrievedChunk], cited: list[str]) -> list[Source]:
    return [
        Source(
            article=_article_label(c),
            source_type=c.source_type,
            citation=c.citation,
            doc_title=c.doc_title,
            content=c.text,
            score=round(c.score, 4),
            cited=any(match_citation(x, [c.citation]) for x in cited),
            added_by=c.added_by,
        )
        for c in chunks
    ]


def _default_chat(messages: Sequence[Message]) -> str:
    return cached_chat(messages)


def answer(
    question: str,
    cfg: RetrievalConfig | None = None,
    *,
    debug: bool = False,
    chat: Chat = _default_chat,
    trace: RetrievalTrace | None = None,
) -> AskResult:
    """질문에 근거 기반 답변을 만든다. 검색 결과가 없으면 LLM을 부르지 않고 거절한다.

    `trace`를 주면 검색을 건너뛴다(평가에서 예산 추정용으로 먼저 검색한 결과 재사용).
    """
    cfg = cfg or get_preset(SERVICE_RETRIEVAL_PRESET)
    start = time.perf_counter()
    before = tracker.snapshot()

    trace = trace or retrieve_with_trace(question, cfg)
    retrieval_ms = (time.perf_counter() - start) * 1000
    context = select_context(trace.results)
    if context:
        raw = chat(build_messages(question, context))
        report = check_answer(
            raw, [c.citation for c in context], [c.text for c in context]
        )
    else:
        raw = REFUSAL
        report = check_answer(REFUSAL, [], [])

    result = AskResult(
        answer=report.answer,
        sources=_sources(context, report.cited),
        notice=NOTICE,
        grounded=report.grounded,
        data_snapshot=data_snapshot(),
        warnings=report.warnings,
    )
    if debug:
        result.debug = {
            "preset": cfg.name,
            "queries": trace.queries,
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            "retrieval_ms": round(retrieval_ms, 1),
            "refused": report.refused,
            "raw_answer": raw,
            "dropped_by_budget": [
                c.citation
                for c in trace.results
                if c.chunk_id not in {k.chunk_id for k in context}
            ],
            "candidates": [
                {
                    "citation": c.citation,
                    "chunk_id": c.chunk_id,
                    "score": round(c.score, 4),
                    "stage_scores": {k: round(v, 4) for k, v in c.stage_scores.items()},
                    "added_by": c.added_by,
                    "via": c.via,
                }
                for c in trace.results
            ],
            "usage": (tracker.snapshot() - before).to_dict(),
        }
    return result
