# Claude Code 설정 적용 방법 (WSL Ubuntu)

템플릿 repo 루트에 **그대로 풀면** 되는 파일만 들어 있습니다.

```bash
cd ~/rag_minipjt
unzip -o /mnt/c/Users/<윈도우사용자명>/Downloads/rag_minipjt_claude_setup_v2.zip -d /tmp/cs
cp -r /tmp/cs/rag_minipjt/. .          # 이전 zip(v1)을 풀었다면 이 명령으로 덮어씀

chmod +x .claude/hooks/*.py
uv add httpx tenacity pyyaml beautifulsoup4 lxml docling kiwipiepy rank-bm25 sentence-transformers tiktoken
uv add --dev ruff pytest respx
```

## .env 에 추가
```
LAW_OC=<발급받은 OC>
LAW_API_BASE=http://www.law.go.kr/DRF
JUDGE_MODEL=gpt-5.4-mini
LLM_BUDGET_CREDITS=26000
CREDIT_PER_1K_INPUT=      # T0.8에서 실측
CREDIT_PER_1K_OUTPUT=
CREDIT_PER_1K_EMBED=
```
- OC 값은 `.env`에만 둡니다. 코드·문서에 OC 값이 들어가면 `guard.py` 훅이 차단합니다.
- 먼저 WSL 터미널에서 직접 호출해 JSON이 오는지 확인하세요. 검증 실패 메시지가 오면 open.law.go.kr에서 사용할 API(현행법령·행정규칙·법령해석례·법령용어·별표서식)의 활용 신청이 승인됐는지, OC 값이 맞는지 확인합니다.

## v1 → v2 변경 파일
| 파일 | 변경 |
|---|---|
| `CLAUDE.md` | 데이터 원천(Open API 6종), OC 취급 규칙, citation 규칙 |
| `docs/DESIGN.md` | 전면 개정: API 수집·캐시, 원천별 청킹, 위임 그래프, Delegation expansion, 실험 E0~E10 |
| `docs/TASKS.md` | T0.6(API 호출 확인)·T0.7(응답 구조 확인), Phase 1 수집 작업, Phase 3 E8/E9 |
| `docs/EXPERIMENTS.md` | sources 열, annex 유형, Full-Recall@5 |
| `data/sources.yaml` | **신규** — 수집 대상 고정 |
| `.claude/skills/law-api/` | **신규** — 엔드포인트, 정규화, 캐시, 별표 HTML 처리 |
| `.claude/skills/law-structure/` | API 계층 기준으로 개정, chunk_id·citation 규칙 |
| `.claude/skills/reindex`, `api-smoke`, `add-retrieval-technique` | 수집 단계, 위임 확장, 새 질문 |
| `.claude/agents/*` | 원천별 점검, DELEG 실패 코드, delegation/annex 문항 |
| `.claude/hooks/guard.py` | OC 유출 차단, law.go.kr 직접 curl 차단, 재수집 경고 |
| `.claude/hooks/validate_golden_set.py` | gold 형식 `law:`/`decree:`/`annex:`, 유형 annex |

## 시작 프롬프트 예시
```
docs/TASKS.md의 Phase 0부터 진행해줘. T0.7에서 실제 API 응답 구조를 확인하면 law-api 스킬의 확인 결과 표를 채워줘.
```
