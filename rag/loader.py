"""sources.yaml → Open API(캐시 우선) → 원천 무관 `LawDocument` 리스트.

사용: uv run python -m rag.loader [--refresh] [--sources law,decree,annex]
"""

from __future__ import annotations

import argparse
import logging
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from common.config import SOURCES_FILE
from common.law_api import (
    CacheKey,
    LawApiClient,
    LawApiError,
    as_list,
    as_text,
    normalize_article,
)

logger = logging.getLogger(__name__)

SOURCE_TYPES = ("law", "decree", "annex", "admrul", "term")
# 용어 정의 끝에 붙는 시행일 주석: "[시행일: 2026.1.24] 제2조제4호라목 중 …에 관한 부분"
TERM_NOTE = re.compile(r"\[시행일:[^\]]*\][^\n]*")


@dataclass
class LawDocument:
    """loader 출력: 원천 무관 공통 형태 (DESIGN §3.1)."""

    source_type: str  # law | decree | annex | admrul | term
    doc_id: str  # MST / 행정규칙일련번호 / "{decree MST}:{별표번호}" / 용어명
    title: str
    meta: dict[str, Any]
    units: list[Any]  # law/decree: list[Article], 그 외: 원천별 본문 블록(dict)
    addenda: list[dict[str, str]] = field(default_factory=list)  # 부칙


