"""eval/evaluate.py 지표·gold 매칭 단위테스트 (Qdrant·임베딩 없이)."""

import pytest

from eval.evaluate import aggregate, gold_matcher, score_question, validate_golden
from rag.retriever import RetrievedChunk


def chunk(article_key: str, source_type: str = "law", **payload) -> RetrievedChunk:
    payload = {"chunk_type": "article", **payload}
    return RetrievedChunk(
        chunk_id=f"{article_key}-x",
        source_type=source_type,
        citation="",
        doc_title=payload.pop("doc_title", ""),
        text="",
        parent_text="",
        article_key=article_key,
        score=1.0,
        payload=payload,
    )


@pytest.mark.parametrize(
    ("gold", "hit", "miss"),
    [
        ("law:제31조", chunk("law:a31"), chunk("law:a3")),
        ("제31조", chunk("law:a31"), chunk("decree:a31", "decree")),
        (
            "decree:제22조의2",
            chunk("decree:a22_2", "decree"),
            chunk("decree:a22", "decree"),
        ),
        ("annex:별표2", chunk("annex:2", "annex"), chunk("annex:1", "annex")),
        (
            "term:고영향 인공지능",
            chunk("term:고영향 인공지능", "term"),
            chunk("term:인공지능", "term"),
        ),
        ("law:부칙", chunk("law:add1", chunk_type="addendum"), chunk("law:a1")),
        (
            "admrul:확인 고시",
            chunk("admrul:1-a3", "admrul", doc_title="확인 고시"),
            chunk("admrul:2-a3", "admrul", doc_title="다른 고시"),
        ),
        # naive 청크는 걸친 조(covers) 중 하나만 맞아도 적중
        (
            "law:제31조",
            chunk("law:a30", covers=["law:a30", "law:a31"]),
            chunk("law:a30", covers=["law:a30"]),
        ),
    ],
)
def test_gold_matcher(gold: str, hit: RetrievedChunk, miss: RetrievedChunk) -> None:
    match = gold_matcher(gold)
    assert match(hit)
    assert not match(miss)


def test_score_and_aggregate() -> None:
    q1 = {
        "id": "q1",
        "type": "cross_ref",
        "question": "",
        "gold": ["law:제43조", "law:제31조"],
        "should_refuse": False,
    }
    q2 = {
        "id": "q2",
        "type": "definition",
        "question": "",
        "gold": ["law:제2조"],
        "should_refuse": False,
    }
    q3 = {
        "id": "q3",
        "type": "out_of_scope",
        "question": "",
        "gold": [],
        "should_refuse": True,
    }
    r1 = score_question(
        q1,
        [
            chunk("law:a5"),
            chunk("law:a43"),
            chunk("law:a6"),
            chunk("law:a7"),
            chunk("law:a31"),
        ],
        10,
    )
    r2 = score_question(q2, [chunk("law:a9")] * 5, 20)
    r3 = score_question(q3, [chunk("law:a1")], 30)
    assert r1.gold_ranks == {"law:제43조": 2, "law:제31조": 5}
    assert r1.first_hit == 2 and r2.first_hit is None
    agg = aggregate([r1, r2, r3])
    assert agg["n"] == 2
    assert agg["hit@1"] == 0.0 and agg["hit@3"] == 0.5
    assert agg["mrr"] == 0.25
    assert agg["full_recall@5"] == 1.0 and agg["n_multi"] == 1


def test_validate_golden() -> None:
    ok = {
        "id": "q1",
        "type": "definition",
        "question": "?",
        "gold": ["law:제2조"],
        "reference_answer": "",
        "should_refuse": False,
        "split": "dev",
    }
    assert validate_golden([ok]) == []
    bad = {**ok, "id": "q2", "gold": ["법 제2조"]}
    refuse_with_gold = {**ok, "id": "q3", "type": "out_of_scope", "should_refuse": True}
    errors = validate_golden([ok, bad, refuse_with_gold, ok])
    assert len(errors) == 3
