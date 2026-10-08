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
    # T3.3: 질문의 "제N조"·"시행령 제N조"·"별표 N" 조를 맨 앞에 고정
    use_router: bool = False
    # T3.4: data/term_synonyms.yaml 별칭 → 정식 용어 덧붙임 / LLM 재작성 질의 n개(질의별 순위 RRF)
    use_term_expansion: bool = False
    use_multi_query: bool = False
    n_queries: int = 3
    # T3.5: 같은 조 청크를 1개로 합침(2개 이상 합쳐진 법령 조는 본문=조 전체)
    small_to_big: bool = False
    # T3.5 / T3.7: 상위 expansion_seed_k개의 참조 조(같은 원천) / 위임 연결(법↔영↔별표·고시)을
    # 종류별 최대 max_expansion개 결과 뒤에 덧붙인다
    use_ref_expansion: bool = False
    use_delegation_expansion: bool = False
    max_expansion: int = 3
    expansion_seed_k: int = 3
    # T3.8: 순위 점수 1/(rrf_k+rank)에 priority 1이면 +boost, 2면 +boost/2
    priority_boost: float = 0.0


E0 = RetrievalConfig(name="E0_naive", collection=NAIVE_COLLECTION_NAME)
E1 = RetrievalConfig(name="E1_structure", collection=RAW_COLLECTION_NAME)
E2 = RetrievalConfig(name="E2_header")
E3 = replace(E2, name="E3_hybrid", use_bm25=True)
E4 = replace(E3, name="E4_rerank", use_rerank=True)
# E4 변형: 입력을 조 전체(parent_text)로 — 항·호 청크도 조 문맥으로 판단 (/add-retrieval-technique 메모)
E4_PARENT = replace(E4, name="E4_rerank_parent", rerank_field="parent_text")
# ↓ E4 이후 프리셋은 "직전 채택 프리셋 + 플래그 1개" 규칙으로 계획(DESIGN §8)대로 쌓아 둔 것.
#   평가(로컬 실행 대기) 후 기각된 기법이 있으면 다음 프리셋의 기반을 바꾼다 — docs/TASKS.md "로컬 실행 대기".
E5 = replace(E4, name="E5_router", use_router=True)
E6_TERM = replace(E5, name="E6_term", use_term_expansion=True)
E6_MQ = replace(E5, name="E6_multi_query", use_multi_query=True)
E6 = E6_TERM  # 결정 대기: E6_term vs E6_multi_query (비용 대비 효과)
E7_REF = replace(E6, name="E7_ref", use_ref_expansion=True)
E7_S2B = replace(E7_REF, name="E7_small_to_big", small_to_big=True)
E7 = E7_S2B  # 결정 대기
CORE_SOURCES = ("law", "decree", "annex")
E8 = replace(E7, name="E8_sources", sources=CORE_SOURCES)
# 대조군: E9는 확장으로 최대 top_k + max_expansion개를 돌려주므로 같은 개수를 검색만으로 채운 경우
E8_K8 = replace(E8, name="E8_sources_k8", top_k=E8.top_k + E8.max_expansion)
E9 = replace(E8, name="E9_delegation", use_delegation_expansion=True)
E10 = replace(
    E9, name="E10_aux", sources=(*CORE_SOURCES, "admrul", "term")
)  # expc 미수집
E10_BOOST = replace(E10, name="E10_aux_boost", priority_boost=0.002)

PRESETS: dict[str, RetrievalConfig] = {
    cfg.name: cfg
    for cfg in (
        E0,
        E1,
        E2,
        E3,
        E4,
        E4_PARENT,
        E5,
        E6_TERM,
        E6_MQ,
        E7_REF,
        E7_S2B,
        E8,
        E8_K8,
        E9,
        E10,
        E10_BOOST,
        replace(E2, name="baseline"),
        # 서비스 프리셋(SERVICE_RETRIEVAL_PRESET 기본값). T3.9에서 평가 결과로 확정 — 현재는 잠정
        replace(E10, name="full"),
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
