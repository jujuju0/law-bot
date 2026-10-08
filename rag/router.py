"""질문 속 조문 번호 Router (DESIGN §4.2, T3.3): "법 제28조", "시행령 25조", "영 제1조의2", "별표 2" → 조 키."""

from __future__ import annotations

import re

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
