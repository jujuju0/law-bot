"""LLM 응답 캐시 (DESIGN §9.3). 모든 LLM 호출은 `cached_chat`을 거친다.

키 = sha256(model, temperature, max_tokens, messages). temperature 0(또는 미지정) 호출만 캐시한다.
캐시 hit·실제 호출 토큰은 `common.usage.tracker`에 기록된다.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from common.config import CACHE_DIR, MAX_TOKENS, MODEL, TEMPERATURE
from common.usage import tracker

Message = tuple[str, str]  # (role, content) — role: system | user | assistant
LLM_CACHE_PATH = CACHE_DIR / "llm.sqlite"


class LlmCache:
    """sqlite 키-값 캐시 (key → {"text", "llm_in", "llm_out"})."""

    def __init__(self, path: Path = LLM_CACHE_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS llm (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )

    def get(self, key: str) -> dict[str, Any] | None:
        """저장된 응답(없으면 None)."""
        row = self._conn.execute(
            "SELECT value FROM llm WHERE key = ?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: dict[str, Any]) -> None:
        """응답 저장(같은 키는 덮어씀)."""
        self._conn.execute(
            "INSERT OR REPLACE INTO llm (key, value) VALUES (?, ?)",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        self._conn.commit()


@lru_cache(maxsize=1)
def get_llm_cache() -> LlmCache:
    """프로세스 공용 LLM 캐시."""
    return LlmCache()


def cache_key(
    messages: Sequence[Message], model: str, temperature: float | None, max_tokens: int
) -> str:
    """캐시 키: 모델·생성 설정·메시지 전체의 sha256."""
    raw = json.dumps(
        [model, temperature, max_tokens, list(messages)], ensure_ascii=False
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def is_cached(
    messages: Sequence[Message],
    *,
    model: str = MODEL,
    temperature: float | None = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
) -> bool:
    """이 호출이 캐시에 있는지(예산 추정에서 캐시 hit 제외용)."""
    if temperature not in (None, 0):
        return False
    key = cache_key(messages, model, temperature, max_tokens)
    return get_llm_cache().get(key) is not None


def _invoke(
    messages: Sequence[Message], model: str, temperature: float | None, max_tokens: int
) -> dict[str, Any]:
    from common.ai_model import get_llm_model

    llm = get_llm_model(model=model, temperature=temperature, max_tokens=max_tokens)
    msg = llm.invoke(list(messages))
    meta = getattr(msg, "usage_metadata", None) or {}
    return {
        "text": msg.content if isinstance(msg.content, str) else str(msg.content),
        "llm_in": int(meta.get("input_tokens", 0)),
        "llm_out": int(meta.get("output_tokens", 0)),
    }


def cached_chat(
    messages: Sequence[Message],
    *,
    model: str = MODEL,
    temperature: float | None = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    use_cache: bool = True,
    invoke: Callable[..., dict[str, Any]] = _invoke,
) -> str:
    """LLM 호출(캐시 우선). 반환은 응답 텍스트. `invoke`는 테스트용 주입 지점."""
    cacheable = use_cache and temperature in (None, 0)
    key = cache_key(messages, model, temperature, max_tokens)
    if cacheable and (hit := get_llm_cache().get(key)) is not None:
        tracker.add_cache_hit()
        return hit["text"]
    result = invoke(messages, model, temperature, max_tokens)
    tracker.add_llm(result["llm_in"], result["llm_out"])
    if cacheable:
        get_llm_cache().put(key, result)
    return result["text"]
