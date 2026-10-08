---
name: run-eval
description: Golden Set으로 검색/답변 평가를 실행하고 결과를 docs/EXPERIMENTS.md에 기록한다. "평가 돌려줘", "E4 실험해줘", "baseline이랑 비교해줘" 같은 요청에 사용.
---

# 평가 실행 절차

## 인자
- `config`: `eval/configs.py`의 프리셋 이름 (기본 `baseline`). 여러 개면 순서대로 실행.
- `split`: `dev`(기본) | `test` — **test는 사용자가 명시적으로 요청할 때만.**
- `answer`: 답변 평가(LLM judge)까지 할지. 기본은 retrieval만. **답변 평가는 최종 후보 config에만** (DESIGN §9).
- `limit`: 개발 중 빠른 확인용 문항 수 (예: 5).
- `exp_id`: EXPERIMENTS.md에 쓸 ID (예: E4). 없으면 사용자에게 묻지 말고 다음 번호 사용.

## 절차
1. 사전 점검
   - Qdrant 응답 확인: `curl -s localhost:6333/collections` → 대상 컬렉션 존재·포인트 수 > 0. 없으면 `/reindex` 먼저 제안 후 중단.
   - `eval/golden_set.jsonl` 유효성: `uv run python -m eval.evaluate --validate-only`
2. 비용 확인 (`--answer`일 때만)
   - `uv run python -m common.usage --summary`로 누적 사용량·잔여 예산 확인
   - evaluate가 출력하는 예상 크레딧을 사용자에게 보여주고 **승인 후** 실행 (`--yes`는 사용자가 허락한 경우만)
   - 예상치가 잔여 예산의 20%를 넘으면 실행하지 말고 보고
3. 실행
   ```bash
   uv run python -m eval.evaluate --config <config> --split <split> [--answer]
   ```
   결과는 `eval/results/{timestamp}_{config}.json`.
4. 이전 실험 대비 비교
   - EXPERIMENTS.md 요약 표의 직전 채택 실험과 Hit@1/3/5, MRR, p50 지연 Δ 계산.
   - 문항 단위로 개선/악화 목록 산출 (결과 JSON 두 개를 diff).
5. 기록 — `docs/EXPERIMENTS.md`
   - 요약 표의 해당 행 채우기(토큰·크레딧 열 포함) + 유형별 Hit@3 표 행 추가
   - 하단에 "실험 기록 템플릿" 형식으로 섹션 추가. 가설은 사용자가 말한 것 또는 DESIGN §8의 가설.
   - "결정"은 비워두고 사용자에게 채택 여부를 물어본다.
6. 실패가 3건 이상이면 `retrieval-analyst` 에이전트로 실패 분석을 돌리고 요약을 함께 보고.

## 보고 형식 (채팅)
```
E4 hybrid (dev 30문항)
Hit@1 0.53 → 0.63 (+0.10) | Hit@3 0.73 → 0.87 | MRR 0.62 → 0.72 | p50 410ms
사용량: LLM 14.2k / 임베딩 0.3k 토큰, 캐시 hit 30/33, 약 N 크레딧 (누적 X / 잔여 Y)
개선: q004, q011, q019  악화: q023
유형별 최대 개선: colloquial +0.25
```

## 주의
- 평균 차이가 1~2문항 수준이면 "유의미하지 않을 수 있음"이라고 명시.
- 결과 JSON은 커밋 대상. 덮어쓰지 않는다.
