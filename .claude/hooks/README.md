# Hooks

`.claude/settings.json`에 등록되어 Claude Code가 도구를 쓸 때 자동 실행된다. 모두 `python3` 표준 라이브러리만 사용(WSL Ubuntu 기본 python3로 동작).

| 파일 | 이벤트 | 동작 | 차단 여부 |
|---|---|---|---|
| `guard.py` | PreToolUse (Read/Edit/Write/Bash) | `.env` 읽기·수정 차단 / **`.env`의 LAW_OC 값이 코드·문서·명령에 들어가면 차단** / law.go.kr 직접 curl 차단(LawApiClient 사용 유도) / Qdrant 컬렉션 `DELETE`, `data/`·`eval/results/` 삭제, `down -v` 차단 / test split 평가·답변 평가(`--answer`, 크레딧 소모)·API 재수집 시 경고 | 차단(exit 2) |
| `format_python.py` | PostToolUse (Edit/Write) | `.py` 수정 시 `ruff format` + `ruff check --fix`. 남은 오류는 Claude에게 전달. ruff 없으면 건너뜀 | 피드백 |
| `validate_golden_set.py` | PostToolUse (Edit/Write) | `eval/golden_set.jsonl` 스키마 검증 (필수 필드, type 8종, split, gold 형식 `law:제31조`·`decree:`·`annex:별표1`, 유형별 규칙) | 피드백 |
| `schema_sync_reminder.py` | PostToolUse (Edit/Write) | chunker/loader/law_api/sources.yaml/config/prompts 수정 시 테스트·DESIGN.md·재수집·재평가 필요성을 컨텍스트로 주입 | 안내만 |

OC 값은 훅 프로세스가 `.env`에서 직접 읽어 비교만 한다. Claude에게는 값이 전달되지 않는다.

## 설치 후 확인
```bash
chmod +x .claude/hooks/*.py
uv add --dev ruff
# Claude Code 안에서
/hooks
```

## 수동 테스트
```bash
echo '{"tool_name":"Read","tool_input":{"file_path":".env"}}' | python3 .claude/hooks/guard.py; echo "exit=$?"   # 2
echo '{"tool_name":"Bash","tool_input":{"command":"curl \"http://www.law.go.kr/DRF/lawSearch.do?target=law\""}}' | python3 .claude/hooks/guard.py; echo "exit=$?"   # 2
```
