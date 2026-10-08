# TASKS — 1인 진행 체크리스트 (Open API)

진행 규칙
- 위에서부터 순서대로. 각 Phase의 **DoD(완료 조건)**를 만족해야 다음으로 넘어간다.
- 완료하면 `[x]`로 바꾸고 날짜를 남긴다. Claude에게 "TASKS.md 다음 할 일 진행해줘"라고 하면 첫 번째 미완료 항목부터 진행한다.
- 괄호 안은 사용할 skill(`/이름`) 또는 agent(`@이름`).

---

## Phase 0. 환경 준비 (0.5일)
- [x] T0.1 템플릿 clone, `uv sync`, Qdrant `docker compose up -d`, 대시보드 확인 (2026-10-08)
- [x] T0.2 `.env` 작성 (`.env.example` 참고, `LAW_OC` 포함), notebook에서 LLM·임베딩·Qdrant 연결 확인 (2026-10-08, `notebook/env_check.ipynb`)
- [x] T0.3 의존성: `httpx tenacity pyyaml beautifulsoup4 lxml docling kiwipiepy rank-bm25 sentence-transformers`, dev: `ruff pytest respx` (2026-10-08; docling은 별표 방식 확정 후 제거)
- [x] T0.4 템플릿 버그 수정: `get_llm_model`이 `model` 인자 사용, `max_tokens` 기본 1024 (2026-10-08)
- [x] T0.5 `common/config.py`에 `COLLECTION_NAME`, `LAW_OC`, `LAW_API_BASE`, `SERVICE_RETRIEVAL_PRESET`, `JUDGE_MODEL` 추가 (2026-10-08)
- [x] T0.6 API 호출 확인: WSL 터미널에서 직접 `lawSearch.do?OC=...&target=law&type=JSON&query=인공지능` 호출 → JSON 응답 확인. 실패 시 API별 활용 신청 승인 상태·OC 값 확인 (2026-10-08, curl은 훅이 막아 httpx로 동일 요청 확인)
- [x] T0.7 **API 응답 확인 (/law-api)**: `notebook/api_probe.ipynb`에서 httpx + `common.config.LAW_OC`로 법률 목록·본문, admrul/licbyl/lstrm/expc 목록 1회씩 호출 (curl 직접 호출은 훅이 차단) → `data/raw/`에 저장 → 실제 키 구조 확인 → law-api 스킬의 "확인 결과" 표 채우기 (2026-10-08)

**DoD:** 법률 본문 JSON이 `data/raw/law/`에 저장되고 루트·조문단위 구조를 확인함

## Phase 1. Offline — 수집·청킹·적재 (2일)
- [x] T1.0 (2026-10-08, `LLM_TEMPERATURE`를 비우거나 `none`이면 temperature 인자 생략. 참고: langchain-openai는 gpt-5 계열에서 temperature를 자체적으로 뺌) LLM 설정 연결: `get_llm_model`의 `temperature`·`max_tokens` 기본값을 `common.config`의 `TEMPERATURE`·`MAX_TOKENS`에서 읽기 (기본 0·1024). `.env.example`에는 `LLM_TEMPERATURE=0`, `LLM_MAX_TOKENS=1024` 추가 완료(2026-10-08, config가 읽는 키 이름에 맞춤). 메모: 사용 모델이 `temperature` 인자를 거부하면(일부 reasoning 계열) 인자를 생략하고 호출하도록 처리
- [x] T1.1 `common/law_api.py`: `LawApiClient`(재시도·캐시), `as_list`/`as_text` (DESIGN §2.1·§2.4) (2026-10-08, `normalize_article`→`Article` 포함. admrul/lstrm 본문 루트 키 `AdmRulService`/`LsTrmService` 추가)
  - 인증 실패 감지: target별 **기대 루트 키 맵**(`law→LawSearch`, `admrul→AdmRulSearch`, `lstrm→LsTrmSearch`, `expc→Expc`, `licbyl→licBylSearch`, 본문 `law→법령`). 루트 키가 없으면 응답의 `result`/`msg`를 담아 `LawApiAuthError`. 상태 코드·Content-Type에 의존하지 않음. admrul·lstrm 본문 루트 키는 처음 받을 때 확인해 맵과 DESIGN §2.4에 추가
  - OC 마스킹: **캐시 저장 경로 한 곳**에서만 처리. raw 응답 본문과 manifest URL 모두 OC 값을 `***`로 바꿈
  - 조문 정규화: `항`이 dict면 `as_list`로 감쌈. 항에 `항번호`가 없으면 그 아래 `호`를 조의 직접 자식으로 취급(법 제2·29조, 영 제1조의2·2·11·33조)
  - `fetch_html`(별표 HTML)은 만들지 않음. licbyl은 수집 경로에서 제외
