# 설계 문서 — AI 기본법 근거 기반 QA 백엔드

> 기준 문서: `RAG Mini Project RFP`, 템플릿 `gg1th_rag_mini_pjt_template`
> 1인 프로젝트. 이 문서가 스키마·인터페이스의 단일 기준(Single Source of Truth)이다.
> 데이터 원천: **국가법령정보 공동활용 Open API만 사용** (PDF는 사용하지 않음)

---

## 0. 데이터 원천 결정

| 항목 | 결정 |
|---|---|
| 원천 | 현행법령(법률·시행령), 행정규칙, 법령해석례, 법령용어, 별표·서식 — 모두 Open API |
| 구조 파싱 | API 응답 계층(조문단위→항→호→목)을 그대로 사용, 정규식은 참조·위임 탐지에만 |
| 전처리 | 응답 정규화(단건 dict vs 리스트, 중첩 리스트, 전문 행 처리) |
| 위임 조항 | 법률 조 → 시행령 조·별표 연결로 실제 답변 |
| Docling | **별표 HTML → Markdown 표 변환**에 사용 (RFP의 Docling 요구 충족) |

---

## 1. 목표와 차별화 전략

| RFP 요구 | 이 프로젝트의 구현 | 차별화 포인트 |
|---|---|---|
| 구조 기반 청킹 | API의 조문 계층을 payload로 보존, 원천별 청킹 규칙 | 고정 길이 청킹(E0) 대비 구조 청킹 효과를 수치로 |
| Advanced RAG | 플래그 기반 파이프라인 + **위임 확장(Delegation Expansion)** | 법률 ↔ 시행령 ↔ 고시를 잇는 계층형 검색 |
| Grounded Answer | 원천 우선순위(법률>시행령>고시>해석례) + 인용 후검증 | 출처 종류를 구분한 인용 `[법 제31조②]`, `[영 제22조]`, `[영 별표 1]` |
| Evaluation | 유형별 Golden Set + Ablation | "위임 확장으로 delegation 유형 정답률 0 → N" 같은 극적 개선을 수치로 |

발표 핵심 메시지: **"법률만으로는 답할 수 없는 질문을, 법령 체계를 따라가 답하게 만들었다."**

---

## 2. 데이터 원천 (Open API)

### 2.1 공통
- Base: `http://www.law.go.kr/DRF/lawSearch.do` (목록), `http://www.law.go.kr/DRF/lawService.do` (본문)
- 인증: `OC` = `.env`의 `LAW_OC` (코드·문서·커밋에 값 하드코딩 금지 — 훅으로 차단)
- 사용할 API별로 open.law.go.kr에서 **활용 신청·승인**이 돼 있어야 한다. 인증 실패 시 응답이 JSON이 아니라 HTML·오류 메시지로 오는 경우가 있어 Content-Type·본문 검사 필수.
- `type=JSON` 기본. (JSON 미지원 target은 XML/HTML)
- 호출 간 0.5초 간격, 타임아웃 30초, 재시도 3회(지수 백오프).

### 2.2 사용 API

| 원천 (`source_type`) | 목록 조회 | 본문 조회 | 용도 | 우선순위 |
|---|---|---|---|---|
| `law` 법률 | `lawSearch target=law query=인공지능 발전과 신뢰 기반 조성 등에 관한 기본법` | `lawService target=law MST={법령일련번호}` | 핵심 근거 | 1 (필수) |
| `decree` 시행령 | 같은 방식, query에 `... 시행령` | 같음 | 위임 사항 세부 | 1 (필수) |
| `admrul` 행정규칙 | `lawSearch target=admrul query=인공지능` → 과기정통부 소관만 allowlist | `lawService target=admrul ID={행정규칙일련번호}` | 고시·가이드라인 | 2 |
| `annex` 별표·서식 | `lawSearch target=licbyl query={법령명}` | 목록의 **HTML 링크**를 받아 Docling으로 변환 | 과태료 부과기준 등 | 2 |
| `term` 법령용어 | `lawSearch target=lstrm query={용어}` | `lawService target=lstrm query={용어}` | 용어 정의 보강, 질의 확장 사전 | 3 (선택) |
| `expc` 법령해석례 | `lawSearch target=expc query=인공지능` | `lawService target=expc ID={해석례일련번호}` | 해석 사례 | 3 (선택) |

