---
name: add-retrieval-technique
description: 새 Advanced RAG 검색 기법(BM25, RRF, Rerank, Router, Multi-Query, Term/Ref/Delegation expansion 등)을 플래그 기반으로 추가하고 ablation 평가까지 마치는 표준 절차. 검색 기법을 구현하거나 바꿀 때 사용.
---

# 검색 기법 추가 절차

RFP 핵심: "여러 기법을 많이 적용하는 것이 아니라, 어떤 방법이 실제 검색 결과를 개선했는지 확인하는 것."
따라서 모든 기법은 **끄고 켤 수 있어야** 하고, **평가 없이 채택하지 않는다.**

## 1. 근거 확인
- 이 기법이 해결하려는 실패 유형(retrieval-analyst 원인 코드)과 대상 문항을 한 줄로 적는다.
  예: "VOCAB 실패 q007, q012, q019 → Multi-Query"
- 근거가 없으면 사용자에게 먼저 baseline 실패 분석을 제안한다.

## 2. 구현
1. `rag/config.py`의 `RetrievalConfig`에 `use_<technique>: bool = False` 및 하이퍼파라미터 추가 (기본값 False → 기존 실험 재현성 유지)
2. 구현 위치
   | 기법 | 파일 |
   |---|---|
   | BM25 / RRF / Router / Multi-Query / Ref-expansion | `rag/retriever.py` (단계별 private 함수) |
   | Rerank | `rag/reranker.py` (`rerank(question, chunks, top_k) -> list[RetrievedChunk]`) |
3. 각 단계는 `RetrievedChunk.stage_scores[<stage>]`에 점수를 남긴다 (debug·분석용).
4. 무거운 객체(BM25 인덱스, CrossEncoder)는 모듈 레벨 lazy 싱글톤으로 1회 로딩.
5. `eval/configs.py`에 새 프리셋 추가: 직전 채택 프리셋 + 이번 플래그만 True (한 번에 하나만 바꾼다).

## 3. 테스트
- `tests/test_retriever.py`에 최소 1개: 대상 실패 문항 중 하나가 top-3에 들어오는지.
- `uv run pytest -q tests/test_retriever.py`

## 4. 평가 & 기록
- `/run-eval` 스킬로 새 프리셋 실행 (dev).
- 지연이 2배 이상 늘면 보고에 강조.
- EXPERIMENTS.md에 채택/기각 결정을 사용자와 확정.

## 5. 정리
- 기각된 기법도 코드는 남기되 서비스 프리셋에서는 끈다.
- `docs/DESIGN.md §4.2` 표에 실제 사용한 하이퍼파라미터를 반영.

## 기법별 구현 메모
- **BM25**: `kiwipiepy.Kiwi().tokenize(text)`에서 품사 `NNG,NNP,VV,VA,SL,SN` 형태만 사용. 인덱스 대상은 `embed_text`.
- **RRF**: `score(d) = Σ_i 1 / (k + rank_i(d))`, rank는 1부터. k=60.
- **Router**: `제\s*(\d+)\s*조(?:\s*의\s*(\d+))?` (공백 변형 허용) → Qdrant `scroll` with `FieldCondition(key="article_no", match=MatchAny(any=[...]))`.
- **Multi-Query**: 원 질문 포함 n+1개 쿼리. LLM 출력은 JSON 배열로 받고 파싱 실패 시 원 질문만 사용.
- **Rerank**: 입력 쌍은 `(question, parent_text 또는 text)` — 둘 다 실험해 볼 것. `max_length=512`.
- **Ref-expansion**: 상위 3개 청크의 `refs` → 해당 조 청크를 점수 `min_score * 0.9`로 뒤에 추가. `added_by="ref"`.
- **Delegation expansion**: 상위 청크가 법률이고 `delegated=true`면 `delegates_to` 청크를, 시행령 청크면 `delegated_from` 법률 청크를, 시행령 청크가 `annex:*`를 refs로 가지면 해당 별표 청크를 추가 (총 `max_expansion`개). `added_by="delegation"`. 그래프는 `data/processed/delegation_graph.json`에서 로딩.
- **Term expansion**: `term` 청크로 만든 사전(용어명 → 정의 핵심어). 질문에 용어/동의어가 있으면 질의 뒤에 정식 용어 덧붙임. LLM 호출 없음.
- **Router (v2)**: `(시행령|영)\s*제\s*(\d+)\s*조` → `source_type=decree`, `별표\s*(\d+)` → `source_type=annex`, 그 외 `제N조` → `law`.
- **sources 추가 실험**: 코드 변경 없이 `RetrievalConfig.sources`만 바꾼 프리셋을 만든다 (E8). 원천 추가 효과와 연결 기법 효과를 분리하기 위해.
