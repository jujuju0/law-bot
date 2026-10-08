#!/usr/bin/env python3
"""PreToolUse 가드: .env 접근, Open API 인증키(OC) 유출, 위험한 명령을 차단한다.

exit 2 + stderr 메시지 → Claude에게 차단 사유가 전달된다.
"""
import json
import os
import re
import sys

data = json.load(sys.stdin)
tool = data.get("tool_name", "")
inp = data.get("tool_input", {}) or {}
project = os.environ.get("CLAUDE_PROJECT_DIR", ".")


def block(msg: str) -> None:
    print(f"[guard] 차단: {msg}", file=sys.stderr)
    sys.exit(2)


def law_oc() -> str | None:
    """훅 프로세스가 .env에서 LAW_OC 값을 직접 읽는다 (Claude에게는 노출되지 않음)."""
    try:
        with open(os.path.join(project, ".env"), encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\s*LAW_OC\s*=\s*['\"]?([^'\"\s#]+)", line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None


# 1) .env 파일 읽기/수정 차단 (.env.example은 허용)
path = inp.get("file_path", "") or ""
if re.search(r"(^|/)\.env$", path):
    block(".env에는 API 키가 있습니다. 키 이름은 .env.example을 참고하세요.")

# 2) OC 값이 코드·문서·명령에 하드코딩되는 것 차단
oc = law_oc()
if oc and len(oc) >= 3:
    texts = [inp.get("content"), inp.get("new_string"), inp.get("command")]
    texts += [e.get("new_string") for e in inp.get("edits", []) or [] if isinstance(e, dict)]
    if any(t and oc in t for t in texts):
        block("Open API 인증키(OC) 값이 포함돼 있습니다. common.config.LAW_OC를 통해서만 사용하세요.")

if tool == "Bash":
    cmd = inp.get("command", "") or ""

    # 3) Bash로 .env 내용 출력 차단
    if re.search(r"\b(cat|less|more|head|tail|grep|sed|awk|source)\b[^|;&]*(^|[\s/])\.env(\s|$)", cmd):
        block("Bash로 .env를 읽을 수 없습니다.")

    # 4) law.go.kr 직접 호출 차단 → LawApiClient(캐시·재시도·OC 주입) 사용
    if re.search(r"\b(curl|wget|http)\b.*law\.go\.kr", cmd, re.I):
        block("law.go.kr은 common.law_api.LawApiClient로 호출하세요 (예: uv run python -m rag.loader --refresh).")

    # 5) Qdrant 컬렉션 직접 삭제 차단 → /reindex
    if re.search(r"curl\b.*-X\s*DELETE\b.*collections", cmd, re.I):
        block("Qdrant 컬렉션 삭제는 /reindex 스킬(rag.vectorstore --rebuild)로만 하세요.")

    # 6) 데이터·캐시·평가 결과·볼륨 삭제 차단
    if re.search(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+.*\b(data|eval/results|docker-qdrant)\b", cmd):
        block("data/(API 캐시 포함), eval/results/, docker-qdrant/ 삭제는 사용자가 직접 하세요.")
    if re.search(r"docker\s+compose\b.*\bdown\b.*(-v|--volumes)", cmd):
        block("Qdrant 볼륨 삭제(down -v)는 사용자가 직접 하세요.")

    # 7) test split / API 재수집은 경고만
    if re.search(r"eval\.evaluate\b.*--split\s+test", cmd):
        print("[guard] 참고: test split 평가입니다. 사용자가 최종 평가로 요청한 경우에만 진행하세요.", file=sys.stderr)
    if re.search(r"eval\.evaluate\b.*--answer", cmd):
        print("[guard] 참고: 답변 평가는 LLM 크레딧을 씁니다. 예상 크레딧을 사용자에게 보여주고 승인받았는지 확인하세요 (DESIGN §9.5).", file=sys.stderr)
    if re.search(r"rag\.loader\b.*--refresh", cmd):
        print("[guard] 참고: Open API 재수집입니다. 캐시가 덮어써지고 snapshot이 바뀝니다.", file=sys.stderr)

sys.exit(0)