- 무엇을 가져올지는 `data/sources.yaml`에 **명시적으로 고정**한다 (검색어 결과가 바뀌어도 재현 가능하게).
  ```yaml
  snapshot_date: 2026-10-xx
  law:     [{name: "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법", mst: null}]   # 최초 실행 시 mst 채움
  decree:  [{name: "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법 시행령", mst: null}]
  admrul:  []   # T1.2에서 목록 확인 후 수동 선택 (이름, ID)
  annex:   []   # 시행령 별표 중 선택 (예: 과태료 부과기준)
  term:    [인공지능, 인공지능시스템, 고영향 인공지능, 생성형 인공지능, 인공지능사업자, 이용자, 영향받는 자, 학습용데이터]
  expc:    {query: 인공지능, max: 20}
  ```
  `mst`/`id`가 비어 있으면 목록 API로 찾아 채우고, 사용자 확인 후 파일에 저장.

### 2.3 원본 캐시 (재현성·호출량 절약)
```
data/raw/{source_type}/{id}.json      # API 응답 원문 그대로
data/raw/annex/{id}.html              # 별표 HTML 원문
data/raw/manifest.json                # 호출 URL(OC 제거), 시각, 응답 크기, sha256
```
- 파이프라인은 기본적으로 **캐시를 읽는다.** API 재호출은 `--refresh`일 때만.
- `tests/fixtures/`에는 법률 1개 응답을 축약 저장 → 파서 단위테스트가 네트워크 없이 돈다.

### 2.4 응답 구조 (현행법령 본문, 예상 필드 — T0.7에서 실제 응답으로 확정)
```
법령
├── 기본정보: 법령ID, 법령명_한글, 공포일자, 공포번호, 시행일자, 소관부처, 법종구분 ...
├── 조문
│   └── 조문단위[]: 조문키, 조문번호, 조문가지번호, 조문여부(조문|전문), 조문제목, 조문시행일자, 조문내용,
│       └── 항[]: 항번호(①), 항내용
│           └── 호[]: 호번호(1.), 호내용
│               └── 목[]: 목번호(가.), 목내용
├── 부칙: 부칙단위[] (부칙공포일자, 부칙내용)
└── 별표: 별표단위[] (별표번호, 별표제목, 별표서식파일링크 ...)
```
정규화 규칙 (`common/law_api.py`)
- **단건이면 dict, 여러 건이면 list**로 오는 필드가 있다 → `as_list(x)`로 항상 리스트화
- `조문여부 == "전문"`은 장·절 제목 행 → 청크가 아니라 이후 조문들의 `chapter/section` 컨텍스트로 사용
- 내용 필드가 문자열 대신 문자열 리스트로 오는 경우 → `"\n".join`
- 항이 하나뿐인 조는 `항` 없이 `조문내용`에 본문이 있음
- 항·호 내용에 `①`, `1.` 기호가 이미 포함됨 → 중복 접두 금지

---

## 3. 데이터 처리 (Offline)

### 3.1 모듈
| 파일 | 역할 |
|---|---|
| `common/law_api.py` | `LawApiClient`: search/service 호출, 재시도, OC 주입, 캐시 read/write, `as_list` 등 정규화 유틸 |
| `rag/loader.py` | `sources.yaml` → 원천별 원본 로딩(캐시 우선) → `LawDocument` 표준 객체로 변환 |
| `rag/chunker.py` | 원천별 청킹 규칙 → `Chunk[]`, `data/processed/chunks.jsonl` |
| `rag/vectorstore.py` | 임베딩·Qdrant 적재 |

