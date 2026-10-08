"""rag/chunker.py·annex_parser·legal_text 테스트 — 기대값은 /law-structure 스킬, DESIGN §3.2."""

import json
from pathlib import Path

import pytest

from rag.annex_parser import parse_annex
from rag.chunker import Chunk, chunk_documents, naive_chunks
from rag.legal_text import (
    DelegationSource,
    find_delegation_sources,
    find_refs,
    join_wrapped,
)
from rag.loader import admrul_document, annex_documents, law_document

FIXTURES = Path(__file__).parent / "fixtures"
ANNEX_TARGETS = [{"law": "decree", "number": "1"}, {"law": "decree", "number": "2"}]


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def chunks() -> dict[str, Chunk]:
    law = load("law_282791.json")["법령"]
    decree = load("decree_288781.json")["법령"]
    docs = [
        law_document(law, "law", "282791"),
        law_document(decree, "decree", "288781"),
        *annex_documents(decree, "288781", ANNEX_TARGETS),
        admrul_document(
            load("admrul_2100000283290.json")["AdmRulService"],
            "2100000283290",
            short="확인 절차",
        ),
    ]
    result, _graph = chunk_documents(docs)
    return {c.chunk_id: c for c in result}


def of(chunks: dict[str, Chunk], article_key: str) -> list[Chunk]:
    return [c for c in chunks.values() if c.article_key == article_key]


# -- 법률 구조 -------------------------------------------------------------------
def test_law_article_and_chapter_counts(chunks: dict[str, Chunk]) -> None:
    law = [
        c
        for c in chunks.values()
        if c.source_type == "law" and c.chunk_type != "addendum"
    ]
    # 2026-07-21 시행본: 제1~43조 + 제17조의2·22조의2·22조의3
    assert len({c.article_key for c in law}) == 46
    assert len({c.chapter for c in law}) == 6
    assert "law:a22_2-p1" in chunks or "law:a22_2" in chunks


def test_definition_article_is_item_level(chunks: dict[str, Chunk]) -> None:
    items = of(chunks, "law:a2")
    assert [c.chunk_id for c in items] == [f"law:a2-i{i}" for i in range(1, 13)]
    i4 = chunks["law:a2-i4"]
    assert i4.citation == "법 제2조 제4호"
    assert i4.text.count("\n") == 12  # 도입 문장 + 호 + 목 가~카(11)
    assert chunks["law:a2-i7"].text.count("\n") == 3
    assert i4.embed_text.startswith(
        "[법률 > 제1장 총칙] 제2조(정의) 이 법에서 사용하는 용어의 뜻은"
    )
    assert '4. "고영향 인공지능"이란' in i4.embed_text and "<개정" not in i4.embed_text


def test_short_article_single_chunk_and_citation(chunks: dict[str, Chunk]) -> None:
    a31 = chunks["law:a31"]
    assert a31.chunk_type == "article"
    assert a31.citation == "법 제31조"
    assert a31.text.count("\n") == 4  # 머리 + 항 4개
    assert a31.chapter == "제4장 인공지능윤리 및 신뢰성 확보"


def test_long_article_split_by_paragraph(chunks: dict[str, Chunk]) -> None:
    paras = of(chunks, "law:a6")
    assert len(paras) > 1 and all(c.chunk_type == "paragraph" for c in paras)
    p2 = chunks["law:a6-p2"]
    assert p2.citation == "법 제6조 제2항"
    assert p2.paragraph == "②"
    assert p2.parent_text.startswith("제6조(")


def test_amendment_marks_extracted_and_removed_from_embed(
    chunks: dict[str, Chunk],
) -> None:
    amended = [c for c in chunks.values() if c.amended]
    assert len(amended) >= 10
    c = amended[0]
    assert c.amended[0] in c.text
    assert "<개정" not in c.embed_text and "<신설" not in c.embed_text


def test_internal_refs_exclude_other_laws(chunks: dict[str, Chunk]) -> None:
    assert {"law:a31", "law:a36", "law:a40"} <= set(chunks["law:a43"].refs)
    # 「에너지법」 제2조제1호 등 다른 법률 참조는 refs에 들어가지 않는다
    assert chunks["law:a2-i4"].refs == []


@pytest.mark.parametrize("key", ["law:a31", "law:a33", "law:a35", "law:a36"])
def test_delegated_articles(chunks: dict[str, Chunk], key: str) -> None:
    assert any(c.delegated for c in of(chunks, key))


def test_addenda_chunks(chunks: dict[str, Chunk]) -> None:
    add = chunks["law:add1"]
    assert add.chunk_type == "addendum"
    assert add.citation == "법 부칙 <제20676호>"
    assert add.refs == []