- [x] T1.2 `tests/test_law_api.py`: fixtures + respx, 네트워크 없이 (2026-10-08, 커밋 전 훅은 git 저장소가 아니라 보류)
  - fixtures(`tests/fixtures/`, `data/raw`에서 잘라 저장): 법 제2조(dict 항 + 호·목), 법 제29조(dict 항), 법 제31조(항 list), 법 제1조(항 없음), 전문 행, 인증 실패 응답(`{"result","msg"}`)
  - 테스트: 단건 dict/리스트 정규화, `항번호` 없는 dict 항 → 호가 조의 직접 자식, 루트 키 없을 때 `LawApiAuthError`(200 + JSON이어도), **저장된 raw·manifest 파일에 OC 원문이 없음**
  - (가능하면) 커밋 전 훅: 스테이징된 파일에서 `.env`의 OC 값을 grep해 커밋 차단 (현재 디렉터리는 git 저장소가 아님 → `git init` 후 적용)
- [x] T1.3 수집 대상 → `data/sources.yaml` 확정값 기록 (DESIGN §2.2) (2026-10-08)
  - law MST `282791`, decree MST `288781`, `snapshot_date: 2026-10-08`
  - admrul: 「인공지능제품ㆍ서비스 확인 절차 운영에 관한 고시」 ID `2100000283290` (과기정통부)
  - annex: 시행령 별표 1(이행조치 인정 기준 및 절차), 별표 2(과태료의 부과기준) — decree 본문의 `별표내용`에서 추출. 별지 서식 제외
  - term: 기존 목록 유지
  - expc: 제외 — `query=인공지능` 0건(2026-10-08). T6.4 README 한계에 기록
- [x] T1.4 `rag/loader.py`: sources.yaml → 캐시/수집 → `LawDocument` 리스트, `--refresh` 옵션 (annex는 decree 캐시에서 `LawDocument`로 분리) (2026-10-08, law 1·decree 1·annex 2·admrul 1·term 6. 용어는 인공지능기본법 출처 정의만 — 인공지능시스템·이용자는 해당 정의 없어 제외)
- [x] T1.5 `rag/chunker.py` 법률·시행령 (2026-10-08, 법 108·영 87청크. 호 단위 청크에 도입 문장 포함): 조문단위 계층 → 청크 (긴 조 항 분할, 법 제2조 호 단위, 부칙, 전문=장 컨텍스트)
- [x] T1.6 별표 (2026-10-08, `rag/annex_parser.py`, 줄 경계만 kiwi로 공백 판정. 별표 2 금액 3행 고정값 일치): `별표내용` 고정폭 표 파싱 + 행 그룹 청킹 (DESIGN §3.2 "별표 파싱")
  - 별표 1: 번호 단위(`1.`, `가.`) 청크
  - 별표 2: `일반기준` 1청크, `개별기준` 표는 box-drawing 경계로 머리글/본문을 나누고 행 1개 = 1청크, 각 행 앞에 머리글(위반행위 / 근거 법조문 / 과태료 금액 1차·2차·3차 이상)과 `(단위: 만원)` 반복
  - 테스트: 별표 2 행별 (위반행위, 근거조문, 금액 3개)이 원문과 일치 — 숫자 할루시네이션 검증의 기준값
- [x] T1.7 행정규칙·용어 청킹 (2026-10-08, 고시 9·용어 6)
- [x] T1.8 메타 (2026-10-08, 조 단위 `article_key`로 통일. 위임 간선 57·참조 88. `에 따른 X` 정의 인용은 위임에서 제외 — DESIGN §3.4): `refs`, `delegated`, `delegates_to`/`delegated_from`, `citation`, `priority` + `delegation_graph.json`
- [x] T1.9 `tests/test_chunker.py` (2026-10-08, 전체 53 passed. chunk-inspector 치명 2·중요 9건 → 수정 후 회귀 테스트로 고정) (기대값은 `/law-structure`), 청크 품질 점검 (@chunk-inspector)
- [x] T1.10 `vectorstore.py` (2026-10-08, `ai_basic_law` 236포인트 = law 108·decree 87·annex 26·admrul 9·term 6, 임베딩 캐시): 컬렉션·payload index·upsert·`--rebuild`·`--sources` (/reindex)
- [x] T1.11 비교용 naive 청커 (2026-10-08, 50청크, `covers`로 걸친 조 기록)(법률 조문 텍스트 연결 후 고정 500자) → `ai_basic_law_naive`