```python
@dataclass
class LawDocument:          # loader 출력: 원천 무관 공통 형태
    source_type: str        # law | decree | admrul | annex | term | expc
    doc_id: str             # MST / ID
    title: str              # 법령명·행정규칙명·별표제목·용어·안건명
    meta: dict              # 시행일자, 소관부처, 공포번호 ...
    units: list[dict]       # law/decree: 조문단위 정규화 리스트, 그 외: 원천별 본문 블록
```

### 3.2 원천별 청킹 규칙
| 원천 | 단위 | embed_text 헤더 | 비고 |
|---|---|---|---|
| law / decree | 조 (≤700자) / 항 (>700자) | `[법률|시행령 > 제4장 ...] 제31조(인공지능 투명성 확보 의무) ②` | 법 제2조는 **호 단위**(4호는 가~카목 포함) |
| 부칙 | 부칙 1건 = 1청크 | `[법률 부칙 <제20676호>]` | 시행일 질문 |
| admrul | 조 단위 (조문내용 문자열에서 `제N조(` 로 분할) | `[고시: {행정규칙명}] 제N조(...)` | 조가 없는 가이드라인은 제목(Ⅰ., 1.) 단위 |
| annex | 표의 **행 그룹** 단위 + 표 머리글 반복 | `[시행령 별표 1 과태료의 부과기준] 위반행위 / 근거 법조문 / 금액` | Docling `HTML → markdown` 후 표 파싱 |
| term | 용어 1개 = 1청크 | `[법령용어] 고영향 인공지능` | 질의 확장 사전으로도 사용 |
| expc | 해석례 1건: `질의요지+회답` 1청크, `이유` 별도 청크 | `[법령해석례 {해석기관} {해석일자}] {안건명}` | |

### 3.3 Chunk 스키마 (Qdrant payload)
```json
{
  "chunk_id": "law:a31-p2",
  "source_type": "law",
  "doc_id": "<MST>",
  "doc_title": "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법",
  "doc_short": "법",
  "chapter": "제4장 인공지능윤리 및 신뢰성 확보",
  "section": null,
  "article_no": 31,
  "article_sub": 0,
  "article": "제31조",
  "article_title": "인공지능 투명성 확보 의무",
  "paragraph": "②",
  "item": null,
  "chunk_type": "paragraph",
  "text": "② 인공지능사업자는 생성형 인공지능 ...",
  "embed_text": "[법률 > 제4장 인공지능윤리 및 신뢰성 확보] 제31조(인공지능 투명성 확보 의무) ② ...",
  "parent_text": "제31조 전체",
  "refs": ["law:31"],
  "delegated": false,
  "delegates_to": [],
  "delegated_from": [],
  "effective_date": "2026-01-22",
  "priority": 1,
  "citation": "법 제31조 제2항"
}
```
- `chunk_id` = `{source_type}:{로컬ID}` (규칙은 `.claude/skills/law-structure/SKILL.md`)
- `doc_short`: 법 / 영(시행령) / 고시 / 별표 / 용어 / 해석
- `citation`: 답변·sources에 그대로 쓰는 사람이 읽는 표기
- `priority`: 1 법률·시행령, 2 고시·별표, 3 용어·해석례

### 3.4 위임 그래프 (v2 핵심)
1. 법률 청크: `대통령령으로 정한다|고시` 패턴 → `delegated=true`
2. 시행령 청크: `법 제(\d+)조(?:제(\d+)항)?에 따라|에서 "대통령령으로 정하는` 패턴 → `delegated_from=["law:33-p4"]`
3. 역방향으로 법률 청크의 `delegates_to=["decree:a20", ...]` 채움
4. 별표: 시행령 조문의 `별표 \d+` 언급 → `refs`에 `annex:{번호}` 추가
5. 그래프 전체를 `data/processed/delegation_graph.json`으로 저장 (발표용 시각화 재료)

### 3.5 vectorstore.py
- 단일 컬렉션 `ai_basic_law`, 원천은 payload `source_type`으로 구분 (필터·ablation이 쉬움)
- vector `dense` 1536 (text-embedding-3-small, Cosine)
- payload index: `source_type`, `article_no`, `chunk_type`, `doc_short`(keyword), `delegated`(bool), `priority`(integer)
- Point ID: `uuid5(NAMESPACE_URL, chunk_id)`
- `--sources law,decree` 옵션으로 적재 원천 선택 → 실험 E-SRC

