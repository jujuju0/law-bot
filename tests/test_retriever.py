"""rag/retriever.py · rag/reranker.py 단위테스트 (Qdrant·임베딩 API 없이).

실제 CrossEncoder 테스트는 모델 다운로드(약 2GB)가 필요하므로 `RUN_RERANK_MODEL=1`일 때만 돈다.
"""

import os
from dataclasses import asdict, replace

import pytest

from rag import retriever
from rag.config import get_preset
from rag.reranker import pair_text, rerank
from rag.retriever import RetrievedChunk, retrieve_with_trace
from rag.router import parse_article_refs


def chunk(chunk_id: str, text: str, score: float = 0.0, **payload) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_type="law",
        citation=chunk_id,
        doc_title="",
        text=text,
        parent_text=payload.pop("parent_text", f"{text} (조 전체)"),
        article_key=f"law:{chunk_id}",
        score=score,
        stage_scores={"rrf": score},
        payload={"embed_text": f"[헤더] {text}", **payload},
    )


class KeywordScorer:
    """문서에 키워드가 있으면 1점 — 입력 쌍을 기록해 필드 선택도 검증한다."""

    def __init__(self, keyword: str) -> None:
        self.keyword = keyword
        self.pairs: list[tuple[str, str]] = []

    def predict(self, sentences: list[tuple[str, str]], **_: object) -> list[float]:
        self.pairs.extend(sentences)
        return [float(self.keyword in doc) for _, doc in sentences]


CANDIDATES = [
    chunk("a3", "다른 조문", 0.03),
    chunk("a12", "제31조에 따른 표시", 0.02),
    chunk("a31", "투명성 확보 의무", 0.01),
]


def test_rerank_reorders_and_keeps_stage_scores() -> None:
    out = rerank("31조 요약", CANDIDATES, top_k=2, scorer=KeywordScorer("투명성"))
    assert [c.chunk_id for c in out] == ["a31", "a3"]
    top = out[0]
    assert top.score == 1.0
    assert top.stage_scores == {"rrf": 0.01, "rerank": 1.0, "pre_rerank_rank": 3}
    assert CANDIDATES[2].score == 0.01  # 원본 후보는 변경하지 않음


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("embed_text", "[헤더] 투명성 확보 의무"),
        ("parent_text", "투명성 확보 의무 (조 전체)"),
        ("text", "투명성 확보 의무"),
    ],
)
def test_rerank_input_field(field: str, expected: str) -> None:
    scorer = KeywordScorer("x")
    rerank("q", CANDIDATES[2:], top_k=1, field=field, scorer=scorer)
    assert scorer.pairs == [("q", expected)]


def test_pair_text_fallbacks_and_invalid_field() -> None:
    bare = replace(CANDIDATES[0], payload={}, parent_text="")
    assert pair_text(bare, "embed_text") == bare.text
    assert pair_text(bare, "parent_text") == bare.text
    with pytest.raises(ValueError):
        pair_text(bare, "citation")


def test_rerank_empty() -> None:
    assert rerank("q", [], top_k=5, scorer=KeywordScorer("x")) == []


def test_retrieve_with_trace_reranks_candidates(monkeypatch) -> None:
    scorer = KeywordScorer("투명성")
    monkeypatch.setattr(
        retriever, "_dense", lambda q, cfg, limit, stage="dense": list(CANDIDATES)
    )
    monkeypatch.setattr(
        retriever, "_bm25", lambda q, cfg, limit, stage="dense": list(CANDIDATES)
    )
    monkeypatch.setattr(retriever, "get_cross_encoder", lambda **_: scorer)

    cfg = replace(get_preset("E4_rerank"), top_k=2)
    trace = retrieve_with_trace("31조 요약", cfg)
    assert trace.results[0].chunk_id == "a31"
    assert "rerank" in trace.results[0].stage_scores
    # 후보 재현율은 rerank 전 1단계 후보로 측정한다
    assert [c.chunk_id for c in trace.candidates] == ["a3", "a12", "a31"]

    trace_off = retrieve_with_trace("31조 요약", get_preset("E3_hybrid"))
    assert trace_off.results[0].chunk_id == "a3"
    assert scorer.pairs and len(scorer.pairs) == len(CANDIDATES)  # E3에서는 호출 안 됨


