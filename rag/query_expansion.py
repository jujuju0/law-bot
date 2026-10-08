"""질의 확장 (DESIGN §4.2, T3.4).

- Term expansion: `data/term_synonyms.yaml`의 별칭이 질문에 있으면 정식 법령 용어를 덧붙인다(LLM 없음, 결정적).
- Multi-Query: LLM이 질문을 법령 용어로 n개 재작성한다(`common.cache.cached_chat` 경유, JSON 배열 파싱 실패 시 []).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import yaml

from common.cache import cached_chat
from common.config import DATA_DIR

SYNONYMS_PATH = DATA_DIR / "term_synonyms.yaml"
MULTI_QUERY_MAX_TOKENS = 200  # DESIGN §9.5 호출 상한
JSON_ARRAY = re.compile(r"\[.*\]", re.DOTALL)

MULTI_QUERY_SYSTEM = (
    "너는 한국 「인공지능 발전과 신뢰 기반 조성 등에 관한 기본법」(AI 기본법)과 시행령 검색을 돕는다. "
    "사용자 질문을 법령 조문에 쓰일 법률 용어로 바꾼 검색 질의를 만든다. "
    "질문에 없는 사실·조문 번호·숫자를 지어내지 않는다. "
    "출력은 문자열 JSON 배열 하나만 쓴다."
)


class TermExpander:
    """정식 용어 → 별칭 사전으로 질의를 확장한다."""

    def __init__(self, synonyms: dict[str, list[str]]) -> None:
        self.synonyms = {
            term: [a.lower() for a in aliases] for term, aliases in synonyms.items()
        }

    def matched_terms(self, question: str) -> list[str]:
        """질문에 별칭이 있고 정식 용어는 없는 용어 목록(사전 순서)."""
        q = question.lower()
        return [
            term
            for term, aliases in self.synonyms.items()
            if term not in question and any(a in q for a in aliases)
        ]

    def expand(self, question: str) -> str:
        """질문 뒤에 정식 용어를 덧붙인 검색 질의(추가할 용어가 없으면 질문 그대로)."""
        terms = self.matched_terms(question)
        return f"{question} {' '.join(terms)}" if terms else question


@lru_cache(maxsize=2)
def get_term_expander(path: Path = SYNONYMS_PATH) -> TermExpander:
    """사전 파일 기반 TermExpander 싱글톤."""
    return TermExpander(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def parse_queries(text: str, n: int) -> list[str]:
    """LLM 출력에서 문자열 JSON 배열을 꺼낸다(최대 n개, 실패 시 [])."""
    m = JSON_ARRAY.search(text)
    if not m:
        return []
    try:
        items = json.loads(m[0])
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    queries = [s.strip() for s in items if isinstance(s, str) and s.strip()]
    return list(dict.fromkeys(queries))[:n]


def multi_queries(question: str, n: int) -> list[str]:
    """질문을 법률 용어 검색 질의 n개로 재작성한다(원 질문은 포함하지 않음)."""
    text = cached_chat(
        [
            ("system", MULTI_QUERY_SYSTEM),
            ("user", f"질문: {question}\n법률 용어 검색 질의 {n}개를 JSON 배열로:"),
        ],
        max_tokens=MULTI_QUERY_MAX_TOKENS,
    )
    return [q for q in parse_queries(text, n) if q != question]
