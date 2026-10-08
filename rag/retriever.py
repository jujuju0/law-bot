"""검색 파이프라인 (DESIGN §4). 단계마다 `RetrievedChunk.stage_scores`에 점수를 남긴다."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any

from qdrant_client import QdrantClient, models

from common.config import COLLECTION_NAME, RAW_COLLECTION_NAME
from common.qdrant import get_qdrant_client
from rag.bm25 import get_bm25_index
from rag.chunk_store import get_chunk_store
from rag.config import RetrievalConfig
from rag.embeddings import get_embedding_cache
from rag.query_expansion import get_term_expander, multi_queries
from rag.reranker import get_cross_encoder, rerank
from rag.router import parse_article_refs, parse_definition_chunks
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
    via: str | None = None  # 확장으로 붙은 경우 출발 조 키
    payload: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def keys(self) -> list[str]:
        """이 청크가 대표하는 조 키(naive 청크는 걸친 조 전체)."""
        return [self.article_key, *self.payload.get("covers", [])]

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        score: float,
        stage: str,
        added_by: str = "search",
    ) -> RetrievedChunk:
        """Qdrant/chunks.jsonl payload → RetrievedChunk."""
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
            added_by=added_by,
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


def _dense(
    query: str, cfg: RetrievalConfig, limit: int, stage: str = "dense"
) -> list[RetrievedChunk]:
    vector = get_embedding_cache().embed([query])[0]
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
        RetrievedChunk.from_payload(p.payload or {}, p.score, stage) for p in points
    ]


def _bm25(
    query: str, cfg: RetrievalConfig, limit: int, stage: str = "bm25"
) -> list[RetrievedChunk]:
    if cfg.collection != COLLECTION_NAME and cfg.collection != RAW_COLLECTION_NAME:
        raise ValueError(
            f"BM25는 구조 청크(chunks.jsonl) 컬렉션에서만 지원: {cfg.collection}"
        )
    hits = get_bm25_index().search(query, cfg.sources, limit)
    return [RetrievedChunk.from_payload(p, s, stage) for p, s in hits]


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


def _representative(question: str, key: str) -> dict[str, Any] | None:
    """조 키의 청크 중 질문과 BM25 점수가 가장 높은 것(동점이면 조문 순서상 첫 청크)."""
    payloads = get_chunk_store().article(key)
    if not payloads:
        return None
    scores = get_bm25_index().scores(question)
    return max(payloads, key=lambda p: scores.get(p["chunk_id"], 0.0))


def _route(
    question: str, results: list[RetrievedChunk], cfg: RetrievalConfig
) -> list[RetrievedChunk]:
    """질문에 조·별표 번호가 있으면 해당 조 청크를 맨 앞에 고정한다(원천 필터 적용, 총 top_k 유지)."""
    top_score = results[0].score if results else 1.0
    routed = []
    for cid in parse_definition_chunks(question):
        payload = get_chunk_store().by_id[cid]
        if payload["source_type"] not in cfg.sources:
            continue
        hit = next((c for c in results if c.chunk_id == cid), None)
        if hit is None:
            hit = RetrievedChunk.from_payload(payload, top_score, "router", "router")
        routed.append(replace(hit, stage_scores={**hit.stage_scores, "router": 1.0}))
    for key in parse_article_refs(question):
        if key.split(":", 1)[0] not in cfg.sources:
            continue
        hit = next((c for c in results if c.article_key == key), None)
        if hit is None and (payload := _representative(question, key)) is not None:
            hit = RetrievedChunk.from_payload(payload, top_score, "router", "router")
        if hit is not None:
            routed.append(
                replace(hit, stage_scores={**hit.stage_scores, "router": 1.0})
            )
    if not routed:
        return results
    ids = {c.chunk_id for c in routed}
    rest = [c for c in results if c.chunk_id not in ids]
    return (routed + rest)[: cfg.top_k]


def prepare_queries(question: str, cfg: RetrievalConfig) -> list[str]:
    """검색 질의 목록: [원 질문(또는 Term expansion 결과)] + Multi-Query 재작성(LLM, 캐시 경유)."""
    first = get_term_expander().expand(question) if cfg.use_term_expansion else question
    queries = [first]
    if cfg.use_multi_query:
        queries += [q for q in multi_queries(question, cfg.n_queries) if q != first]
    return queries


def _first_stage(
    queries: list[str], cfg: RetrievalConfig, limit: int
) -> list[RetrievedChunk]:
    """질의마다 dense(+BM25) 순위를 만들고, 순위가 2개 이상이면 RRF로 합친다."""
    rankings = []
    for i, q in enumerate(queries):
        suffix = f"@{i}" if i else ""
        rankings.append(_dense(q, cfg, limit, f"dense{suffix}"))
        if cfg.use_bm25:
            rankings.append(_bm25(q, cfg, limit, f"bm25{suffix}"))
    if len(rankings) == 1:
        return rankings[0]
    return _rrf(rankings, cfg.rrf_k)[:limit]


def _priority_boost(
    ranked: list[RetrievedChunk], cfg: RetrievalConfig
) -> list[RetrievedChunk]:
    """순위 점수 1/(rrf_k+rank)에 원천 우선순위 가산(priority 1: +boost, 2: +boost/2)으로 재정렬."""
    bonus = {1: cfg.priority_boost, 2: cfg.priority_boost / 2}

    def key(item: tuple[int, RetrievedChunk]) -> float:
        rank, c = item
        return 1 / (cfg.rrf_k + rank) + bonus.get(c.payload.get("priority", 3), 0.0)

    return [c for _, c in sorted(enumerate(ranked, 1), key=key, reverse=True)]


def _small_to_big(ranked: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """같은 조(article_key) 청크를 가장 높은 순위 하나로 합친다. 2개 이상 합쳐진 법령 조는 본문을 조 전체로."""
    groups: dict[str, list[RetrievedChunk]] = {}
    for c in ranked:
        groups.setdefault(c.article_key, []).append(c)
    merged = []
    for chunks in groups.values():
        top = chunks[0]
        if len(chunks) > 1 and top.source_type in ("law", "decree"):
            top = replace(
                top,
                text=top.parent_text,
                stage_scores={**top.stage_scores, "merged": len(chunks)},
            )
        merged.append(top)
    return merged


def _expansion_targets(c: RetrievedChunk, kind: str) -> list[str]:
    """확장 대상 조 키. ref: 같은 원천 내 참조, delegation: 위임 상·하위 + 시행령→별표."""
    p = c.payload
    if kind == "ref":
        own = f"{c.source_type}:"
        return [r for r in p.get("refs", []) if r.startswith(own)]
    annex = [r for r in p.get("refs", []) if r.startswith("annex:")]
    return [*p.get("delegates_to", []), *p.get("delegated_from", []), *annex]


def _expand(
    question: str, results: list[RetrievedChunk], cfg: RetrievalConfig, kind: str
) -> list[RetrievedChunk]:
    """상위 `expansion_seed_k`개 청크의 연결 조를 최대 `max_expansion`개 뒤에 덧붙인다(`added_by=kind`).

    delegation은 덧붙인 청크도 다시 시드로 삼아 위임 체인(법 → 영 → 별표)을 따라간다.
    """
    have = {key for c in results for key in c.keys}
    floor = min((c.score for c in results), default=1.0) * 0.9
    queue = list(results[: cfg.expansion_seed_k])
    added: list[RetrievedChunk] = []
    while queue and len(added) < cfg.max_expansion:
        seed = queue.pop(0)
        for key in _expansion_targets(seed, kind):
            if len(added) >= cfg.max_expansion:
                break
            if key in have or key.split(":", 1)[0] not in cfg.sources:
                continue
            if (payload := _representative(question, key)) is None:
                continue
            c = RetrievedChunk.from_payload(payload, floor, kind, kind)
            c.via = seed.article_key
            added.append(c)
            have.add(key)
            if kind == "delegation":
                queue.append(c)
    return results + added


@dataclass
class RetrievalTrace:
    """검색 1회의 최종 결과와 중간 후보(평가의 후보 재현율·API debug용)."""

    results: list[RetrievedChunk]
    candidates: list[RetrievedChunk]  # 1단계(dense/hybrid) 후보, 최대 candidate_k개
    queries: list[str] = field(default_factory=list)  # 실제 검색에 쓴 질의


def _rerank(
    question: str, candidates: list[RetrievedChunk], cfg: RetrievalConfig
) -> list[RetrievedChunk]:
    scorer = get_cross_encoder(max_length=cfg.rerank_max_length)
    return rerank(
        question, candidates, len(candidates), field=cfg.rerank_field, scorer=scorer
    )


def retrieve_with_trace(
    question: str, cfg: RetrievalConfig, queries: list[str] | None = None
) -> RetrievalTrace:
    """질문 → 최종 결과 + 1단계 후보.

    단계: 질의 준비(term/multi-query) → dense(+BM25 → RRF) → rerank → priority boost → small-to-big
    → 상위 top_k → router → ref/delegation expansion(뒤에 덧붙임, 결과는 top_k보다 길 수 있음).
    `queries`를 주면 질의 준비를 건너뛴다(평가에서 LLM 호출을 지연 측정 밖으로 빼기 위함).
    """
    queries = queries or prepare_queries(question, cfg)
    limit = max(cfg.candidate_k, cfg.top_k)
    candidates = _first_stage(queries, cfg, limit)
    ranked = _rerank(question, candidates, cfg) if cfg.use_rerank else candidates
    if cfg.priority_boost:
        ranked = _priority_boost(ranked, cfg)
    if cfg.small_to_big:
        ranked = _small_to_big(ranked)
    results = ranked[: cfg.top_k]
    if cfg.use_router:
        results = _route(question, results, cfg)
    if cfg.use_ref_expansion:
        results = _expand(question, results, cfg, "ref")
    if cfg.use_delegation_expansion:
        results = _expand(question, results, cfg, "delegation")
    return RetrievalTrace(results=results, candidates=candidates, queries=queries)


def warmup(cfg: RetrievalConfig) -> None:
    """설정에 필요한 무거운 객체(BM25 색인, chunk store, CrossEncoder)를 미리 로딩한다(지연 측정·서비스 기동용)."""
    get_bm25_index()
    get_chunk_store()
    if cfg.use_term_expansion:
        get_term_expander()
    if cfg.use_rerank:
        get_cross_encoder(max_length=cfg.rerank_max_length)


def retrieve(question: str, cfg: RetrievalConfig) -> list[RetrievedChunk]:
    """질문 → 최종 결과(확장 청크 포함)."""
    return retrieve_with_trace(question, cfg).results
