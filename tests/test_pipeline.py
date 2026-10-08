"""rag/grounding.py · rag/prompts.py · rag/pipeline.py 단위테스트 (LLM·Qdrant 없이, 실제 청크 payload 사용)."""

import pytest

from rag import pipeline
from rag.chunk_store import get_chunk_store
from rag.config import get_preset
from rag.grounding import check_answer, evidence_amounts, match_citation
from rag.prompts import REFUSAL, build_messages, format_chunk, select_context
from rag.retriever import RetrievalTrace, RetrievedChunk


def store_chunk(
    chunk_id: str, score: float = 0.5, added_by: str = "search"
) -> RetrievedChunk:
    c = RetrievedChunk.from_payload(get_chunk_store().by_id[chunk_id], score, "dense")
    c.added_by = added_by
    return c


LAW43 = store_chunk("law:a43")
ANNEX2_R2 = store_chunk("annex:2-r2", added_by="delegation")


# ---------------------------------------------------------------------------
# 인용 대조
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("cited", "available", "ok"),
    [
        ("법 제31조 제2항", ["법 제31조 제2항"], True),
        ("법 제31조", ["법 제31조 제2항"], True),  # 조 단위 인용 ↔ 항 근거
        ("법 제31조 제2항", ["법 제31조"], True),  # 항 인용 ↔ 조 전체 근거
        ("법 제3조", ["법 제31조"], False),
        ("법 제31조", ["법 제3조"], False),
        ("영 제31조", ["법 제31조"], False),
        ("영 별표 2", ["영 별표 2"], True),
        ("영 별표 1", ["영 별표 2"], False),
        ("영 별표 1", ["영 별표 2", "영 별표 10"], False),
    ],
)
def test_match_citation(cited: str, available: list[str], ok: bool) -> None:
    assert bool(match_citation(cited, available)) is ok


def test_invalid_citation_removed_and_reported() -> None:
    r = check_answer(
        "과태료 대상입니다 [법 제43조 제1항, 법 제99조]. 근거 없음 [영 제1조].",
        ["법 제43조"],
        [LAW43.text],
    )
    assert r.answer == "과태료 대상입니다 [법 제43조 제1항]. 근거 없음."
    assert r.cited == ["법 제43조 제1항"]
    assert r.invalid_citations == ["법 제99조", "영 제1조"]
    assert r.grounded


# ---------------------------------------------------------------------------
# 숫자 근거 (별표 표는 "(단위: 만원)" 맨 숫자)
# ---------------------------------------------------------------------------
def test_evidence_amounts_reads_table_unit() -> None:
    amounts = evidence_amounts(ANNEX2_R2.text)
    assert 20_000_000 in amounts  # "2,000" × 만원
    assert 30_000_000 in evidence_amounts(LAW43.text)  # "3천만원"


@pytest.mark.parametrize(
    ("answer", "unsupported"),
    [
        ("국내대리인 미지정 과태료는 2,000만원입니다 [영 별표 2].", []),
        ("2000 만원 [영 별표 2], 상한 3천만원 [법 제43조].", []),
        ("상한은 3,000만원입니다 [법 제43조].", []),  # 3천만원과 같은 금액
        ("1차 위반 시 500만원입니다 [영 별표 2].", ["500만원"]),  # 이 행에는 없음
        ("4천만원 이하 [법 제43조].", ["4천만원"]),
        ("30일 이내에 [법 제43조].", ["30일"]),
    ],
)
def test_unsupported_numbers(answer: str, unsupported: list[str]) -> None:
    r = check_answer(answer, ["법 제43조", "영 별표 2"], [LAW43.text, ANNEX2_R2.text])
    assert r.unsupported_numbers == unsupported
    assert r.grounded is (not unsupported)


def test_refusal_is_grounded_without_citations() -> None:
    r = check_answer(REFUSAL, ["법 제43조"], [LAW43.text])
    assert r.refused and r.grounded and r.cited == []
    assert not check_answer(
        "근거 없는 답변입니다.", ["법 제43조"], [LAW43.text]
    ).grounded


# ---------------------------------------------------------------------------
# 프롬프트·컨텍스트 예산
# ---------------------------------------------------------------------------
def test_build_messages_contains_citations_and_kinds() -> None:
    messages = build_messages("질문?", [LAW43, ANNEX2_R2])
    assert [role for role, _ in messages] == ["system", "user"]
    user = messages[1][1]
    assert 'citation="법 제43조" 종류="법률"' in user
    assert 'citation="영 별표 2" 종류="시행령 별표"' in user
    assert user.endswith("질문: 질문?")
    assert REFUSAL in messages[0][1]


