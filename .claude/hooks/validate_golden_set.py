#!/usr/bin/env python3
"""PostToolUse: eval/golden_set.jsonl이 수정되면 스키마를 검증한다 (DESIGN.md §7.1)."""
import json
import re
import sys

data = json.load(sys.stdin)
path = (data.get("tool_input") or {}).get("file_path", "") or ""
if not path.endswith("golden_set.jsonl"):
    sys.exit(0)

TYPES = {"definition", "article_lookup", "colloquial", "obligation",
         "cross_ref", "delegation", "annex", "out_of_scope"}
REQUIRED = {"id", "type", "question", "gold", "reference_answer", "should_refuse", "split"}
GOLD = re.compile(
    r"^(?:(law|decree):)?제\d+조(의\d+)?$"   # law:제31조, decree:제5조, 제31조(=law)
    r"|^(law|decree):부칙$"
    r"|^annex:별표\d+(의\d+)?$"
    r"|^(admrul|term|expc):.+$"
)

errors, ids = [], set()
try:
    lines = open(path, encoding="utf-8").read().splitlines()
except OSError:
    sys.exit(0)

for n, line in enumerate(lines, 1):
    if not line.strip():
        continue
    try:
        q = json.loads(line)
    except json.JSONDecodeError as e:
        errors.append(f"{n}행: JSON 오류 {e}")
        continue
    qid = q.get("id")
    missing = REQUIRED - q.keys()
    if missing:
        errors.append(f"{n}행 {qid}: 필드 누락 {sorted(missing)}")
    if qid in ids:
        errors.append(f"{n}행: id 중복 {qid}")
    ids.add(qid)
    t = q.get("type")
    if t not in TYPES:
        errors.append(f"{n}행 {qid}: 알 수 없는 type '{t}'")
    if q.get("split") not in {"dev", "test"}:
        errors.append(f"{n}행 {qid}: split은 dev|test")
    golds = q.get("gold", []) or []
    for g in golds:
        if not GOLD.match(g):
            errors.append(f"{n}행 {qid}: gold 형식 오류 '{g}' (예: law:제31조, decree:제5조, annex:별표1)")
    if q.get("should_refuse") and golds:
        errors.append(f"{n}행 {qid}: should_refuse=true면 gold는 []")
    if not q.get("should_refuse") and not golds:
        errors.append(f"{n}행 {qid}: 정답 gold가 비어 있음")
    if t in {"cross_ref"} and len(golds) < 2:
        errors.append(f"{n}행 {qid}: cross_ref는 gold 2개 이상")
    if t == "annex" and not any(g.startswith("annex:") for g in golds):
        errors.append(f"{n}행 {qid}: annex 유형은 annex:별표N gold 필요")

if errors:
    print("[golden_set] 스키마 오류:\n" + "\n".join(errors[:30]), file=sys.stderr)
    sys.exit(2)
sys.exit(0)
