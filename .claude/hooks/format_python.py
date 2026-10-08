#!/usr/bin/env python3
"""PostToolUse: 수정된 .py 파일에 ruff format + ruff check --fix 적용.

ruff가 없으면 조용히 넘어간다. 남은 린트 오류는 exit 2로 Claude에게 알려 수정하게 한다.
"""
import json
import os
import shutil
import subprocess
import sys

data = json.load(sys.stdin)
path = (data.get("tool_input") or {}).get("file_path", "") or ""
if not path.endswith(".py") or not os.path.exists(path):
    sys.exit(0)

project = os.environ.get("CLAUDE_PROJECT_DIR", ".")
if shutil.which("uv"):
    ruff = ["uv", "run", "--quiet", "ruff"]
elif shutil.which("ruff"):
    ruff = ["ruff"]
else:
    sys.exit(0)

try:
    subprocess.run(ruff + ["format", path], cwd=project, capture_output=True, timeout=30)
    r = subprocess.run(
        ruff + ["check", "--fix", "--quiet", path],
        cwd=project, capture_output=True, text=True, timeout=30,
    )
except (subprocess.TimeoutExpired, FileNotFoundError):
    sys.exit(0)

if r.returncode != 0 and r.stdout.strip():
    if "No such file" in r.stderr or "not found" in r.stderr.lower():
        sys.exit(0)  # ruff 미설치
    print(f"[ruff] {path}에 남은 린트 오류:\n{r.stdout.strip()[:2000]}", file=sys.stderr)
    sys.exit(2)
sys.exit(0)