@pytest.mark.skipif(
    os.getenv("RUN_RERANK_MODEL") != "1", reason="CrossEncoder 모델 다운로드 필요"
)
def test_real_reranker_lifts_q009() -> None:
    """E3 악화 문항 q009("31조 요약")가 BM25 후보 위 rerank로 top-3에 드는지(실제 모델)."""
    from rag.bm25 import get_bm25_index

    question = "인공지능기본법 31조를 요약해 주세요."
    hits = get_bm25_index().search(question, ("law",), 20)
    candidates = [RetrievedChunk.from_payload(p, s, "bm25") for p, s in hits]
    out = rerank(question, candidates, top_k=3)
    assert "law:a31" in [c.article_key for c in out], [
        asdict(c)["citation"] for c in out
    ]


# ---------------------------------------------------------------------------
# Router (T3.3) — chunks.jsonl만 사용
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("question", "keys"),
    [
        ("법 제28조는 무엇에 관한 조문인가요?", ["law:a28"]),
        ("시행령 25조 내용 알려줘", ["decree:a25"]),
        ("인공지능기본법 31조를 요약해 주세요.", ["law:a31"]),
        ("영 제24조에서 정한 기준을 알려주세요.", ["decree:a24"]),
        ("영 제1조의2와 법 제3조", ["decree:a1_2", "law:a3"]),
        ("법 제31조제2항", ["law:a31"]),
        ("시행령 별표 2 과태료", ["annex:2"]),
        ("매출 1조원 이상이면?", []),
        ("고영향 인공지능이 뭐야?", []),
    ],
)
def test_parse_article_refs(question: str, keys: list[str]) -> None:
    assert parse_article_refs(question) == keys


def test_router_pins_article_first(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever, "_dense", lambda q, cfg, limit, stage="dense": list(CANDIDATES)
    )
    cfg = replace(get_preset("E2_header"), use_router=True, top_k=3)
    out = retrieve_with_trace("인공지능기본법 28조를 요약해 주세요.", cfg).results
    assert len(out) == 3
    assert out[0].article_key == "law:a28"
    assert out[0].added_by == "router"
    assert out[0].stage_scores["router"] == 1.0
    assert [c.chunk_id for c in out[1:]] == ["a3", "a12"]


def test_router_respects_sources(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever, "_dense", lambda q, cfg, limit, stage="dense": list(CANDIDATES)
    )
    law_only = replace(get_preset("E2_header"), use_router=True)
    out = retrieve_with_trace("시행령 25조 내용 알려줘", law_only).results
    assert all(c.added_by == "search" for c in out)

    with_decree = replace(law_only, sources=("law", "decree"))
    out = retrieve_with_trace("시행령 25조 내용 알려줘", with_decree).results
    assert out[0].article_key == "decree:a25"


def test_router_moves_existing_hit_to_front(monkeypatch) -> None:
    found = chunk("x", "본문", 0.5)
    found.article_key = "law:a28"
    monkeypatch.setattr(
        retriever, "_dense", lambda q, cfg, limit, stage="dense": [*CANDIDATES, found]
    )
    cfg = replace(get_preset("E2_header"), use_router=True)
    out = retrieve_with_trace("법 제28조는?", cfg).results
    assert out[0].chunk_id == "x"
    assert out[0].added_by == "search"
    assert len({c.chunk_id for c in out}) == len(out)


# ---------------------------------------------------------------------------
# 질의 준비·확장 단계 (T3.4·T3.5·T3.7·T3.8) — 실제 chunks.jsonl payload 사용
# ---------------------------------------------------------------------------
def store_chunk(chunk_id: str, score: float = 0.5) -> RetrievedChunk:
    from rag.chunk_store import get_chunk_store

    return RetrievedChunk.from_payload(
        get_chunk_store().by_id[chunk_id], score, "dense"
    )


