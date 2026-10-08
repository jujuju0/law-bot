"""검색 파이프라인 (DESIGN §4). 단계마다 `RetrievedChunk.stage_scores`에 점수를 남긴다."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any

from qdrant_client import QdrantClient, models

from common.config import COLLECTION_NAME, RAW_COLLECTION_NAME
from common.qdrant import get_qdrant_client
from rag.bm25 import get_bm25_index
from rag.config import RetrievalConfig
from rag.embeddings import get_embedding_cache
from rag.reranker import get_cross_encoder, rerank
from rag.vectorstore import VECTOR_NAME


@dataclass
class RetrievedChunk:
    """검색 결과 1건 (DESIGN §4.3). payload 전체는 `payload`에 보존한다."""

    chunk_id: str
    source_type: str
    citation: str
    doc_title: str
    text: str
    parent_text: str
    article_key: str
    score: float
    stage_scores: dict[str, float] = field(default_factory=dict)
    added_by: str = "search"  # search | router | ref | delegation
    payload: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def keys(self) -> list[str]:
        """이 청크가 대표하는 조 키(naive 청크는 걸친 조 전체)."""
        return [self.article_key, *self.payload.get("covers", [])]

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any], score: float, stage: str
    ) -> RetrievedChunk:
        """Qdrant payload → RetrievedChunk."""
        return cls(
            chunk_id=payload["chunk_id"],
            source_type=payload["source_type"],
            citation=payload["citation"],
            doc_title=payload["doc_title"],
            text=payload["text"],
            parent_text=payload["parent_text"],
            article_key=payload["article_key"],
            score=score,
            stage_scores={stage: score},
            payload=payload,
        )


@lru_cache(maxsize=1)
def _client() -> QdrantClient:
    return get_qdrant_client()


def _source_filter(sources: tuple[str, ...]) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(
                key="source_type", match=models.MatchAny(any=list(sources))
            )
        ]
    )


def _dense(question: str, cfg: RetrievalConfig, limit: int) -> list[RetrievedChunk]:
    vector = get_embedding_cache().embed([question])[0]
    points = (
        _client()
        .query_points(
            cfg.collection,
            query=vector,
            using=VECTOR_NAME,
            query_filter=_source_filter(cfg.sources),
            limit=limit,
            with_payload=True,
        )
        .points
    )
    return [
        RetrievedChunk.from_payload(p.payload or {}, p.score, "dense") for p in points
    ]


def _bm25(question: str, cfg: RetrievalConfig, limit: int) -> list[RetrievedChunk]:
    if cfg.collection != COLLECTION_NAME and cfg.collection != RAW_COLLECTION_NAME:
        raise ValueError(
            f"BM25는 구조 청크(chunks.jsonl) 컬렉션에서만 지원: {cfg.collection}"
        )
    hits = get_bm25_index().search(question, cfg.sources, limit)
    return [RetrievedChunk.from_payload(p, s, "bm25") for p, s in hits]


def _rrf(rankings: list[list[RetrievedChunk]], k: int) -> list[RetrievedChunk]:
    """Reciprocal Rank Fusion: score(d) = Σ 1/(k + rank_i(d)), rank는 1부터. 단계 점수는 합쳐 보존."""
    fused: dict[str, RetrievedChunk] = {}
    for ranking in rankings:
        for rank, c in enumerate(ranking, 1):
            base = fused.setdefault(c.chunk_id, replace(c, score=0.0, stage_scores={}))
            base.score += 1 / (k + rank)
            base.stage_scores.update(c.stage_scores)
            base.stage_scores[f"{next(iter(c.stage_scores))}_rank"] = rank
    for c in fused.values():
        c.stage_scores["rrf"] = c.score
    return sorted(fused.values(), key=lambda c: c.score, reverse=True)


@dataclass
class RetrievalTrace:
    """검색 1회의 최종 결과와 중간 후보(평가의 후보 재현율·API debug용)."""

    results: list[RetrievedChunk]
    candidates: list[RetrievedChunk]  # 1단계(dense/hybrid) 후보, 최대 candidate_k개


def _rerank(
    question: str, candidates: list[RetrievedChunk], cfg: RetrievalConfig
) -> list[RetrievedChunk]:
    scorer = get_cross_encoder(max_length=cfg.rerank_max_length)
    return rerank(
        question, candidates, cfg.top_k, field=cfg.rerank_field, scorer=scorer
    )


def retrieve_with_trace(question: str, cfg: RetrievalConfig) -> RetrievalTrace:
    """질문 → 최종 상위 `cfg.top_k`개 + 1단계 후보. 단계: dense (+ BM25 → RRF) (+ rerank)."""
    limit = max(cfg.candidate_k, cfg.top_k)
    candidates = _dense(question, cfg, limit)
    if cfg.use_bm25:
        candidates = _rrf([candidates, _bm25(question, cfg, limit)], cfg.rrf_k)[:limit]
    results = (
        _rerank(question, candidates, cfg)
        if cfg.use_rerank
        else candidates[: cfg.top_k]
    )
    return RetrievalTrace(results=results, candidates=candidates)


def warmup(cfg: RetrievalConfig) -> None:
    """설정에 필요한 무거운 객체(BM25 색인, CrossEncoder)를 미리 로딩한다(지연 측정·서비스 기동용)."""
    if cfg.use_bm25:
        get_bm25_index()
    if cfg.use_rerank:
        get_cross_encoder(max_length=cfg.rerank_max_length)


def retrieve(question: str, cfg: RetrievalConfig) -> list[RetrievedChunk]:
    """질문 → 상위 `cfg.top_k`개 청크."""
    return retrieve_with_trace(question, cfg).results
