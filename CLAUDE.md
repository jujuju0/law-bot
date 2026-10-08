# CLAUDE.md — AI 기본법 RAG QA 백엔드

이 파일은 Claude Code가 매 세션 읽는 프로젝트 메모리다. 상세 설계는 `docs/DESIGN.md`, 진행 상황은 `docs/TASKS.md`, 실험 기록은 `docs/EXPERIMENTS.md`.

## Mission
AI 기본법을 잘 모르는 사용자도 질문만으로 이해할 수 있는 **근거 기반** QA 백엔드(`POST /ask`)를 만든다.
평가 기준의 핵심은 "기법을 많이 쓰는 것"이 아니라 **어떤 기법이 실제로 검색을 개선했는지 수치로 증명하는 것**이다.

## 데이터 원천 — 국가법령정보 공동활용 Open API
| source_type | API target | 내용 |
|---|---|---|
| `law` | `law` | 인공지능기본법(법률 제20676호) — 필수 |
| `decree` | `law` | 같은 법 시행령 — 필수 |
| `admrul` | `admrul` | 과기정통부 고시·가이드라인 |
| `annex` | `licbyl` | 시행령 별표(과태료 부과기준 등). **본문은 HTML만 제공** → Docling으로 표 변환 |
| `term` | `lstrm` | 법령용어 정의 (선택) |
| `expc` | `expc` | 법령해석례 (선택) |

- 수집 대상은 `data/sources.yaml`에 고정. API 원문은 `data/raw/`에 캐시하고 **파이프라인은 캐시를 읽는다**(재호출은 `--refresh`).
- 인증키 `OC`는 `.env`의 `LAW_OC`. **코드·문서·테스트·커밋에 OC 값을 쓰지 않는다**(훅이 차단). 로그·manifest에 URL을 남길 때 OC 파라미터 제거.
- 인증이 안 되면(OC 오류, API 활용 신청 미승인 등) JSON 대신 HTML·오류 메시지가 올 수 있으니 응답을 검사한다.
- 서비스(`/ask`)는 런타임에 law.go.kr을 호출하지 않는다.
- API 호출·응답 구조·정규화 규칙은 `/law-api` 스킬 참고.

## 아키텍처 (한 줄 요약)
Offline: `law_api(캐시) → loader → chunker(+위임 그래프) → vectorstore(Qdrant)`
Online: `router → (term/multi-query) → dense+BM25 → RRF → rerank → ref/delegation expansion → LLM → answer+sources`
모든 Advanced 기법은 `RetrievalConfig`의 플래그로 on/off 가능해야 한다(ablation 때문).

## 명령어
```bash
uv sync
docker compose -f docker-qdrant/docker-compose.yaml up -d      # Qdrant (:6333/dashboard)
uv run python -m rag.loader --refresh                          # Open API 수집 → data/raw/ (필요할 때만)
uv run python -m rag.chunker --dry-run                         # 청킹만 → data/processed/chunks.jsonl
uv run python -m rag.vectorstore --rebuild [--sources law,decree,annex]
uv run python -m eval.evaluate --config baseline               # 평가 → eval/results/
uv run uvicorn app.main:app --reload                           # API (:8000/docs)
uv run pytest -q
uv run ruff check . && uv run ruff format .
```

## 코드 규칙
- Python 3.12, 타입힌트 필수, 공개 함수는 docstring 1~2줄.
- 설정값은 `common/config.py`에서만 읽는다. 모델명·URL·컬렉션명·OC 하드코딩 금지.
- law.go.kr 호출은 `common/law_api.LawApiClient`로만. `requests`/`httpx` 직접 호출 금지.
- 중복 코드가 발생하지 않고 유지보수하기 용이하도록 확장성 있는 코드로 설계한다.
- repo 구조나 코드 설계는 실무에서 선호하는 구조로 설계한다.
- API 응답은 **단건 dict / 다건 list가 섞여 온다** → 항상 `as_list()`로 정규화.
- 청크 payload 스키마는 `docs/DESIGN.md §3.3`이 단일 기준. 필드를 바꾸면 DESIGN.md와 `tests/test_chunker.py`를 같이 고친다.
- 파서 테스트는 `tests/fixtures/`의 저장된 응답으로 돌린다(네트워크 없이).
- 실험 코드는 `notebook/`, 서비스 코드는 `rag/`·`app/`.

## 답변 생성 규칙 (절대 원칙)
1. 검색된 근거 **안에서만** 답한다. LLM 일반 지식으로 보충 금지.
2. 모든 주장 뒤에 citation 표기: `[법 제31조 제2항]`, `[영 제22조]`, `[영 별표 1]`, `[고시 ○○ 제3조]`. 인용은 검색 결과에 실제로 있어야 한다(후처리 검증).
3. 효력 순서 법률 > 시행령 > 고시 > 해석례·용어. 해석례는 "해석 사례", 용어는 "참고 정의"로 구분.
4. 위임 조항인데 하위 법령 근거가 없으면 "하위 법령에 위임되어 있으나 제공된 자료에서 확인되지 않습니다".
5. 근거가 없으면 거절: "제공된 AI 기본법 관련 법령에서 확인할 수 없습니다."
6. 금액·기간 같은 숫자는 근거 텍스트에 있는 것만.
7. 응답에 `notice`(AI 생성 표시, 법 제31조②)와 `data_snapshot`(수집 일자) 포함.

## 비용 규칙 (크레딧 예산 — DESIGN §9)
- LLM·임베딩 호출은 `common/cache.py` 캐시를 거친다. 캐시를 우회하는 직접 호출 금지.
- 모든 실행의 토큰 사용량은 `common/usage.py`로 `eval/usage_ledger.jsonl`에 기록한다.
- `eval.evaluate --answer`는 **최종 후보 config에만**, 실행 전 예상 크레딧을 사용자에게 보여주고 승인받는다.
- 개발 중 확인은 `--limit 5`. 전체 재적재·전체 답변 평가 전에는 `uv run python -m common.usage --summary`로 잔여 예산 확인.

## 템플릿에서 알려진 함정
- `common/ai_model.get_llm_model()`은 `model` 인자를 받지만 내부에서 `MODEL` 상수를 쓴다 → judge 모델 교체 불가. `model=model`로 수정.
- `common/config.py`의 `TEMPERATURE`, `MAX_TOKENS`는 문자열이고 실제로 쓰이지 않는다. `get_llm_model`의 `max_tokens=512`는 긴 답변을 자를 수 있다.
- `notebook/`에서 `common` import 오류 → `uv sync`(editable 설치) 확인.

## 작업 방식
- 검색 기법 추가: `/add-retrieval-technique` / 평가: `/run-eval` / 수집·재적재: `/reindex` / API 점검: `/api-smoke` / Open API 사용법: `/law-api`
- 에이전트: `chunk-inspector`(청크 품질), `golden-set-builder`(골든셋), `retrieval-analyst`(실패 분석), `grounding-reviewer`(근거 검증)
- `.env`는 읽거나 수정하지 않는다(훅으로 차단). 키 이름은 `.env.example` 참고.
- Qdrant 컬렉션 삭제는 `/reindex`를 통해서만. `data/raw/` 캐시는 지우지 않는다.
