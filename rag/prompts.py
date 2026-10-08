"""답변 생성 프롬프트와 근거 컨텍스트 구성 (DESIGN §5.1, CLAUDE.md "답변 생성 규칙")."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from common.cache import Message
from common.usage import count_tokens
from rag.retriever import RetrievedChunk

REFUSAL = "제공된 AI 기본법 관련 법령에서 확인할 수 없습니다."
DELEGATION_MISSING = "하위 법령에 위임되어 있으나 제공된 자료에서 확인되지 않습니다."
NOTICE = (
    "AI가 생성한 답변입니다(「인공지능 발전과 신뢰 기반 조성 등에 관한 기본법」 제31조). "
    "법률 자문이 아니며, 정확한 내용은 원문을 확인하세요."
)
CONTEXT_TOKEN_BUDGET = 6000  # DESIGN §9.5: LLM에 넣는 근거 합계 상한

SOURCE_KIND = {
    "law": "법률",
    "decree": "시행령",
    "annex": "시행령 별표",
    "admrul": "고시",
    "expc": "해석 사례",
    "term": "참고 정의",
}

SYSTEM_PROMPT = f"""너는 「인공지능 발전과 신뢰 기반 조성 등에 관한 기본법」(AI 기본법)과 그 하위 법령을 안내하는 도우미다.
독자는 법을 잘 모르는 일반인이다.

규칙:
1. <근거> 안의 내용만 사용한다. 근거에 없는 내용은 일반 지식으로 보충하거나 추측하지 않는다.
2. 모든 주장 문장 끝에 근거의 citation 값을 대괄호로 그대로 단다. 예: [법 제31조 제2항], [영 제22조], [영 별표 2].
   <근거>에 없는 citation은 쓰지 않는다.
3. 효력 순서는 법률 > 시행령(별표 포함) > 고시 > 해석 사례·참고 정의다. 충돌하면 상위 근거를 따르고 그 사실을 밝힌다.
4. 종류가 "해석 사례"인 근거는 "해석 사례에 따르면", "참고 정의"인 근거는 "참고 정의에 따르면"처럼 구분해 쓴다.
5. 질문이 대통령령·고시 등에 위임된 세부 사항을 묻는데 그 하위 법령 근거가 <근거>에 없으면
   "{DELEGATION_MISSING}"라고 쓴다.
6. 금액·기간·비율·인원 같은 숫자는 <근거> 텍스트에 있는 것만 그대로 쓴다. 계산하거나 바꾸지 않는다.
7. 질문에 답할 근거가 <근거>에 없으면 다른 말 없이 정확히 "{REFUSAL}"라고만 답한다.
   이때는 요약·설명·"근거:" 목록을 붙이지 않는다.
8. 한 괄호에는 완전한 citation 하나만 쓴다. 여러 개면 [법 제32조 제1항][법 제32조 제2항]처럼 나눠 쓴다.
9. "모두 충족", "어느 하나에 해당" 같은 요건의 결합 방식은 근거 그대로 옮긴다.

형식:
- 첫 줄: 한 줄 요약
- 이어서 쉬운 설명 3~5문장 (문장마다 citation)
- 마지막: "근거:" 다음 줄부터 사용한 citation 목록 (규칙 7의 거절은 제외)"""


def format_chunk(c: RetrievedChunk) -> str:
    """근거 1건을 프롬프트 블록으로."""
    kind = SOURCE_KIND.get(c.source_type, c.source_type)
    return f'<근거 citation="{c.citation}" 종류="{kind}">\n{c.text}\n</근거>'


def select_context(
    chunks: Sequence[RetrievedChunk],
    budget: int = CONTEXT_TOKEN_BUDGET,
    counter: Callable[[str], int] = count_tokens,
) -> list[RetrievedChunk]:
    """토큰 예산 안의 근거만 고른다. 넘치면 확장으로 붙은 청크부터, 그다음 낮은 순위부터 뺀다."""
    kept = list(chunks)
    drop_order = [c for c in reversed(kept) if c.added_by in ("ref", "delegation")]
    drop_order += [c for c in reversed(kept) if c not in drop_order]
    total = sum(counter(format_chunk(c)) for c in kept)
    for c in drop_order:
        if total <= budget or len(kept) == 1:
            break
        kept.remove(c)
        total -= counter(format_chunk(c))
    return kept


def build_messages(question: str, chunks: Sequence[RetrievedChunk]) -> list[Message]:
    """시스템 프롬프트 + 근거 + 질문 메시지."""
    context = "\n\n".join(format_chunk(c) for c in chunks) or "(검색된 근거 없음)"
    return [
        ("system", SYSTEM_PROMPT),
        ("user", f"<근거 목록>\n{context}\n</근거 목록>\n\n질문: {question}"),
    ]