**DoD:** 테스트 통과 + 원천별 포인트 수 확인 + chunk-inspector 치명 이슈 0 + 위임 그래프에 법 제33조 → 시행령 연결이 있음(시행령에 해당 조가 있다면)

## Phase 2. Golden Set + Baseline (1일) ← 기법 개발 전에 확정
- [x] T2.1 골든셋 45문항 (@golden-set-builder), 유형 분포는 DESIGN §7.2. 시행령·별표 문항은 실제 수집된 조문 기준
- [x] T2.2 직접 검수: gold가 정말 정답인지 원문 대조, dev 33 / test 12
- [x] T2.3 `retriever.py` dense + `RetrievalConfig` 골격 (sources 필터 포함)
- [x] T2.4 `eval/evaluate.py`: Hit@K, Recall@K, Full-Recall@5, MRR, 유형별 집계, 결과 JSON(+usage), `--limit`, `--answer` 전 예산 가드(DESIGN §9.5)
- [x] T2.5 E0~E2 실행·기록 (/run-eval) (2026-10-08, 커밋 43c55ac 기준으로 체크 갱신)
- [ ] T2.6 실패 분석 (@retrieval-analyst) → 기법 우선순위 결정

**DoD:** EXPERIMENTS.md에 E0~E2 + 실패 유형 분석

## Phase 3. Advanced Retrieval (2.5일)
각 항목은 `/add-retrieval-technique` 절차로 진행
- [x] T3.1 BM25(kiwi) + RRF → E3 (2026-10-08, 채택: Cand-R@20 +0.086)
- [ ] T3.2 Reranker → E4 (CPU 지연 측정) — 코드·단위테스트 완료(2026-10-08, `rag/reranker.py`, 프리셋 `E4_rerank`·`E4_rerank_parent`). **로컬에서 평가 실행·기록 남음** (클라우드 세션은 API 키·Qdrant·HF 모델 다운로드 불가)
- [ ] T3.3 Router (법/시행령/별표 번호) → E5 — 코드·테스트 완료(2026-10-08, `rag/router.py`, `rag/chunk_store.py`, 프리셋 `E5_router`). 평가 로컬 대기
- [ ] T3.4 Multi-Query vs Term expansion → E6 (둘 다 해보고 비용 대비 효과 비교) — 코드·테스트 완료(2026-10-08, `rag/query_expansion.py`, `data/term_synonyms.yaml`, `common/cache.py`·`common/usage.py` 신설, 프리셋 `E6_term`·`E6_multi_query`). 평가 로컬 대기
- [ ] T3.5 Ref expansion + Small-to-Big → E7 — 코드·테스트 완료(2026-10-08, 프리셋 `E7_ref`·`E7_small_to_big`). 평가 로컬 대기
- [ ] T3.6 원천 추가만 (law+decree+annex) → E8 — 프리셋 `E8_sources` + 대조군 `E8_sources_k8`(top_k=8, E9와 결과 개수 맞춤). 평가 로컬 대기
- [ ] T3.7 **Delegation expansion** → E9 — 코드·테스트 완료(2026-10-08, 위임 체인 법→영→별표 추적, 프리셋 `E9_delegation`). 평가 로컬 대기
- [ ] T3.8 보조 원천 (admrul, term, expc) → E10, priority_boost 조정 — 프리셋 `E10_aux`(admrul·term, expc 미수집) / `E10_aux_boost`(0.002). 평가 로컬 대기
- [ ] T3.9 서비스 프리셋 확정 (`configs.py`) — 검색 지표로 후보 3~4개로 좁힌 뒤 **그 후보만** 답변 평가(`--answer`)

**DoD:** 기법별 채택/기각 사유가 수치와 함께 EXPERIMENTS.md에 있음, E8 vs E9 비교 완료

## Phase 4. Grounded Answer (1일)
- [ ] T4.1 `rag/prompts.py` (DESIGN §5.1, 원천 우선순위·citation 형식)
- [ ] T4.2 `pipeline.py`: retrieve → context → LLM → 인용·숫자 후검증 → 응답
- [ ] T4.3 위임·별표·범위 밖 질문 처리 확인
- [ ] T4.4 답변 점검 (@grounding-reviewer)

**DoD:** delegation·annex·out_of_scope 문항 올바르게 처리, 숫자 불일치 warnings 0

