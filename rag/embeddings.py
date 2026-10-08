"""임베딩 캐시: (모델, 텍스트) sha256 → 벡터. 적재(문서)와 검색(질의) 모두 이 캐시를 거친다."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from common.ai_model import get_embedding_model
from common.config import EMBEDDING_MODEL, PROCESSED_DIR
from common.usage import count_tokens, tracker

logger = logging.getLogger(__name__)

EMBED_CACHE_DIR = PROCESSED_DIR / "embedding_cache"
BATCH_SIZE = 64


class EmbeddingCache:
    """(모델, 텍스트) sha256 → 벡터 캐시. 실험마다 재적재해도 바뀐 텍스트만 임베딩한다."""

    def __init__(
        self, model: str = EMBEDDING_MODEL, cache_dir: Path = EMBED_CACHE_DIR
    ) -> None:
        self.model = model
        self.path = cache_dir / f"{model.replace('/', '_')}.jsonl"
        self._vectors: dict[str, list[float]] = {}
        if self.path.exists():
            with self.path.open(encoding="utf-8") as f:
                for line in f:
                    row = json.loads(line)
                    self._vectors[row["k"]] = row["v"]

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model}\n{text}".encode()).hexdigest()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """캐시에 없는 텍스트만 배치로 임베딩하고 결과를 캐시에 추가한다."""
        missing = list(
            dict.fromkeys(t for t in texts if self._key(t) not in self._vectors)
        )
        if missing:
            embedder = get_embedding_model()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                tracker.add_embed(sum(count_tokens(t) for t in missing))
                for i in range(0, len(missing), BATCH_SIZE):
                    batch = missing[i : i + BATCH_SIZE]
                    for text, vec in zip(
                        batch, embedder.embed_documents(batch), strict=True
                    ):
                        k = self._key(text)
                        self._vectors[k] = vec
                        f.write(json.dumps({"k": k, "v": vec}) + "\n")
            logger.info(
                "임베딩 %d건 새로 계산 (캐시 %d건 재사용)",
                len(missing),
                len(texts) - len(missing),
            )
        return [self._vectors[self._key(t)] for t in texts]


@lru_cache(maxsize=1)
def get_embedding_cache() -> EmbeddingCache:
    """프로세스 공용 캐시(1회 로딩)."""
    return EmbeddingCache()
