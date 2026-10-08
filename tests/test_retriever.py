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
    monkeypatch.setattr(retriever, "_dense", lambda q, cfg, limit: list(CANDIDATES))
    monkeypatch.setattr(retriever, "_bm25", lambda q, cfg, limit: list(CANDIDATES))
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