---

## 4. 검색 (Online)

### 4.1 RetrievalConfig
```python
@dataclass
class RetrievalConfig:
    name: str = "baseline"
    sources: tuple[str, ...] = ("law",)      # 검색 대상 원천
    top_k: int = 5
    candidate_k: int = 20
    use_router: bool = False                # "제N조", "시행령 제N조", "별표 N" 직접 조회
    use_bm25: bool = False
    rrf_k: int = 60
    use_multi_query: bool = False
    n_queries: int = 3
    use_term_expansion: bool = False        # 법령용어 사전으로 질의 확장
    use_rerank: bool = False
    reranker: str = "BAAI/bge-reranker-v2-m3"
    use_ref_expansion: bool = False         # 같은 법 내 참조 조문
    use_delegation_expansion: bool = False  # 법률 ↔ 시행령 ↔ 별표/고시
    max_expansion: int = 3
    priority_boost: float = 0.0             # 동점 근처에서 법률·시행령 우선
    small_to_big: bool = True
```

### 4.2 단계
| 단계 | 구현 | 노트 |
|---|---|---|
| Router | `(시행령\s*)?제\s*(\d+)\s*조(의\s*\d+)?`, `별표\s*(\d+)` → payload filter 직접 조회 | "시행령" 언급 시 `source_type=decree` |
| Term expansion | 질문에 법령용어 사전의 동의어·일상어가 있으면 정식 용어를 덧붙임 | Multi-Query보다 싸고 결정적 |
| Dense | Qdrant `query_points(filter=source_type in cfg.sources)` | |
| BM25 | kiwipiepy 형태소 + rank_bm25 (`chunks.jsonl` 기반) | |
| RRF | `Σ 1/(k+rank)` | |
| Multi-Query | LLM이 법률 용어로 3개 재작성 | 일상어 질문 |
| Rerank | CrossEncoder(bge-reranker-v2-m3), 입력 `(질문, embed_text)` | |
| Ref expansion | 상위 청크 `refs` (같은 법 내) | 과태료↔의무 |
| **Delegation expansion** | 상위 청크가 `delegated`면 `delegates_to` 청크 추가, 시행령 청크면 `delegated_from` 법률 조 추가 | "세부 기준은?" 질문 |
| Small-to-Big | 같은 조 청크 병합, `parent_text` 사용 | |

### 4.3 retriever.py 인터페이스
```python
@dataclass
class RetrievedChunk:
    chunk_id: str; source_type: str; citation: str; doc_title: str
    text: str; parent_text: str; score: float
    stage_scores: dict[str, float]; added_by: str   # "search" | "router" | "ref" | "delegation"

def retrieve(question: str, cfg: RetrievalConfig) -> list[RetrievedChunk]: ...
```

---

## 5. 답변 생성 (pipeline.py)

### 5.1 시스템 프롬프트 골자
```
너는 「인공지능기본법」과 그 하위 법령을 안내하는 도우미다. 독자는 법을 잘 모르는 일반인이다.
규칙:
1. 아래 <근거> 안의 내용만 사용한다. 근거에 없는 내용은 추측하지 않는다.
2. 각 문장 끝에 근거의 citation을 [법 제31조 제2항], [영 제22조], [영 별표 1] 형식으로 단다.
3. 근거의 효력 순서는 법률 > 시행령 > 고시 > 법령해석례·법령용어다. 충돌하면 상위 근거를 따르고 그 사실을 밝힌다.
4. 법령해석례는 "해석 사례"로, 법령용어는 "참고 정의"로 구분해 표현한다.
5. 위임 조항인데 하위 법령 근거가 <근거>에 없으면 "세부 사항은 하위 법령에 위임되어 있으나 제공된 자료에서 확인되지 않습니다"라고 쓴다.
6. 근거가 없으면 정확히 "제공된 AI 기본법 관련 법령에서 확인할 수 없습니다."라고 답한다.
형식: ① 한 줄 요약 ② 쉬운 설명(3~5문장) ③ 근거 목록
```

