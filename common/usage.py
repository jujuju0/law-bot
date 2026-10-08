"""토큰 사용량 집계와 누적 장부 (DESIGN §9.4).

- 프로세스 전역 `tracker`가 LLM 입·출력 토큰, 임베딩 토큰, 캐시 hit를 누적한다.
- 작업 단위 사용량은 `tracker.snapshot()` 전후 차이(`Usage.__sub__`)로 구한다.
- `record(task, config, usage)`가 `eval/usage_ledger.jsonl`에 1줄 append.

사용: uv run python -m common.usage --summary
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from common.config import (
    CREDIT_PER_1K_EMBED,
    CREDIT_PER_1K_INPUT,
    CREDIT_PER_1K_OUTPUT,
    LLM_BUDGET_CREDITS,
    USAGE_LEDGER,
)


@dataclass
class Usage:
    """토큰 사용량 묶음."""

    llm_in: int = 0
    llm_out: int = 0
    embed: int = 0
    llm_calls: int = 0
    cache_hits: int = 0

    def __sub__(self, other: Usage) -> Usage:
        return Usage(
            **{
                f.name: getattr(self, f.name) - getattr(other, f.name)
                for f in fields(self)
            }
        )

    @property
    def est_credits(self) -> float:
        """단가(.env의 CREDIT_PER_1K_*) 기준 예상 크레딧."""
        return (
            self.llm_in / 1000 * CREDIT_PER_1K_INPUT
            + self.llm_out / 1000 * CREDIT_PER_1K_OUTPUT
            + self.embed / 1000 * CREDIT_PER_1K_EMBED
        )

    def to_dict(self) -> dict[str, float | int]:
        """결과 JSON·장부용 dict(예상 크레딧 포함)."""
        return {**asdict(self), "est_credits": round(self.est_credits, 2)}


class UsageTracker:
    """프로세스 전역 사용량 누적기."""

    def __init__(self) -> None:
        self.total = Usage()

    def add_llm(self, input_tokens: int, output_tokens: int) -> None:
        """실제 LLM 호출 1건의 토큰을 더한다."""
        self.total.llm_in += input_tokens
        self.total.llm_out += output_tokens
        self.total.llm_calls += 1

    def add_cache_hit(self) -> None:
        """캐시로 대체된 LLM 호출 1건."""
        self.total.cache_hits += 1

    def add_embed(self, tokens: int) -> None:
        """실제 임베딩 API 호출 토큰(캐시 hit는 0)."""
        self.total.embed += tokens

    def snapshot(self) -> Usage:
        """현재 누적값 복사본."""
        return Usage(**asdict(self.total))


tracker = UsageTracker()


@lru_cache(maxsize=1)
def _encoder() -> Any | None:
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except (ImportError, OSError, ValueError):  # 인코딩 파일 다운로드 불가 등
        return None


def count_tokens(text: str) -> int:
    """임베딩 토큰 추정(tiktoken cl100k, 로딩 실패 시 글자 수 기반 근사)."""
    enc = _encoder()
    return len(enc.encode(text)) if enc else max(1, len(text) // 2)


def record(
    task: str, config: str | None, usage: Usage, path: Path = USAGE_LEDGER
) -> None:
    """누적 장부에 1줄 append (`ts, task, config, tokens, est_credits`)."""
    row = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "task": task,
        "config": config,
        **usage.to_dict(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def summarize(path: Path = USAGE_LEDGER) -> dict:
    """장부 합계·작업별 합계·잔여 예산."""
    rows = (
        [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        if path.exists()
        else []
    )
    by_task: dict[str, float] = defaultdict(float)
    total = Usage()
    for r in rows:
        by_task[r["task"]] += r.get("est_credits", 0.0)
        for f in fields(total):
            setattr(total, f.name, getattr(total, f.name) + int(r.get(f.name, 0)))
    used = sum(by_task.values())
    return {
        "runs": len(rows),
        "total": total.to_dict(),
        "by_task_credits": {k: round(v, 2) for k, v in by_task.items()},
        "used_credits": round(used, 2),
        "budget": LLM_BUDGET_CREDITS,
        "remaining": round(LLM_BUDGET_CREDITS - used, 2),
    }


def main() -> None:
    """CLI: `--summary`로 누적 사용량과 잔여 예산을 출력한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    if args.summary:
        print(json.dumps(summarize(), ensure_ascii=False, indent=2))
        if not (CREDIT_PER_1K_INPUT or CREDIT_PER_1K_OUTPUT or CREDIT_PER_1K_EMBED):
            print("주의: .env에 CREDIT_PER_1K_* 단가가 없어 크레딧이 0으로 계산됨")


if __name__ == "__main__":
    main()
