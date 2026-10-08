"""검색 설정(`RetrievalConfig`)과 실험·서비스 프리셋 (DESIGN §4.1, §8).

모든 Advanced 기법은 플래그로 on/off 한다(기본 False → 이전 실험 재현성 유지).
프리셋은 직전 채택 프리셋 + 플래그 1개씩만 바꿔 만든다(/add-retrieval-technique).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from common.config import COLLECTION_NAME, NAIVE_COLLECTION_NAME, RAW_COLLECTION_NAME


@dataclass(frozen=True)
class RetrievalConfig:
    """검색 파이프라인 설정."""

    name: str = "baseline"
    collection: str = COLLECTION_NAME
    sources: tuple[str, ...] = ("law",)  # 검색 대상 원천 (payload source_type 필터)
    top_k: int = 5
    candidate_k: int = 20  # 단계 간 넘기는 후보 수 (fusion·rerank 대상)
    use_bm25: bool = False  # T3.1: kiwi 형태소 BM25를 dense와 RRF로 결합
    rrf_k: int = 60
    use_rerank: bool = False  # T3.2: 1단계 후보(candidate_k개)를 CrossEncoder로 재정렬
    # 재순위화 입력 문서: embed_text | parent_text | text
    rerank_field: str = "embed_text"
    rerank_max_length: int = 512


E0 = RetrievalConfig(name="E0_naive", collection=NAIVE_COLLECTION_NAME)
E1 = RetrievalConfig(name="E1_structure", collection=RAW_COLLECTION_NAME)
E2 = RetrievalConfig(name="E2_header")
E3 = replace(E2, name="E3_hybrid", use_bm25=True)
E4 = replace(E3, name="E4_rerank", use_rerank=True)
# E4 변형: 입력을 조 전체(parent_text)로 — 항·호 청크도 조 문맥으로 판단 (/add-retrieval-technique 메모)
E4_PARENT = replace(E4, name="E4_rerank_parent", rerank_field="parent_text")

PRESETS: dict[str, RetrievalConfig] = {
    cfg.name: cfg
    for cfg in (
        E0,
        E1,
        E2,
        E3,
        E4,
        E4_PARENT,
        replace(E2, name="baseline"),
    )
}


def get_preset(name: str) -> RetrievalConfig:
    """이름으로 프리셋을 찾는다(없으면 사용 가능한 이름과 함께 KeyError)."""
    try:
        return PRESETS[name]
    except KeyError:
        raise KeyError(
            f"알 수 없는 프리셋 '{name}'. 사용 가능: {', '.join(PRESETS)}"
        ) from None