### 5.2 후처리 (Hallucination guard)
1. 답변의 `[...]` 인용 추출 → 검색 결과 `citation` 집합과 대조
2. 없는 인용 → `warnings` 기록 후 제거
3. 인용 0개 + 거절 문구 아님 → `grounded=false`
4. 금액·기간 등 숫자가 답변에 있는데 근거 텍스트에 없으면 → `warnings` (과태료 금액 할루시네이션 방지)

### 5.3 LLM 설정
temperature 0, max_tokens 1024

---

## 6. API (app/main.py)

### `POST /ask`
Request
```json
{ "question": "AI 서비스라고 미리 알리지 않으면 과태료가 얼마인가요?", "debug": false }
```
Response (RFP 스키마 + 확장 필드)
```json
{
  "answer": "생성형 AI 서비스임을 사전에 고지하지 않으면 3천만원 이하의 과태료 대상입니다 [법 제43조 제1항]. 구체적인 금액은 시행령 별표의 부과기준에 따릅니다 [영 별표 1].",
  "sources": [
    { "article": "제43조", "source_type": "law", "citation": "법 제43조 제1항",
      "doc_title": "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법", "content": "...", "score": 0.88 },
    { "article": "별표 1", "source_type": "annex", "citation": "영 별표 1",
      "doc_title": "... 시행령", "content": "| 위반행위 | 근거 법조문 | 금액 | ...", "score": 0.81 }
  ],
  "notice": "AI가 생성한 답변입니다. 법률 자문이 아니며 원문을 확인하세요.",
  "grounded": true,
  "data_snapshot": "2026-10-xx",
  "debug": null
}
```
- `data_snapshot`: 법령 데이터 수집 일자 (`sources.yaml`). 현행 법령이 바뀔 수 있으므로 명시.
- `GET /health`: Qdrant 상태, 원천별 포인트 수, snapshot 일자
- 서비스는 **런타임에 law.go.kr을 호출하지 않는다** (지연·호출 제한·장애 격리). 갱신은 오프라인 `--refresh` 후 재적재.

---

## 7. 평가 (eval/)

### 7.1 golden_set.jsonl 스키마
```json
{"id":"q031","type":"delegation","question":"고영향 인공지능에 해당하는지 확인받는 절차는 구체적으로 어떻게 되나요?",
 "gold":["law:제33조","decree:제?조"],
 "reference_answer":"...","must_include":["확인"],"should_refuse":false,"split":"dev"}
```
- `gold` 형식: `{source_type}:{참조}` — `law:제31조`, `decree:제22조`, `annex:별표1`, `admrul:{행정규칙명}`, `term:{용어}`, `expc:{일련번호}`
- 하위 호환: 접두어 없는 `제31조`는 `law:제31조`로 취급

### 7.2 질문 유형 (총 45문항 목표)
| type | 수 | 예시 | 주로 검증하는 기법 |
|---|---|---|---|
| definition | 6 | 생성형 인공지능의 정의는? | 호 단위 청킹, term |
| article_lookup | 5 | 법 제33조 / 시행령 제5조 내용은? | Router |
| colloquial | 8 | AI로 만든 그림 올릴 때 뭐 표시해야 해? | Multi-Query, term expansion, BM25 |
| obligation | 6 | 고영향 AI 사업자가 해야 할 조치는? | Hybrid, Rerank |
| cross_ref | 4 | 고지 안 하면 어떤 제재가? | Ref expansion |
| delegation | 7 | 고영향 AI 확인 절차의 세부 사항은? | **Delegation expansion** |
| annex | 4 | 국내대리인 미지정 시 과태료 금액은? | 별표 청킹, Delegation expansion |
| out_of_scope | 5 | 개인정보보호법상 과징금은? | 거절 |

- dev 33 / test 12. 튜닝은 dev에서만.
- 시행령·별표·고시 문항은 **T1 수집 결과를 보고** 작성 (실제 존재하는 조문만 gold로).