# -- 위임 그래프 -----------------------------------------------------------------
def test_law33_delegates_to_decree(chunks: dict[str, Chunk]) -> None:
    targets = {t for c in of(chunks, "law:a33") for t in c.delegates_to}
    assert "decree:a25" in targets
    assert "law:a33" in {k for c in of(chunks, "decree:a25") for k in c.delegated_from}


def test_penalty_chain_law43_decree32_annex2(chunks: dict[str, Chunk]) -> None:
    assert "decree:a32" in {t for c in of(chunks, "law:a43") for t in c.delegates_to}
    assert "annex:2" in chunks["decree:a32"].delegates_to
    assert all(c.delegated_from == ["decree:a32"] for c in of(chunks, "annex:2"))
    assert all(c.delegated_from == ["decree:a27"] for c in of(chunks, "annex:1"))


def test_admrul_delegation_basis_from_purpose_article(chunks: dict[str, Chunk]) -> None:
    a1 = chunks["admrul:2100000283290-a1"]
    assert a1.citation == "고시 확인 절차 제1조"
    # 제1조(목적)의 근거(법 제16조, 영 제15조)를 고시 전체 조가 공유
    assert set(a1.delegated_from) == {"law:a16", "decree:a15"}
    assert chunks["admrul:2100000283290-a5"].delegated_from == a1.delegated_from
    # 제2조의 "법 제26조제1항에 따른 협회"는 위임 근거가 아니다
    assert "law:a26" not in chunks["admrul:2100000283290-a2"].delegated_from
    assert "admrul:2100000283290-a5" in {
        t for c in of(chunks, "decree:a15") for t in c.delegates_to
    }


# -- 별표 -------------------------------------------------------------------------
ANNEX2_ROWS = [  # DESIGN §3.2 고정값 = §5.2 숫자 검증 기준값
    (
        "법 제31조제1항을 위반하여 고지를 이행하지 않은 경우",
        "법 제43조제1항제1호",
        "500",
        "1,000",
        "1,500",
    ),
    (
        "법 제36조제1항을 위반하여 국내대리인을 지정하지 않은 경우",
        "법 제43조제1항제2호",
        "2,000",
        "2,000",
        "2,000",
    ),
    (
        "법 제40조제3항에 따른 중지명령이나 시정명령을 이행하지 않은 경우",
        "법 제43조제1항제3호",
        "1,000",
        "2,000",
        "3,000",
    ),
]


@pytest.fixture(scope="module")
def annexes() -> dict[int, str]:
    units = load("decree_annex.json")["법령"]["별표"]["별표단위"]
    from common.law_api import as_text

    return {
        int(u["별표번호"]): as_text(u["별표내용"])
        for u in units
        if u["별표구분"] == "별표"
    }


def test_annex2_table_rows_match_source(annexes: dict[int, str]) -> None:
    parsed = parse_annex(annexes[2])
    table = next(s.table for s in parsed.sections if s.table)
    assert table.unit == "만원"
    assert table.headers[:2] == ["위반행위", "근거 법조문"]
    assert table.headers[2:] == [
        f"과태료 금액 {x} 위반" for x in ("1차", "2차", "3차 이상")
    ]
    rows = [(r[0].split(". ", 1)[1], *r[1:]) for r in table.rows]
    assert rows == ANNEX2_ROWS
    assert any("깨진 문자" in w for w in parsed.warnings)


def test_annex_chunks(chunks: dict[str, Chunk]) -> None:
    assert [c.chunk_id for c in of(chunks, "annex:2")] == [
        "annex:2-note",
        "annex:2-r1",
        "annex:2-r2",
        "annex:2-r3",
    ]
    r1 = chunks["annex:2-r1"]
    assert r1.citation == "영 별표 2"
    assert "(단위: 만원)" in r1.text and "| 500 | 1,000 | 1,500" in r1.text
    assert {"law:a31", "law:a43"} <= set(r1.refs)
    a = chunks["annex:1-1-가"]
    assert a.text.startswith("1. 인공지능사업자가")  # 상위 번호 도입 문장
    assert "\n가. 법 제2조제4호라목의" in a.text
    assert "annex:1-7" in chunks  # 목 없는 번호
    # 별표 1의 "같은 법 제8조"는 다른 법률이므로 refs에 law:a8이 없다
    assert "law:a8" not in a.refs


def test_annex1_header_meta(annexes: dict[int, str]) -> None:
    parsed = parse_annex(annexes[1])
    assert parsed.number == 1
    assert parsed.title == "이행조치 인정 기준 및 절차(제27조제5항 관련)"
    assert parsed.effective_note and parsed.effective_note.startswith("[시행일:")
    assert [s.number for s in parsed.sections] == [str(i) for i in range(1, 8)]


