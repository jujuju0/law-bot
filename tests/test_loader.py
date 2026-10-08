"""rag/loader.py 변환 함수 단위테스트 — fixtures만 사용."""

import json
from pathlib import Path

import pytest

from common.law_api import LawApiError
from rag.loader import annex_documents, law_document, term_document

FIXTURES = Path(__file__).parent / "fixtures"
LAW_TITLE = "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_law_document_meta_units_and_addenda() -> None:
    doc = law_document(load("law_articles.json")["법령"], "law", "282791")
    assert doc.title == LAW_TITLE
    assert doc.meta["ministry"] == "과학기술정보통신부"
    assert doc.units[0].is_heading
    assert doc.addenda[0]["promulgation_no"] == "20676"
    assert doc.addenda[0]["text"].startswith("부칙 <제20676호")


def test_annex_documents_pick_annex_only_and_skip_forms() -> None:
    body = load("decree_annex.json")["법령"]
    body["기본정보"] = {"법령명_한글": f"{LAW_TITLE} 시행령"}
    targets = [{"law": "decree", "number": "1"}, {"law": "decree", "number": "2"}]
    docs = annex_documents(body, "288781", targets)
    assert [d.doc_id for d in docs] == ["288781:1", "288781:2"]
    assert docs[1].title.startswith("과태료의 부과기준")
    assert "개별기준" in docs[1].units[0]["text"]
    with pytest.raises(LawApiError):
        annex_documents(body, "288781", [{"law": "decree", "number": "9"}])


def test_term_document_keeps_only_allowed_sources() -> None:
    body = load("term_high_impact.json")["LsTrmService"]
    doc = term_document("고영향 인공지능", body, [LAW_TITLE])
    assert doc is not None
    assert len(doc.units) == 1
    assert doc.units[0]["source"].startswith(LAW_TITLE)
    assert term_document("고영향 인공지능", body, ["없는 법령"]) is None