### 7.3 지표
| 대상 | 지표 | 계산 |
|---|---|---|
| Retrieval | Hit@1/3/5, Recall@5, MRR | gold 항목 단위. `should_refuse` 제외. delegation·cross_ref는 **모든 gold 포함 여부(Full-Recall@5)** 도 별도 |
| Answer | 정답성·관련성·근거충실성 (1~5) | LLM-as-judge (`eval/judge_prompt.md`) |
| Answer | Hallucination rate, 숫자 불일치율 | 후검증 warnings |
| Answer | Refusal accuracy | |
| 운영 | p50 latency | |

---

## 8. 실험 계획 (Ablation)

| ID | 설정 | 가설 |
|---|---|---|
| E0 | 법률만, 고정 500자 청킹 + dense | 기준선 |
| E1 | 법률만, 구조 청킹(API 계층) + dense | 구조 청킹 효과 |
| E2 | E1 + contextual header | 헤더 prefix 효과 |
| E3 | E2 + BM25 + RRF | 법률 용어 정확 일치 |
| E4 | E3 + Rerank | 순위 정밀도 |
| E5 | E4 + Router | article_lookup |
| E6 | E5 + Multi-Query (또는 Term expansion) | colloquial, 비용 대비 효과 |
| E7 | E6 + Ref expansion | cross_ref |
| E8 | E7 + sources=law,decree,annex (확장 없이 단순 추가) | 원천만 늘리면? (노이즈 증가 가능) |
| E9 | E8 + Delegation expansion | **delegation·annex 유형** |
| E10 | E9 + admrul/term/expc 추가 | 보조 원천의 효과·노이즈 |

E8 vs E9 비교가 발표의 하이라이트: "원천을 넣기만 하면 안 되고, 법령 체계를 따라 연결해야 한다."

---

## 9. 비용·토큰 예산

### 9.1 예산
- LLM 게이트웨이 크레딧: 총 30,000, 설계 시점 사용 약 4,000 → **잔여 약 26,000** (`LLM_BUDGET_CREDITS`)
- 크레딧↔토큰 단가는 T0.8에서 실측해 `.env`에 기록 (`CREDIT_PER_1K_INPUT`, `CREDIT_PER_1K_OUTPUT`, `CREDIT_PER_1K_EMBED`)

| 용도 | 배분 | 비고 |
|---|---|---|
| 개발·디버깅 (pipeline, /ask 수동 테스트) | 20% | LLM 캐시로 반복 호출 최소화 |
| 임베딩 (재적재, naive 컬렉션) | 10% | 임베딩 캐시로 바뀐 청크만 |
| 검색 평가 (Multi-Query 재작성 등) | 5% | 검색 지표 평가는 LLM 거의 안 씀 |
| 답변 평가 (생성 + judge) | 45% | **최종 후보 3~4개 + test 1회만** |
| 예비 | 20% | 프롬프트 수정 후 재평가 등 |

### 9.2 사용량 추정 (가정치, T0.8 이후 실측으로 교체)
| 작업 | 1회 규모 |
|---|---|
| 임베딩 전체 재적재 | 약 10만 토큰 (청크 200~300개) |
| 검색 지표 평가 | 쿼리 임베딩만, Multi-Query 켜면 LLM 약 1.5만 토큰 |
| 답변 생성 (45문항) | 약 23만 토큰 (문항당 입력 4.5k + 출력 0.4k) |
| judge 채점 (45문항) | 약 10만 토큰 |
| 답변+judge 1회 | 약 30만 토큰 |
E0~E10 전부 답변 평가 시 약 350만 토큰 → 하지 않는다. 검색 지표로 후보를 좁힌 뒤 답변 평가.

