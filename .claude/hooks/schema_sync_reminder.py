#!/usr/bin/env python3
"""PostToolUse: 청킹·설정 코드가 바뀌면 후속 작업을 Claude에게 상기시킨다 (차단하지 않음).

stdout의 JSON additionalContext는 Claude의 컨텍스트에 추가된다.
"""
import json
import sys

data = json.load(sys.stdin)
path = (data.get("tool_input") or {}).get("file_path", "") or ""

msg = None
if path.endswith(("rag/chunker.py", "rag/loader.py")):
    msg = ("청킹/로딩 코드가 바뀌었습니다. payload 필드가 바뀌었다면 docs/DESIGN.md §3과 "
           "tests/test_chunker.py를 함께 갱신하고, /reindex 후 기존 평가 결과는 재측정이 필요합니다.")
elif path.endswith("common/law_api.py"):
    msg = ("Open API 클라이언트가 바뀌었습니다. tests/test_law_api.py(fixtures, 네트워크 없이)로 확인하고, "
           "응답 구조 가정이 바뀌었다면 .claude/skills/law-api/SKILL.md의 '확인 결과' 표를 갱신하세요.")
elif path.endswith("data/sources.yaml"):
    msg = ("수집 대상이 바뀌었습니다. /reindex(필요 시 --refresh)로 재수집·재적재하고 snapshot_date를 갱신하세요. "
           "골든셋 gold가 제외된 문서를 가리키지 않는지도 확인하세요.")
elif path.endswith("rag/config.py"):
    msg = ("RetrievalConfig가 바뀌었습니다. 새 플래그의 기본값은 False여야 하며(이전 실험 재현성), "
           "eval/configs.py 프리셋과 docs/DESIGN.md §4.1을 맞춰 주세요.")
elif path.endswith("rag/prompts.py"):
    msg = "프롬프트가 바뀌었습니다. grounding-reviewer 에이전트로 근거 충실성을 다시 점검하세요."

if msg:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                             "additionalContext": msg}}, ensure_ascii=False))
sys.exit(0)