## Phase 5. API (0.5일)
- [ ] T5.1 `app/main.py`: `POST /ask`, `GET /health`, lifespan 로딩, Pydantic 스키마 (`source_type`, `citation`, `data_snapshot`)
- [ ] T5.2 `debug` 옵션 (후보·단계별 점수·added_by·warnings)
- [ ] T5.3 `tests/test_api.py`, 스모크 (/api-smoke)

**DoD:** `/docs`에서 RFP 예시 질문 정상 응답, 테스트 통과

## Phase 6. 최종 평가 & 발표 (1일)
- [ ] T6.1 test split으로 최종 평가 (retrieval + answer judge) — 실행 전 `common.usage --summary`로 잔여 예산 확인
- [ ] T6.1b 비용 결과 정리: 기법별 토큰·크레딧, 캐시 절감량 (발표 자료용)
- [ ] T6.2 Ablation 표, 유형별 개선 그래프, 위임 그래프 시각화
- [ ] T6.3 Before/After 데모 3개 (구조 청킹 / Hybrid / Delegation expansion)
- [ ] T6.4 README (실행 방법, 데이터 원천·snapshot, 아키텍처, 결과, 한계)

---

## 로컬 실행 대기 (.env·Qdrant·HF 모델 필요)
클라우드 세션(2026-10-08)에는 `.env`(API 키)·임베딩 캐시·Qdrant 데이터가 없고 HuggingFace가 막혀 있어
코드·단위테스트까지만 하고 아래 실행은 로컬로 미뤘다. 위에서부터 순서대로 실행하고 결과를 EXPERIMENTS.md에 기록(`/run-eval`).

1. 사전 점검: `docker compose -f docker-qdrant/docker-compose.yaml up -d` → `uv run python -m eval.evaluate --validate-only`
2. **T3.2 E4** `uv run python -m eval.evaluate --config E4_rerank,E4_rerank_parent` (첫 실행 시 bge-reranker-v2-m3 약 2GB 다운로드)
   - `RUN_RERANK_MODEL=1 uv run pytest -q tests/test_retriever.py`
   - CPU p50 지연을 E3(5ms)와 비교. `embed_text` vs `parent_text` 중 나은 쪽 채택. **기각 시** `rag/config.py`의 E5 이후 프리셋 기반을 `E4`→`E3`로 바꿀 것
3. **T3.3 E5** `uv run python -m eval.evaluate --config E5_router` — article_lookup(q007·q009) Hit@1 확인. q008·q011은 시행령이라 sources=law에선 구조적 불가(→E8)
4. **T3.4 E6** 먼저 `.env`에 `CREDIT_PER_1K_INPUT/OUTPUT/EMBED` 단가 기록 → `uv run python -m common.usage --summary`
   - `uv run python -m eval.evaluate --config E6_term` (LLM 없음)
   - `uv run python -m eval.evaluate --config E6_multi_query --limit 5`로 비용 확인 후 전체 dev(33문항 × LLM 1회, max_tokens 200, 이후 캐시)
   - 결과 JSON의 `usage`·`p50_query_prep_ms`로 비용·지연 비교 → 채택안을 `rag/config.py`의 `E6 = ...`에 반영
   - Term 사전(`data/term_synonyms.yaml`)은 dev 문항을 보고 고친 게 아니라 일반 표현으로 작성함. 사전 수정 시 test split에서도 효과 확인 필요
5. **T3.5 E7** `--config E7_ref,E7_small_to_big` — cross_ref 유형의 `full_recall@ctx`, small-to-big의 Hit@5(조 중복 제거 효과) 확인 → `E7 = ...` 결정
6. **T3.6~T3.7 E8·E9** `--config E8_sources,E8_sources_k8,E9_delegation` — **발표 하이라이트**: delegation·annex 유형의 `full_recall@ctx`를 E8(5개) / E8_k8(8개, 개수 통제) / E9로 비교
7. **T3.8 E10** `--config E10_aux,E10_aux_boost` — definition(term gold)·q035(admrul gold)와 노이즈 비교, priority_boost 채택 여부
8. **T3.9** 위 결과로 `rag/config.py`의 `full` 프리셋 확정(현재 잠정 = E10_aux)

---

## 백로그
- [ ] 법령 개정 감지: 저장된 MST와 최신 목록 비교 → 변경 시 재수집 알림
- [ ] Qdrant 네이티브 sparse vector로 하이브리드 이전
- [ ] "우리 서비스가 고영향 AI인가?" 자가진단 엔드포인트