### 9.3 캐시
| 캐시 | 위치 | 키 | 규칙 |
|---|---|---|---|
| 임베딩 | `data/cache/embeddings.sqlite` | `sha256(embedding_model + embed_text)` | 재적재 시 바뀐 청크만 API 호출. 쿼리 임베딩도 캐시 |
| LLM 응답 | `data/cache/llm.sqlite` | `sha256(model + temperature + max_tokens + messages)` | temperature 0 호출만 캐시. 답변 생성·Multi-Query·judge 공통. `--no-cache`로 우회 |
| Open API 원문 | `data/raw/` | 문서 ID | §2.3 |
- 같은 config·프롬프트로 평가를 다시 돌리면 LLM 비용 0
- 프롬프트를 바꾸면 키가 바뀌어 자연히 재호출 (의도된 동작)
- 캐시 파일은 git 제외, 삭제는 사용자만

### 9.4 사용량 기록
- `common/usage.py`: `UsageTracker`
  - LLM: LangChain `AIMessage.usage_metadata`(input/output 토큰) 누적, 캐시 hit 수 별도 집계
  - 임베딩: 응답에 사용량이 없으면 `tiktoken`으로 추정
  - `est_credits = Σ tokens/1000 × CREDIT_PER_1K_*`
- `eval/results/*.json`에 `usage {llm_in, llm_out, embed, cache_hits, est_credits}` 포함
- **누적 장부** `eval/usage_ledger.jsonl`: 평가·재적재·수동 실행마다 1줄 append (`ts, task, config, tokens, est_credits`)
- `uv run python -m common.usage --summary` → 누적 사용량, 잔여 예산, 용도별 비율
- `/ask`의 `debug` 응답에 해당 요청의 토큰 사용량 포함

### 9.5 예산 가드
- `eval.evaluate --answer` 실행 전 **예상 크레딧**(문항 수 × 문항당 평균, 캐시 hit 제외)과 잔여 예산을 출력하고 확인을 받는다. `--yes`로 생략
- 예상치가 잔여 예산의 20%를 넘으면 중단하고 사용자에게 보고
- 호출 상한: 답변 `max_tokens=1024`, Multi-Query 200, judge 300
- 컨텍스트 상한: LLM에 넣는 근거 합계 6k 토큰 (확장으로 붙은 청크부터 잘라냄)
- 개발 중 수동 테스트는 dev 문항 5개짜리 `--limit 5`로

---

## 10. 의존성
```bash
uv add httpx tenacity pyyaml beautifulsoup4 lxml docling kiwipiepy rank-bm25 sentence-transformers tiktoken
uv add --dev ruff pytest respx
```
`.env.example`
```
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=gpt-5.4-mini
EMBEDDING_MODEL=text-embedding-3-small
QDRANT_URL=http://localhost:6333
COLLECTION_NAME=ai_basic_law
LAW_OC=
LAW_API_BASE=http://www.law.go.kr/DRF
SERVICE_RETRIEVAL_PRESET=full
JUDGE_MODEL=gpt-5.4-mini
LLM_BUDGET_CREDITS=26000
CREDIT_PER_1K_INPUT=
CREDIT_PER_1K_OUTPUT=
CREDIT_PER_1K_EMBED=
```

## 11. 디렉터리 (템플릿 + 추가분)
```
rag_minipjt/
├── CLAUDE.md
├── docs/ DESIGN.md · TASKS.md · EXPERIMENTS.md
├── .claude/ settings.json · agents/ · skills/ · hooks/
├── data/
│   ├── sources.yaml                 # 수집 대상 고정 (커밋)
│   ├── raw/{law,decree,admrul,annex,term,expc}/   # API 원문 캐시 (커밋 여부는 용량 보고 결정)
│   ├── processed/ chunks.jsonl · delegation_graph.json
│   └── cache/ embeddings.sqlite · llm.sqlite   # git 제외
├── common/ config.py · ai_model.py · qdrant.py · law_api.py(신규) · usage.py(신규) · cache.py(신규)
├── rag/  loader · chunker · vectorstore · retriever · reranker · pipeline · config · prompts
├── app/main.py
├── eval/ golden_set.jsonl · evaluate.py · configs.py · judge_prompt.md · results/ · usage_ledger.jsonl
├── tests/ fixtures/ · test_law_api.py · test_chunker.py · test_retriever.py · test_api.py
└── docker-qdrant/ · notebook/
```
