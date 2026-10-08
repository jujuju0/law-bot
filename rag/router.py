"""질문 속 조문 번호·정의 Router (DESIGN §4.2, T3.3): "법 제28조", "시행령 25조", "영 제1조의2", "별표 2" → 조 키, "X란 무엇인가요" → 정의 청크."""

from __future__ import annotations

import re

from rag.chunk_store import get_chunk_store
from rag.legal_text import article_ref

# 접두어(법/시행령/영)는 앞이 한글이 아닐 때만 인정("운영 제3조"의 '영', "기본법 31조"의 '법' 제외)
ARTICLE_MENTION = re.compile(
    r"(?:(?<![가-힣])(시행령|영|법)\s*)?(?<![\d])(?:제\s*)?(\d{1,3})\s*조(?:\s*의\s*(\d+))?(?!원)"
)
ANNEX_MENTION = re.compile(r"별표\s*(\d+)")
PREFIX_SOURCE = {"시행령": "decree", "영": "decree", "법": "law"}


def parse_article_refs(question: str) -> list[str]:
    """질문에서 언급된 조·별표 키를 등장 순서대로(중복 제거). 접두어가 없으면 "시행령" 언급 여부로 원천을 정한다."""
    default = "decree" if "시행령" in question else "law"
    found: list[tuple[int, str]] = [
        (m.start(), article_ref(PREFIX_SOURCE.get(m[1] or "", default), m[2], m[3]))
        for m in ARTICLE_MENTION.finditer(question)
    ]
    found += [
        (m.start(), f"annex:{int(m[1])}") for m in ANNEX_MENTION.finditer(question)
    ]
    return list(dict.fromkeys(key for _, key in sorted(found)))


# "X이란", "X의 뜻/정의/의미", "X는 무엇/뭐" — X가 법령 정의어일 때만 정의 질문으로 본다
DEFINITION_ASK = (
    r"\s*(?:이란|란|의\s*(?:뜻|정의|의미)|(?:이|가|은|는)\s*(?:무엇|뭔|뭐|어떤))"
)


def parse_definition_chunks(question: str) -> list[str]:
    """정의 질문이면 정의 조문 청크 id(법·시행령 정의 호)와 용어 청크 id를 돌려준다. 아니면 []."""
    payloads = get_chunk_store().payloads
    terms = sorted(
        {p["article_title"] for p in payloads if p["source_type"] == "term"},
        key=len,
        reverse=True,
    )
    for term in terms:
        if not re.search(re.escape(term) + DEFINITION_ASK, question):
            continue
        marker = f'"{term}"이란'
        defs = [
            p["chunk_id"]
            for p in payloads
            if p["source_type"] in ("law", "decree") and marker in p["text"]
        ]
        return [*defs, f"term:{term}"]
    return []
