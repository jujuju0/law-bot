"""청크 payload 인메모리 조회 (chunks.jsonl). BM25·Router·Ref/Delegation expansion이 공유한다.

Qdrant 컬렉션 `COLLECTION_NAME`은 같은 chunks.jsonl로 적재되므로 payload가 동일하다.
조 단위 조회는 Qdrant scroll 대신 여기서 해서 네트워크 왕복을 없애고 오프라인 테스트를 가능하게 한다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from common.config import PROCESSED_DIR
from rag.chunker import load_chunks

CHUNKS_PATH = PROCESSED_DIR / "chunks.jsonl"


class ChunkStore:
    """chunk_id·article_key → payload 조회. payload 순서는 chunks.jsonl(조문 순서) 그대로."""

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.by_id = {p["chunk_id"]: p for p in payloads}
        self._by_article: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for p in payloads:
            self._by_article[p["article_key"]].append(p)

    def article(self, key: str) -> list[dict[str, Any]]:
        """조 키(`law:a31`, `annex:2`)에 속한 청크 payload 목록(없으면 빈 리스트)."""
        return self._by_article.get(key, [])

    def __contains__(self, key: str) -> bool:
        return key in self._by_article


@lru_cache(maxsize=2)
def get_chunk_store(path: Path = CHUNKS_PATH) -> ChunkStore:
    """chunks.jsonl 기반 ChunkStore 싱글톤(경로별 1회 로딩)."""
    return ChunkStore([asdict(c) for c in load_chunks(path)])
