"""청크 임베딩 → Qdrant 적재 (DESIGN §3.5).

컬렉션 삭제·재생성은 이 모듈의 `--rebuild`로만 한다(/reindex).
사용: uv run python -m rag.vectorstore --rebuild [--sources law,decree,annex] [--naive]
"""

from __future__ import annotations

import argparse
import logging
import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict

from qdrant_client import QdrantClient, models

from common.config import (
    COLLECTION_NAME,
    NAIVE_COLLECTION_NAME,
    PROCESSED_DIR,
)
from common.qdrant import get_qdrant_client
from common.usage import record, tracker
from rag.chunker import Chunk, chunk_documents, load_chunks, naive_chunks, write_outputs
from rag.embeddings import EmbeddingCache, get_embedding_cache
from rag.loader import SOURCE_TYPES, load_documents

logger = logging.getLogger(__name__)

VECTOR_NAME = "dense"
BATCH_SIZE = 64
PAYLOAD_INDEXES: dict[str, models.PayloadSchemaType] = {
    "source_type": models.PayloadSchemaType.KEYWORD,
    "chunk_type": models.PayloadSchemaType.KEYWORD,
    "doc_short": models.PayloadSchemaType.KEYWORD,
    "article_key": models.PayloadSchemaType.KEYWORD,
    "article_no": models.PayloadSchemaType.INTEGER,
    "priority": models.PayloadSchemaType.INTEGER,
    "delegated": models.PayloadSchemaType.BOOL,
}


def point_id(chunk_id: str) -> str:
    """chunk_id → 결정적 Point ID (uuid5)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


def ensure_collection(
    client: QdrantClient, collection: str, dim: int, rebuild: bool = False
) -> None:
    """컬렉션과 payload index를 만든다. `rebuild`면 기존 컬렉션을 지우고 다시 만든다."""
    if client.collection_exists(collection):
        if not rebuild:
            return
        client.delete_collection(collection)
        logger.info("컬렉션 삭제: %s", collection)
    client.create_collection(
        collection,
        vectors_config={
            VECTOR_NAME: models.VectorParams(size=dim, distance=models.Distance.COSINE)
        },
    )
    for name, schema in PAYLOAD_INDEXES.items():
        client.create_payload_index(collection, field_name=name, field_schema=schema)


def upsert_chunks(
    chunks: Sequence[Chunk],
    collection: str,
    client: QdrantClient | None = None,
    rebuild: bool = False,
    embed_field: str = "embed_text",
    cache: EmbeddingCache | None = None,
) -> int:
    """청크의 `embed_field` 텍스트를 임베딩해 적재하고 적재 수를 반환한다."""
    client = client or get_qdrant_client()
    cache = cache or get_embedding_cache()
    vectors = cache.embed([getattr(c, embed_field) for c in chunks])
    ensure_collection(client, collection, dim=len(vectors[0]), rebuild=rebuild)
    for i in range(0, len(chunks), BATCH_SIZE):
        client.upsert(
            collection,
            points=[
                models.PointStruct(
                    id=point_id(c.chunk_id), vector={VECTOR_NAME: v}, payload=asdict(c)
                )
                for c, v in zip(
                    chunks[i : i + BATCH_SIZE], vectors[i : i + BATCH_SIZE], strict=True
                )
            ],
        )
    return len(chunks)


def count_by_source(
    collection: str, sources: Iterable[str], client: QdrantClient | None = None
) -> dict[str, int]:
    """원천별 포인트 수 (Qdrant count, exact)."""
    client = client or get_qdrant_client()
    return {
        s: client.count(
            collection,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="source_type", match=models.MatchValue(value=s)
                    )
                ]
            ),
            exact=True,
        ).count
        for s in sources
    }


def main() -> None:
    """CLI: chunks.jsonl(없으면 새로 청킹) 또는 naive 청크를 Qdrant에 적재하고 원천별 수를 검증한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true", help="컬렉션 삭제 후 재생성")
    parser.add_argument("--sources", default=",".join(SOURCE_TYPES))
    parser.add_argument(
        "--naive",
        action="store_true",
        help=f"고정 500자 청킹 → {NAIVE_COLLECTION_NAME}",
    )
    parser.add_argument("--collection", help="컬렉션 이름 (기본: 설정값)")
    parser.add_argument(
        "--embed-field", default="embed_text", choices=["embed_text", "text"]
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sources = args.sources.split(",")

    if args.naive:
        docs = load_documents(only=[s for s in sources if s in ("law", "decree")])
        chunks = [c for d in docs for c in naive_chunks(d)]
        collection = args.collection or NAIVE_COLLECTION_NAME
    else:
        path = PROCESSED_DIR / "chunks.jsonl"
        if not path.exists():
            write_outputs(*chunk_documents(load_documents()))
        chunks = [c for c in load_chunks(path) if c.source_type in sources]
        collection = args.collection or COLLECTION_NAME

    before = tracker.snapshot()
    n = upsert_chunks(
        chunks, collection, rebuild=args.rebuild, embed_field=args.embed_field
    )
    record("reindex", collection, tracker.snapshot() - before)
    expected = Counter(c.source_type for c in chunks)
    actual = count_by_source(collection, expected)
    print(f"{collection}: 적재 {n}건, 원천별 {actual}")
    if not args.rebuild:
        print("(--rebuild 없이 upsert — 이전에 있던 다른 청크가 남아 있을 수 있음)")
    elif actual != dict(expected):
        raise SystemExit(f"포인트 수 불일치: 기대 {dict(expected)} / 실제 {actual}")


if __name__ == "__main__":
    main()
