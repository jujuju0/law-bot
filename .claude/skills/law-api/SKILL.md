---
name: law-api
description: 국가법령정보 공동활용 Open API(law.go.kr DRF) 호출·캐시·응답 정규화 레퍼런스. common/law_api.py나 rag/loader.py를 작성·수정할 때, sources.yaml 대상을 찾을 때, API 응답 구조 문제를 디버깅할 때 사용.
---

# 국가법령정보 Open API 레퍼런스

> 필드명은 공개 자료 기준의 **예상값**이다. 처음 구현할 때 반드시 실제 응답을 `data/raw/`에 저장하고 키를 확인한 뒤, 이 문서의 "확인 결과" 표를 갱신할 것.

## 엔드포인트
```
목록: {LAW_API_BASE}/lawSearch.do?OC={LAW_OC}&target={target}&type=JSON&query={검색어}&display=100&page=1
본문: {LAW_API_BASE}/lawService.do?OC={LAW_OC}&target={target}&type=JSON&{MST|ID|query}=...
```
`LAW_API_BASE` 기본값 `http://www.law.go.kr/DRF`

| 원천 | 목록 target | 본문 호출 | 식별자 (목록 응답에서) |
|---|---|---|---|
| 법률·시행령 | `law` | `target=law&MST=` | 법령일련번호 (MST) |
| 행정규칙 | `admrul` | `target=admrul&ID=` | 행정규칙일련번호 |
| 법령해석례 | `expc` | `target=expc&ID=` | 법령해석례일련번호 |
| 법령용어 | `lstrm` | `target=lstrm&query=용어` | 법령용어명 |
| 별표·서식 | `licbyl` | (본문 API 없음) 목록의 **별표 HTML 링크**를 GET | 별표일련번호 / 링크 필드 |

참고: 특정 조문만 받는 `target=eflawjosub&MST=&efYd=&JO=000200` (JO=조번호 4자리+가지번호 2자리)도 있다. 디버깅용.

## LawApiClient 요구사항 (`common/law_api.py`)
```python
class LawApiClient:
    def search(self, target: str, query: str, **params) -> list[dict]: ...
    def service(self, target: str, **params) -> dict: ...
    def fetch_html(self, url: str) -> str: ...      # 별표
```
- OC는 `common.config.LAW_OC`에서 주입. 없으면 즉시 명확한 에러.
- `httpx` + `tenacity`: 타임아웃 30s, 재시도 3회(지수 백오프), 호출 간 최소 0.5s.
- **응답 검증**: `Content-Type`이 JSON이 아니거나 본문이 `<html`로 시작하면 `LawApiAuthError("OC 오류 또는 해당 API 활용 신청 미승인 가능")`.
- **캐시**: `data/raw/{source_type}/{id}.json` 존재하면 읽고 반환. `refresh=True`일 때만 호출. 저장 시 `manifest.json`에 `{url_without_oc, fetched_at, bytes, sha256}` 추가.
- 로그에 URL을 찍을 때 `OC=` 파라미터 제거 (`redact_oc(url)`).
- 목록 페이징: `totalCnt` 기준으로 page 증가.

## 정규화 유틸 (반드시 사용)
```python
def as_list(x) -> list:          # None→[], dict→[dict], list→list
def as_text(x) -> str:           # str→strip, list[str]→"\n".join, dict→ 내부 텍스트 필드
def article_key(no: str, sub: str | None) -> str   # ("22","2") → "22_2"
```

## 현행법령 본문 응답 (예상 구조)
```
법령
├─ 기본정보 { 법령ID, 법령명_한글, 법종구분, 공포일자, 공포번호, 시행일자, 소관부처 }
├─ 조문 { 조문단위: [ {
│     조문키, 조문번호, 조문가지번호, 조문여부("조문"|"전문"), 조문제목, 조문시행일자, 조문내용,
│     항: [ { 항번호:"①", 항내용, 호: [ { 호번호:"1.", 호내용, 목: [ { 목번호:"가.", 목내용 } ] } ] } ]
│  } ] }
├─ 부칙 { 부칙단위: [ { 부칙공포일자, 부칙공포번호, 부칙내용 } ] }
└─ 별표 { 별표단위: [ { 별표번호, 별표가지번호, 별표구분, 별표제목, 별표서식파일링크, ... } ] }
```
주의
- `조문여부=="전문"` → 장·절 제목 행 (`조문내용` 예: "제4장 인공지능윤리 및 신뢰성 확보"). 청크 만들지 말고 컨텍스트로.
- 항이 1개인 조는 `항`이 없고 `조문내용`에 본문.
- `조문내용`에는 `제31조(인공지능 투명성 확보 의무)` 머리가 포함될 수 있음 → 항 텍스트와 중복 결합 금지.
- 항·호·목이 1개면 list가 아닌 dict → `as_list`.
- 내용 필드가 `[["..."]]` 처럼 중첩 리스트로 오는 사례 → `as_text`가 재귀 평탄화.

## 행정규칙 / 해석례 / 용어 (예상 필드)
- 행정규칙: `행정규칙기본정보{행정규칙명, 행정규칙종류, 발령일자, 소관부처명, 행정규칙일련번호}`, `조문내용`(문자열 리스트), `부칙`, `별표`
- 해석례: `안건명, 법령해석례일련번호, 해석기관명, 해석일자, 질의요지, 회답, 이유`
- 법령용어: `법령용어명, 법령용어정의, 출처`(여러 법령에서 정의된 경우 복수)
- 별표 목록(licbyl): `별표명, 관련법령명, 별표번호, 별표종류, 별표서식파일링크, 별표서식PDF파일링크, 별표법령상세링크` → HTML 상세 링크 사용

## 별표 HTML 처리
1. `fetch_html(link)` → `data/raw/annex/{id}.html`
2. Docling `DocumentConverter().convert(path)` (HTML 입력) → markdown. 실패 시 `bs4` + `pandas.read_html` 대체.
3. 표 머리글(위반행위 | 근거 법조문 | 과태료 금액 …)을 행 그룹마다 반복해 청크.
4. 각주(비고, 일반기준)는 별도 청크 `chunk_type=annex_note`.

## 수집 대상 찾기 절차 (sources.yaml 채우기)
1. `search("law", "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법")` → 법령명·법종구분·MST 표로 보여주기 (법률/시행령/시행규칙 구분)
2. `search("admrul", "인공지능")` → 소관부처가 과학기술정보통신부인 것만 표로 → **사용자가 고른 것만** sources.yaml에
3. `search("licbyl", "<시행령 이름>")` → 별표 목록 → 사용자 선택
4. `search("expc", "인공지능")` → 건수 보고 (0건일 수 있음 — 그 사실을 기록)
5. sources.yaml에 `snapshot_date` 기록

## 확인 결과 (T0.7에서 채울 것)
| 항목 | 예상 | 실제 |
|---|---|---|
| type=JSON 지원 (law/admrul/expc/lstrm/licbyl) | 지원 | |
| 법령 본문 루트 키 | `법령` | |
| 단건 항이 dict로 오는가 | 예 | |
| 별표 HTML 링크 필드명 | `별표법령상세링크` 등 | |
| 인증 실패 시 응답 | HTML | |