def load_sources(path: Path = SOURCES_FILE) -> dict[str, Any]:
    """수집 대상 고정 파일을 읽는다."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 원천별 변환
# ---------------------------------------------------------------------------
def _law_body(client: LawApiClient, source_type: str, mst: str) -> dict:
    return client.service("law", cache=CacheKey(source_type, mst), MST=mst)["법령"]


def _addenda(raw: Any) -> list[dict[str, str]]:
    return [
        {
            "key": as_text(a.get("부칙키")),
            "promulgation_no": as_text(a.get("부칙공포번호")),
            "promulgation_date": as_text(a.get("부칙공포일자")),
            "text": as_text(a.get("부칙내용")),
        }
        for a in as_list(raw)
    ]


def law_document(body: dict, source_type: str, mst: str) -> LawDocument:
    """법률·시행령 본문(`법령`)을 `LawDocument`로 변환한다."""
    info = body["기본정보"]
    return LawDocument(
        source_type=source_type,
        doc_id=mst,
        title=as_text(info.get("법령명_한글")),
        meta={
            "law_id": as_text(info.get("법령ID")),
            "kind": as_text(info.get("법종구분")),
            "short_name": as_text(info.get("법령명약칭")),
            "promulgation_no": as_text(info.get("공포번호")),
            "promulgation_date": as_text(info.get("공포일자")),
            "effective_date": as_text(info.get("시행일자")),
            "ministry": as_text(info.get("소관부처")),
        },
        units=[
            normalize_article(u) for u in as_list(body.get("조문", {}).get("조문단위"))
        ],
        addenda=_addenda(body.get("부칙", {}).get("부칙단위")),
    )


def annex_documents(
    body: dict, mst: str, targets: Iterable[dict[str, Any]]
) -> list[LawDocument]:
    """시행령 본문의 `별표단위`에서 sources.yaml에 지정한 별표만 꺼낸다(서식 제외)."""
    by_number = {
        int(b["별표번호"]): b
        for b in as_list(body.get("별표", {}).get("별표단위"))
        if b.get("별표구분") == "별표" and not int(b.get("별표가지번호") or 0)
    }
    decree_title = as_text(body["기본정보"].get("법령명_한글"))
    docs = []
    for t in targets:
        number = int(t["number"])
        unit = by_number.get(number)
        if unit is None:
            raise LawApiError(f"시행령 MST={mst}에 별표 {number}가 없습니다.")
        docs.append(
            LawDocument(
                source_type="annex",
                doc_id=f"{mst}:{number}",
                title=as_text(unit.get("별표제목")),
                meta={
                    "parent": t.get("law", "decree"),
                    "parent_mst": mst,
                    "parent_title": decree_title,
                    "effective_date": as_text(body["기본정보"].get("시행일자")),
                    "number": number,
                    "annex_key": as_text(unit.get("별표키")),
                    "short_title": t.get("title", ""),
                },
                units=[{"text": as_text(unit.get("별표내용"))}],
            )
        )
    return docs


def admrul_document(body: dict, rule_id: str, short: str | None = None) -> LawDocument:
    """행정규칙 본문(`AdmRulService`)을 변환한다. `조문내용`은 조 1개 = 문자열 1개."""
    info = body["행정규칙기본정보"]
    title = as_text(info.get("행정규칙명"))
    return LawDocument(
        source_type="admrul",
        doc_id=rule_id,
        title=title,
        meta={
            "short_name": short or title,
            "kind": as_text(info.get("행정규칙종류")),
            "issue_no": as_text(info.get("발령번호")),
            "issue_date": as_text(info.get("발령일자")),
            "effective_date": as_text(info.get("시행일자")),
            "ministry": as_text(info.get("소관부처명")),
        },
        units=[
            {"text": as_text(s)} for s in as_list(body.get("조문내용")) if as_text(s)
        ],
        addenda=_addenda(body.get("부칙")),
    )


def term_document(
    term: str, body: dict, allowed_sources: Iterable[str]
) -> LawDocument | None:
    """법령용어 본문(`LsTrmService`, 열 방향 병렬 리스트)에서 허용 출처의 정의만 남긴다."""
    defs = as_list(body.get("법령용어정의"))
    sources = as_list(body.get("출처"))
    seqs = as_list(body.get("법령용어일련번호"))
    allowed = tuple(allowed_sources)
    units = [
        {
            "definition": TERM_NOTE.sub("", as_text(d)).strip(),
            "source": as_text(s),
            "seq": as_text(q),
        }
        for d, s, q in zip(defs, sources, seqs, strict=False)
        if any(as_text(s).startswith(a) for a in allowed)
    ]
    if not units:
        return None
    return LawDocument(
        source_type="term", doc_id=term, title=term, meta={}, units=units
    )


# ---------------------------------------------------------------------------
# 수집
# ---------------------------------------------------------------------------
def _find_term_seqs(client: LawApiClient, term: str) -> str | None:
    items = client.search("lstrm", term, cache=CacheKey("term", f"_search_{term}"))
    for item in items:
        if as_text(item.get("법령용어명")) == term:
            return as_text(item.get("법령용어ID"))
    return None


def load_documents(
    sources: dict[str, Any] | None = None,
    client: LawApiClient | None = None,
    only: Iterable[str] = SOURCE_TYPES,
) -> list[LawDocument]:
    """sources.yaml의 대상을 캐시(없으면 API)에서 읽어 `LawDocument` 리스트로 만든다."""
    sources = sources if sources is not None else load_sources()
    client = client or LawApiClient()
    only = set(only)
    docs: list[LawDocument] = []

    law_titles: list[str] = []
    for source_type in ("law", "decree"):
        for entry in sources.get(source_type) or []:
            mst = str(entry["mst"])
            body = _law_body(client, source_type, mst)
            doc = law_document(body, source_type, mst)
            law_titles.append(doc.title)
            if source_type in only:
                docs.append(doc)
            if source_type == "decree" and "annex" in only:
                targets = [
                    a for a in sources.get("annex") or [] if a.get("law") == "decree"
                ]
                docs.extend(annex_documents(body, mst, targets))

    loaders: dict[str, Callable[[Any], LawDocument | None]] = {
        "admrul": lambda e: admrul_document(
            client.service(
                "admrul", cache=CacheKey("admrul", str(e["id"])), ID=str(e["id"])
            )["AdmRulService"],
            str(e["id"]),
            short=e.get("short"),
        ),
        "term": lambda term: _load_term(client, term, law_titles),
    }
    for source_type, load in loaders.items():
        if source_type not in only:
            continue
        for entry in sources.get(source_type) or []:
            doc = load(entry)
            if doc is not None:
                docs.append(doc)
    return docs


def _load_term(
    client: LawApiClient, term: str, law_titles: list[str]
) -> LawDocument | None:
    seqs = _find_term_seqs(client, term)
    if seqs is None:
        logger.warning("법령용어 목록에 '%s'가 없습니다 — 건너뜀", term)
        return None
    body = client.service("lstrm", cache=CacheKey("term", term), trmSeqs=seqs)
    doc = term_document(term, body["LsTrmService"], law_titles)
    if doc is None:
        logger.warning("'%s' 정의 중 인공지능기본법 출처가 없습니다 — 건너뜀", term)
    return doc


def main() -> None:
    """CLI: 수집(캐시 우선) 결과를 원천별로 요약 출력한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh", action="store_true", help="캐시를 무시하고 API 재호출"
    )
    parser.add_argument("--sources", default=",".join(SOURCE_TYPES))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    with LawApiClient(refresh=args.refresh) as client:
        docs = load_documents(client=client, only=args.sources.split(","))
    counts = Counter(d.source_type for d in docs)
    for d in docs:
        print(f"[{d.source_type}] {d.doc_id} {d.title} — units {len(d.units)}")
    print("문서 수:", dict(counts))


if __name__ == "__main__":
    main()
