---
name: api-smoke
description: FastAPI 서버를 띄우고 POST /ask, GET /health를 대표 질문으로 호출해 RFP 응답 스키마와 근거 규칙을 점검한다. app/main.py나 pipeline.py 수정 후, 발표 전 리허설에 사용.
---

# API 스모크 테스트

## 1. 서버
- 이미 떠 있는지: `curl -s localhost:8000/health` (원천별 포인트 수, snapshot 확인)
- 아니면 `uv run uvicorn app.main:app --port 8000 > /tmp/uvicorn.log 2>&1 &` → 최대 30초 대기

## 2. 질문 (유형별 1개)
| 유형 | 질문 | 기대 |
|---|---|---|
| RFP 예시 | 고영향 인공지능이란 무엇인가요? | `법 제2조 제4호` |
| 조문 번호 | 제31조 내용 알려줘 | 1순위 `법 제31조` |
| 일상어 | AI로 만든 이미지를 올릴 때 따로 표시해야 하나요? | `법 제31조` ②/③ |
| 교차참조 | AI 서비스라고 미리 알리지 않으면 어떤 제재가 있나요? | `법 제31조` + `법 제43조` |
| 위임 | 고영향 인공지능 확인 절차의 세부 사항은? | `법 제33조` + 시행령 해당 조 (없으면 "하위 법령에서 확인되지 않음") |
| 별표 | 국내대리인을 지정하지 않으면 과태료가 얼마인가요? | `법 제43조` + `영 별표` (금액은 근거 텍스트와 일치) |
| 범위 밖 | 개인정보보호법상 과징금 기준은? | 거절 문구 |

```bash
curl -s -X POST localhost:8000/ask -H "Content-Type: application/json" \
  -d '{"question":"고영향 인공지능이란 무엇인가요?","debug":true}' | python3 -m json.tool
```

## 3. 체크리스트 (질문마다)
- [ ] HTTP 200, 키: `answer`, `sources[].article`, `sources[].content`, `sources[].citation`, `sources[].source_type`, `notice`, `grounded`, `data_snapshot`
- [ ] 기대 citation이 sources에 있음
- [ ] 답변의 `[...]` 인용이 모두 sources citation 안에 있음 (`debug.warnings` 비어 있음)
- [ ] 답변 속 숫자(금액·기간)가 sources 텍스트에 있음
- [ ] 범위 밖 질문은 거절
- [ ] `debug.latency_ms`

## 4. 보고
질문별 PASS/FAIL 표 + 실패 원인 추정. 이 스킬에서 띄운 서버는 종료하고 끝낸다.