def test_prepare_queries_term_and_multi_query(monkeypatch) -> None:
    monkeypatch.setattr(
        retriever, "multi_queries", lambda q, n: ["국내대리인 지정 의무", "질문"][:n]
    )
    base = get_preset("E5_router")
    assert retriever.prepare_queries("질문", base) == ["질문"]
    term = replace(base, use_term_expansion=True)
    assert retriever.prepare_queries("해외 회사인데 뭐 해야 해?", term) == [
        "해외 회사인데 뭐 해야 해? 국내대리인"
    ]
    mq = replace(base, use_multi_query=True, n_queries=2)
    assert retriever.prepare_queries("질문", mq) == ["질문", "국내대리인 지정 의무"]


def test_multi_query_fuses_rankings(monkeypatch) -> None:
    rankings = {
        "q0": [CANDIDATES[0], CANDIDATES[1]],
        "q1": [CANDIDATES[2], CANDIDATES[1]],
    }
    monkeypatch.setattr(
        retriever,
        "_dense",
        lambda q, cfg, limit, stage="dense": [
            replace(c, stage_scores={stage: c.score}) for c in rankings[q]
        ],
    )
    cfg = replace(get_preset("E2_header"), top_k=3)
    trace = retrieve_with_trace("질문", cfg, queries=["q0", "q1"])
    assert trace.queries == ["q0", "q1"]
    assert trace.results[0].chunk_id == "a12"  # 두 질의 모두에 등장
    assert {"dense_rank", "dense@1_rank"} <= trace.results[0].stage_scores.keys()


def test_small_to_big_merges_same_article() -> None:
    ranked = [
        store_chunk("law:a6-p2"),
        store_chunk("law:a3"),
        store_chunk("law:a6-p3"),
    ]
    out = retriever._small_to_big(ranked)
    assert [c.chunk_id for c in out] == ["law:a6-p2", "law:a3"]
    assert out[0].text == out[0].parent_text
    assert out[0].stage_scores["merged"] == 2
    assert out[1].text != "" and "merged" not in out[1].stage_scores


def test_ref_expansion_adds_same_source_refs() -> None:
    cfg = replace(get_preset("E2_header"), use_ref_expansion=True, max_expansion=2)
    results = [store_chunk("law:a43", 0.9), store_chunk("law:a31", 0.8)]
    out = retriever._expand("과태료", results, cfg, "ref")
    added = out[len(results) :]
    # law:a43 refs = a31(이미 있음), a36, a40 → 최대 2개
    assert [c.article_key for c in added] == ["law:a36", "law:a40"]
    assert all(c.added_by == "ref" and c.via == "law:a43" for c in added)
    assert all(c.score < 0.8 for c in added)


def test_delegation_expansion_follows_chain_and_sources() -> None:
    cfg = replace(
        get_preset("E2_header"),
        sources=("law", "decree", "annex"),
        use_delegation_expansion=True,
    )
    out = retriever._expand(
        "국내대리인 미지정 과태료 금액", [store_chunk("law:a43")], cfg, "delegation"
    )
    assert [(c.article_key, c.via) for c in out[1:]] == [
        ("decree:a32", "law:a43"),
        ("annex:2", "decree:a32"),
    ]
    assert "국내대리인" in out[2].text  # 별표 행 중 질문과 맞는 행을 대표로

    law_only = replace(cfg, sources=("law",))
    out = retriever._expand("과태료", [store_chunk("law:a43")], law_only, "delegation")
    assert len(out) == 1


def test_priority_boost_prefers_law_over_term() -> None:
    term = store_chunk("term:인공지능")
    law = store_chunk("law:a2-i1")
    cfg = replace(get_preset("E2_header"), priority_boost=0.002)
    assert [c.chunk_id for c in retriever._priority_boost([term, law], cfg)] == [
        "law:a2-i1",
        "term:인공지능",
    ]
    no_boost = replace(cfg, priority_boost=0.0)
    assert retriever._priority_boost([term, law], no_boost)[0] is term
