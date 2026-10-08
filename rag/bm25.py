"""BM25 희소 검색 (kiwipiepy 형태소 + rank_bm25). 색인 대상은 chunks.jsonl의 `embed_text`.

토큰화는 BM25 전용 Kiwi를 쓴다: 법령 본문의 정의어("인공지능", "국내대리인" 등)를 사용자 사전에 등록해
`인공/지능`처럼 쪼개지지 않게 하고, 1음절 경동사·형용사와 `법`은 불용어로 뺀다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from kiwipiepy import Kiwi
from rank_bm25 import BM25Okapi

from common.config import PROCESSED_DIR
from rag.chunker import load_chunks
from rag.korean import content_tokens, kiwi_with_user_words

# 법령 정의 문장의 정의어: "국내대리인"이란 / "협회"라 한다 / "위원회"라 한다
DEFINED_TERM = re.compile(
    r"[\"“]([^\"”]{2,20})[\"”](?:이)?(?:란|라\s*한다|이라\s*한다)"
)
STOPWORDS = frozenset(
    {"법", "하", "있", "없", "되", "보", "받", "같", "주", "않", "이"}
)


def defined_terms(texts: Iterable[str]) -> set[str]:
    """정의어를 어절 단위로 모은다("고영향 인공지능" → 고영향, 인공지능). `대통령령으로 정하는 …`은 제외."""
    words: set[str] = set()
    for text in texts:
        for m in DEFINED_TERM.finditer(text):
            if m[1].startswith("대통령령"):
                continue
            words.update(w for w in m[1].split() if len(w) >= 2)
    return words


class BM25Index:
    """청크 payload 리스트 위의 BM25 색인."""

    def __init__(
        self, payloads: list[dict], field: str = "embed_text", kiwi: Kiwi | None = None
    ) -> None:
        self.payloads = payloads
        self.kiwi = kiwi
        self._bm25 = BM25Okapi([self.tokenize(p[field]) or ["_"] for p in payloads])

    def tokenize(self, text: str) -> list[str]:
        """색인·질의 공통 토큰화."""
        return content_tokens(text, self.kiwi, STOPWORDS)

    def search(
        self, query: str, sources: tuple[str, ...], limit: int
    ) -> list[tuple[dict, float]]:
        """원천 필터를 적용한 상위 `limit`개 (payload, 점수). 점수 0 이하는 제외."""
        scores = self._bm25.get_scores(self.tokenize(query))
        ranked = sorted(
            (
                (p, float(s))
                for p, s in zip(self.payloads, scores, strict=True)
                if p["source_type"] in sources and s > 0
            ),
            key=lambda x: x[1],
            reverse=True,
        )
        return ranked[:limit]


@lru_cache(maxsize=4)
def get_bm25_index(
    path: Path = PROCESSED_DIR / "chunks.jsonl", field: str = "embed_text"
) -> BM25Index:
    """chunks.jsonl로 만든 BM25 색인 싱글톤(경로·필드별 1회)."""
    payloads = [asdict(c) for c in load_chunks(path)]
    kiwi = kiwi_with_user_words(defined_terms(p["text"] for p in payloads))
    return BM25Index(payloads, field=field, kiwi=kiwi)
