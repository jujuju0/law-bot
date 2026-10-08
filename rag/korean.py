"""한국어 형태소 분석(kiwipiepy) 공용 유틸 — 줄 병합 띄어쓰기 판단과 BM25 토큰화가 공유한다."""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from kiwipiepy import Kiwi

# BM25 색인·질의에 쓰는 품사: 일반·고유명사, 동사·형용사 어간, 어근, 외국어, 숫자
CONTENT_TAGS = frozenset({"NNG", "NNP", "VV", "VA", "XR", "SL", "SN"})


@lru_cache(maxsize=1)
def get_kiwi() -> Kiwi:
    """기본 Kiwi 싱글톤(모델 로딩 1회). 사용자 사전 없음 — 줄 병합 띄어쓰기 판단용."""
    return Kiwi()


def kiwi_with_user_words(words: Iterable[str], tag: str = "NNP") -> Kiwi:
    """사용자 사전을 등록한 별도 Kiwi 인스턴스(공용 싱글톤은 건드리지 않는다)."""
    kiwi = Kiwi()
    for w in sorted(set(words)):
        kiwi.add_user_word(w, tag)
    return kiwi


def content_tokens(
    text: str, kiwi: Kiwi | None = None, stopwords: frozenset[str] = frozenset()
) -> list[str]:
    """내용어 형태소만 뽑는다(영문은 소문자). 예: "국내대리인을 지정" → ["국내", "대리인", "지정"]."""
    tokens = (
        t.form.lower() if t.tag == "SL" else t.form
        for t in (kiwi or get_kiwi()).tokenize(text)
        if t.tag in CONTENT_TAGS
    )
    return [t for t in tokens if t not in stopwords]