# -- naive (E0) -------------------------------------------------------------------
def test_naive_chunks_fixed_size_and_covers() -> None:
    doc = law_document(load("law_282791.json")["법령"], "law", "282791")
    naive = naive_chunks(doc, size=500)
    assert all(len(c.text) == 500 for c in naive[:-1])
    assert naive[0].chunk_id == "law:naive-001" and naive[0].chunk_type == "naive"
    covered = {k for c in naive for k in c.covers}
    assert len(covered) == 46
    assert all(c.article_key == c.covers[0] for c in naive)


# -- 텍스트 유틸 -------------------------------------------------------------------
@pytest.mark.parametrize(
    ("prev", "nxt", "expected"),
    [
        ("법 제31조제1항을 위반", "하여 고지를", "법 제31조제1항을 위반하여 고지를"),
        (
            "다. 법 제40조제3항에 따른",
            "중지명령이나",
            "다. 법 제40조제3항에 따른 중지명령이나",
        ),
        ("같은 법 제4", "3조에 따른", "같은 법 제43조에 따른"),
        (
            "「신용정보의 이용 및 보호에 관",
            "한 법률」",
            "「신용정보의 이용 및 보호에 관한 법률」",
        ),
        ("관한 법률」", "제8조에 따른", "관한 법률」 제8조에 따른"),
    ],
)
def test_join_wrapped(prev: str, nxt: str, expected: str) -> None:
    assert join_wrapped(prev, nxt) == expected


def test_find_refs_decree_and_delegation_sources() -> None:
    text = "① 법 제33조제4항에 따라 확인을 요청하려는 자는 제26조 및 별표 1에 따른 서류를 「행정절차법」 제2조에 따라 제출한다."
    assert find_refs(text, "decree", self_ref="decree:a25") == [
        "law:a33",
        "decree:a26",
        "annex:1",
    ]
    assert find_delegation_sources(text) == [DelegationSource("law:a33", 4)]
    assert find_delegation_sources(
        '법 제16조제3항 본문에서 "대통령령으로 정하는 기준"'
    ) == [DelegationSource("law:a16", 3)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # 정의어 별칭 「…」(이하 "법"이라 한다) + 따옴표 안 긴 문구
        (
            (
                '「인공지능 발전과 신뢰 기반 조성 등에 관한 기본법」(이하 "법"이라 한다) 제3조제5항에서 '
                '"장애인ㆍ고령자 등 대통령령으로 정하는 취약계층"이란'
            ),
            ["law:a3"],
        ),
        # "에 따른 X": 항 첫머리·주어 뒤는 위임, 호 첫머리·문장 중간은 정의 인용
        (
            "제32조(과태료의 부과기준) 법 제43조제1항에 따른 과태료의 부과기준은 별표 2와 같다.",
            ["law:a43"],
        ),
        (
            "과학기술정보통신부장관은 법 제27조제1항에 따른 윤리원칙을 공표한다.",
            ["law:a27"],
        ),
        (
            "4. 법 제43조제1항제3호에 따른 과태료를 부과 받은 사실이 있는 인공지능사업자",
            [],
        ),
        (
            "받으려는 중소기업등(법 제16조제2항제3호에 따른 중소기업등을 말한다)에 대하여",
            [],
        ),
    ],
)
def test_delegation_source_position_rules(text: str, expected: list[str]) -> None:
    assert [s.key for s in find_delegation_sources(text)] == expected


def test_other_law_article_chain_is_masked() -> None:
    text = "「형법」 제129조부터 제132조까지의 규정을 적용할 때에는 제39조에 따른"
    assert find_refs(text, "law") == ["law:a39"]


# -- 점검 에이전트 지적 회귀 --------------------------------------------------------
def test_item_chunks_keep_intro_sentence(chunks: dict[str, Chunk]) -> None:
    i1 = chunks["decree:a2-i1"]
    assert '법 제4조제2항에서 "대통령령으로 정하는 인공지능"이란' in i1.text
    assert i1.delegated_from == ["law:a4"]
    assert "decree:a2" in {t for c in of(chunks, "law:a4") for t in c.delegates_to}


def test_definition_citations_are_not_delegations(chunks: dict[str, Chunk]) -> None:
    assert of(chunks, "decree:a1_2")[0].delegated_from == ["law:a3"]
    assert all(c.delegates_to == [] for c in of(chunks, "law:a2"))
    assert "decree:a29" not in {
        t for c in of(chunks, "law:a43") for t in c.delegates_to
    }
    law = [c for c in chunks.values() if c.source_type == "law"]
    assert [c.chunk_id for c in law if c.delegates_to and not c.delegated] == []


def test_addendum_delegation(chunks: dict[str, Chunk]) -> None:
    assert chunks["decree:add1"].delegated_from == ["law:add1"]
    assert chunks["law:add1"].delegates_to == ["decree:add1"]
