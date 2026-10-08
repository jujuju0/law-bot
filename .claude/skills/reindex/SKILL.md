---
name: reindex
description: Open API 캐시(data/raw)에서 법령 데이터를 다시 청킹·임베딩해 Qdrant 컬렉션을 재적재한다(필요하면 API 재수집 포함). 청킹 코드·sources.yaml·임베딩 모델을 바꾼 뒤, 또는 컬렉션이 비었을 때 사용.
---

# 수집·재적재 절차

## 1. 사전 점검
- Qdrant: `curl -s localhost:6333/collections`. 실패 시 `docker compose -f docker-qdrant/docker-compose.yaml up -d`.
- 캐시: `ls data/raw/*/ | head` 와 `data/sources.yaml` 확인.
- 재적재 대상 컬렉션과 sources를 사용자에게 한 줄로 알린다 (삭제 후 재생성이므로).

## 2. 수집 (필요할 때만)
다음 경우에만 `--refresh`:
- sources.yaml에 새 대상 추가 / 캐시가 비어 있음 / 사용자가 최신화를 요청
```bash
uv run python -m rag.loader --refresh [--only law,decree]
```
- `LawApiAuthError`(HTML·검증 실패 응답)면 중단하고 "OC 값과 open.law.go.kr의 API별 활용 신청 승인 상태 확인"을 안내.
- 재수집 후 `data/raw/manifest.json`에서 sha256이 바뀐 문서를 보고 → 바뀌었다면 법령 개정 가능성 알림 + sources.yaml `snapshot_date` 갱신.

## 3. 청킹만 먼저 (임베딩 비용 전 검증)
```bash
uv run python -m rag.chunker --dry-run       # 원천별 청크 수, chunk_type 분포, 위임 그래프 엣지 수 출력
uv run pytest -q tests/test_law_api.py tests/test_chunker.py
```
- 실패 시 중단. 청킹 규칙을 바꿨다면 `chunk-inspector`로 점검 → 치명 이슈 있으면 중단.

## 4. 적재
```bash
uv run python -m rag.vectorstore --rebuild [--sources law,decree,annex,admrul,term,expc] [--naive]
```

## 5. 확인
- 원천별 포인트 수 = chunks.jsonl의 원천별 줄 수 (Qdrant `count` with filter)
- 샘플 검색 4개 (정의 / 조문번호 / 일상어 / 위임 세부)로 상위 3개 citation 출력

## 6. 보고
`원천별 청크 수 | 위임 엣지 수 | 샘플 검색 결과 | snapshot_date` 형식. 청킹이 바뀌었으므로 이전 평가 결과는 재측정 필요하다고 안내.
