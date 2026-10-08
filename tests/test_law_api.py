"""common/law_api.py 단위테스트 — 저장된 fixtures + respx, 네트워크 없이."""

import json
from pathlib import Path

import httpx
import pytest
import respx

from common.law_api import (
    CacheKey,
    LawApiAuthError,
    LawApiClient,
    LawApiError,
    article_key,
    as_list,
    as_text,
    normalize_article,
    redact_oc,
    strip_oc_param,
)

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "http://law.test/DRF"
FAKE_OC = "fakeoc0123"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def law_units() -> list[dict]:
    return load("law_articles.json")["법령"]["조문"]["조문단위"]


def find(
    units: list[dict], no: str, sub: str | None = None, heading: bool = False
) -> dict:
    kind = "전문" if heading else "조문"
    return next(
        u
        for u in units
        if u["조문번호"] == no
        and u.get("조문가지번호") == sub
        and u["조문여부"] == kind
    )


@pytest.fixture
def client(tmp_path: Path) -> LawApiClient:
    return LawApiClient(oc=FAKE_OC, base_url=BASE, raw_dir=tmp_path, min_interval=0)


# -- 정규화 유틸 ----------------------------------------------------------------
def test_as_list_normalizes_single_and_many() -> None:
    assert as_list(None) == []
    assert as_list({"a": 1}) == [{"a": 1}]
    assert as_list([1, 2]) == [1, 2]


def test_as_text_flattens_nested_lists() -> None:
    assert (
        as_text([["부칙 <제1호>", " 제1조(시행일) ... "], []])
        == "부칙 <제1호>\n제1조(시행일) ..."
    )
    assert as_text({"content": " 과학기술정보통신부 "}) == "과학기술정보통신부"


def test_article_key() -> None:
    assert article_key("31") == "31"
    assert article_key("22", "2") == "22_2"
    assert article_key("0031", "00") == "31"


# -- 조문 정규화 ----------------------------------------------------------------
def test_dict_paragraph_without_number_becomes_direct_items(
    law_units: list[dict],
) -> None:
    a2 = normalize_article(find(law_units, "2"))
    assert a2.paragraphs == []
    assert len(a2.items) >= 4
    assert a2.items[0].text.startswith('1. "인공지능"이란')
    item4 = a2.items[3]
    assert item4.no == "4."
    assert [m.no for m in item4.children[:2]] == ["가.", "나."]


def test_dict_paragraph_article_29(law_units: list[dict]) -> None:
    a29 = normalize_article(find(law_units, "29"))
    assert a29.paragraphs == [] and a29.items
    assert a29.content.startswith("제29조(")  # 도입 문장은 조문내용에


def test_paragraph_list_article_31(law_units: list[dict]) -> None:
    a31 = normalize_article(find(law_units, "31"))
    assert [p.no for p in a31.paragraphs] == ["①", "②", "③", "④"]
    assert a31.content == "제31조(인공지능 투명성 확보 의무)"
    assert a31.title == "인공지능 투명성 확보 의무"
    assert a31.items == []


def test_article_without_paragraph(law_units: list[dict]) -> None:
    a1 = normalize_article(find(law_units, "1"))
    assert a1.paragraphs == [] and a1.items == []
    assert a1.content.startswith("제1조(목적) 이 법은")


def test_heading_row_and_branch_article(law_units: list[dict]) -> None:
    h = normalize_article(find(law_units, "1", heading=True))
    assert h.is_heading and h.content == "제1장 총칙"
    a = normalize_article(find(law_units, "22", "2"))
    assert (a.key, a.no, a.sub) == ("22_2", 22, 2)


# -- OC 처리 ---------------------------------------------------------------------
def test_redact_and_strip_oc() -> None:
    url = f"{BASE}/lawService.do?OC={FAKE_OC}&target=law&MST=1"
    assert FAKE_OC not in redact_oc(url, FAKE_OC)
    assert strip_oc_param(url) == f"{BASE}/lawService.do?target=law&MST=1"


# -- 클라이언트 -------------------------------------------------------------------
@respx.mock
def test_auth_failure_with_200_json_raises(client: LawApiClient) -> None:
    respx.get(f"{BASE}/lawService.do").mock(
        return_value=httpx.Response(200, json=load("auth_fail.json"))
    )
    with pytest.raises(LawApiAuthError) as e:
        client.service("law", MST="1")
    assert "검증에 실패" in (e.value.result or "")


@respx.mock
def test_search_missing_root_key_raises(client: LawApiClient) -> None:
    respx.get(f"{BASE}/lawSearch.do").mock(
        return_value=httpx.Response(200, json=load("auth_fail.json"))
    )
    with pytest.raises(LawApiAuthError):
        client.search("law", "인공지능")


@respx.mock
def test_non_json_response_raises_auth_error(client: LawApiClient) -> None:
    respx.get(f"{BASE}/lawService.do").mock(
        return_value=httpx.Response(200, text="<html>error</html>")
    )
    with pytest.raises(LawApiAuthError):
        client.service("law", MST="1")


@respx.mock
def test_not_found_message_is_not_auth_error(client: LawApiClient) -> None:
    respx.get(f"{BASE}/lawService.do").mock(
        return_value=httpx.Response(200, json={"Law": "일치하는 법령용어가 없습니다."})
    )
    with pytest.raises(LawApiError) as e:
        client.service("lstrm", query="없는 용어")
    assert not isinstance(e.value, LawApiAuthError)


@respx.mock
def test_search_returns_items_and_handles_zero_results(client: LawApiClient) -> None:
    route = respx.get(f"{BASE}/lawSearch.do")
    route.side_effect = [
        httpx.Response(200, json=load("search_law.json")),
        httpx.Response(200, json={"Expc": {"totalCnt": "0", "target": "expc"}}),
    ]
    items = client.search("law", "인공지능")
    assert {i["법령일련번호"] for i in items} >= {"282791"}
    assert client.search("expc", "인공지능") == []


@respx.mock
def test_saved_cache_and_manifest_have_no_oc(
    client: LawApiClient, tmp_path: Path
) -> None:
    body = load("search_law.json")
    text = json.dumps(body, ensure_ascii=False).replace("OC=***", f"OC={FAKE_OC}")
    assert FAKE_OC in text
    respx.get(f"{BASE}/lawSearch.do").mock(
        return_value=httpx.Response(
            200, text=text, headers={"content-type": "application/json"}
        )
    )
    client.search("law", "인공지능", cache=CacheKey("law", "_search_law"))

    saved = (tmp_path / "law" / "_search_law.json").read_text(encoding="utf-8")
    manifest = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert FAKE_OC not in saved
    assert FAKE_OC not in manifest
    assert "OC=***" in saved
    entry = json.loads(manifest)["law/_search_law.json"]
    assert "OC" not in entry["url_without_oc"]


@respx.mock
def test_cache_hit_skips_network(client: LawApiClient, tmp_path: Path) -> None:
    (tmp_path / "law").mkdir()
    (tmp_path / "law" / "1.json").write_text(
        json.dumps(load("law_articles.json"), ensure_ascii=False), encoding="utf-8"
    )
    route = respx.get(f"{BASE}/lawService.do")
    data = client.service("law", cache=CacheKey("law", "1"), MST="1")
    assert "법령" in data
    assert not route.called


@respx.mock
def test_server_error_is_retried(
    client: LawApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("time.sleep", lambda _s: None)
    route = respx.get(f"{BASE}/lawService.do")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(200, json=load("law_articles.json")),
    ]
    assert "법령" in client.service("law", MST="1")
    assert route.call_count == 2