def test_select_context_drops_expansion_first() -> None:
    chunks = [store_chunk("law:a31"), store_chunk("law:a36"), ANNEX2_R2]

    def counter(text: str) -> int:
        return 100

    assert select_context(chunks, budget=300, counter=counter) == chunks
    kept = select_context(chunks, budget=200, counter=counter)
    assert [c.chunk_id for c in kept] == ["law:a31", "law:a36"]  # 확장 청크부터 제거
    kept = select_context(chunks, budget=100, counter=counter)
    assert [c.chunk_id for c in kept] == ["law:a31"]
    assert len(select_context(chunks, budget=0, counter=counter)) == 1  # 최소 1개 유지
    assert format_chunk(LAW43).startswith('<근거 citation="법 제43조"')


# ---------------------------------------------------------------------------
# pipeline.answer
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_retrieval(monkeypatch):
    def set_results(results: list[RetrievedChunk]) -> None:
        monkeypatch.setattr(
            pipeline,
            "retrieve_with_trace",
            lambda q, cfg: RetrievalTrace(
                results=results, candidates=results, queries=[q]
            ),
        )

    return set_results


def test_answer_annex_question(fake_retrieval) -> None:
    fake_retrieval([LAW43, ANNEX2_R2])
    seen = []

    def chat(messages):
        seen.append(messages)
        return (
            "국내대리인을 지정하지 않으면 과태료가 부과됩니다 [법 제43조 제1항]. "
            "금액은 위반 횟수와 관계없이 2,000만원입니다 [영 별표 2].\n근거:\n[법 제43조]\n[영 별표 2]"
        )

    res = pipeline.answer(
        "국내대리인 미지정 과태료?", get_preset("E9_delegation"), debug=True, chat=chat
    )
    assert len(seen) == 1
    assert res.grounded and res.warnings == []
    assert res.data_snapshot == "2026-10-08"
    assert "AI가 생성한 답변" in res.notice
    assert [(s.citation, s.cited, s.added_by) for s in res.sources] == [
        ("법 제43조", True, "search"),
        ("영 별표 2", True, "delegation"),
    ]
    assert res.sources[0].article == "제43조"
    assert res.debug and res.debug["preset"] == "E9_delegation"
    assert res.debug["candidates"][1]["added_by"] == "delegation"


def test_answer_flags_hallucinated_amount(fake_retrieval) -> None:
    fake_retrieval([LAW43])
    res = pipeline.answer(
        "과태료 얼마?",
        get_preset("E5_router"),
        chat=lambda m: "1차 위반은 500만원입니다 [법 제43조] [영 별표 2].",
    )
    assert not res.grounded
    assert "근거에 없는 인용 제거: [영 별표 2]" in res.warnings
    assert "근거 텍스트에 없는 숫자: 500만원" in res.warnings
    assert "[영 별표 2]" not in res.answer


def test_answer_without_results_refuses_without_llm(fake_retrieval) -> None:
    fake_retrieval([])

    def chat(messages):
        raise AssertionError("LLM을 부르면 안 됨")

    res = pipeline.answer("내일 날씨?", get_preset("E5_router"), chat=chat)
    assert res.answer == REFUSAL and res.grounded and res.sources == []


def test_empty_bullets_removed_after_invalid_citation() -> None:
    answer = "답변입니다. [법 제43조]\n\n근거:\n- [영 제99조]\n- [법 제43조]"
    r = check_answer(answer, ["법 제43조"], [LAW43.text])
    assert "- \n" not in r.answer and not any(
        line.strip() == "-" for line in r.answer.splitlines()
    )
    assert "- [법 제43조]" in r.answer


def test_abbreviated_citation_inherits_article() -> None:
    from rag.grounding import split_citation

    assert split_citation("법 제32조 제1항 제2호, 제2항") == [
        "법 제32조 제1항 제2호",
        "법 제32조 제2항",
    ]
    assert split_citation("법 제31조, 제43조") == ["법 제31조", "법 제43조"]


def test_sibling_clause_citation_allowed_for_expanded_chunk() -> None:
    from rag.grounding import evidence_citations

    text = "① 가 ② 나 ③ 다"
    assert "영 제25조" in evidence_citations("영 제25조 제4항", text)
    assert evidence_citations("영 제25조 제4항", "④ 라") == ["영 제25조 제4항"]
    r = check_answer(
        "서류를 냅니다. [영 제25조 제1항]",
        evidence_citations("영 제25조 제4항", text),
        [text],
    )
    assert not r.invalid_citations


def test_refusal_drops_citations() -> None:
    r = check_answer(f"{REFUSAL}\n\n근거:\n- [법 제43조]", ["법 제43조"], [LAW43.text])
    assert r.refused and r.answer == REFUSAL and r.cited == []


def test_large_units_checked() -> None:
    r = check_answer(
        "매출 1조원, 100만명 이상. [법 제43조]", ["법 제43조"], [LAW43.text]
    )
    assert "1조원" in r.unsupported_numbers and "100만명" in r.unsupported_numbers
