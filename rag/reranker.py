"""CrossEncoder 재순위화 (DESIGN §4.2, T3.2). 로컬 모델이라 LLM·임베딩 크레딧을 쓰지 않는다."""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol

from common.config import RERANKER_MODEL

if TYPE_CHECKING:  # retriever가 이 모듈을 import하므로 런타임 순환 import 회피
    from rag.retriever import RetrievedChunk

RERANK_FIELDS = ("embed_text", "parent_text", "text")


class PairScorer(Protocol):
    """(질문, 문서) 쌍 점수기. sentence-transformers `CrossEncoder`가 이 인터페이스를 만족한다."""

    def predict(self, sentences: list[tuple[str, str]], **kwargs: object) -> object:
        """쌍마다 관련도 점수(클수록 관련)를 돌려준다."""
        ...


@lru_cache(maxsize=2)
def get_cross_encoder(model: str = RERANKER_MODEL, max_length: int = 512) -> PairScorer:
    """CrossEncoder 싱글톤(모델·max_length별 1회 로딩). sentence-transformers는 여기서만 import."""
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model, max_length=max_length)


def pair_text(chunk: RetrievedChunk, field: str) -> str:
    """재순위화 입력 문서 텍스트. `embed_text`는 payload에서, 없으면 `text`로 대체."""
    if field not in RERANK_FIELDS:
        raise ValueError(
            f"알 수 없는 rerank 필드 '{field}'. 사용 가능: {RERANK_FIELDS}"
        )
    if field == "embed_text":
        return chunk.payload.get("embed_text") or chunk.text
    return getattr(chunk, field) or chunk.text


def rerank(
    question: str,
    chunks: list[RetrievedChunk],
    top_k: int,
    *,
    field: str = "embed_text",
    scorer: PairScorer | None = None,
) -> list[RetrievedChunk]:
    """후보를 CrossEncoder 점수로 다시 정렬해 상위 `top_k`개. `stage_scores`에 `rerank`·`pre_rerank_rank`를 남긴다."""
    if not chunks:
        return []
    scorer = scorer or get_cross_encoder()
    scores = scorer.predict([(question, pair_text(c, field)) for c in chunks])
    reranked = [
        replace(
            c,
            score=float(s),
            stage_scores={**c.stage_scores, "rerank": float(s), "pre_rerank_rank": i},
        )
        for i, (c, s) in enumerate(zip(chunks, scores, strict=True), 1)
    ]
    reranked.sort(key=lambda c: c.score, reverse=True)
    return reranked[:top_k]
