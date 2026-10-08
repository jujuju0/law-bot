"""답변 평가 (DESIGN §7.3·§9.5): 답변 생성 + LLM judge, 예산 가드.

`eval.evaluate --answer`가 호출한다. 순서:
1. 문항별로 검색하고 프롬프트를 만들어 **실행 전 예상 크레딧**을 계산(캐시에 있는 호출은 0)
2. 잔여 예산의 20%를 넘으면 중단, 아니면 사용자 확인(`--yes`면 생략)
3. 답변 생성(`rag.pipeline.answer`) → 후검증 warnings → judge(`JUDGE_MODEL`, max_tokens 300)
"""

from __future__ import annotations

import json
import re
import statistics
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from common.cache import Message, cached_chat, is_cached
from common.config import (
    CREDIT_PER_1K_EMBED,
    CREDIT_PER_1K_INPUT,
    CREDIT_PER_1K_OUTPUT,
    JUDGE_MODEL,
    MAX_TOKENS,
    PROJECT_ROOT,
)
from common.usage import Usage, count_tokens
from common.usage import summarize as usage_summary
from rag.config import RetrievalConfig
from rag.pipeline import AskResult, answer
from rag.prompts import build_messages, select_context
from rag.retriever import RetrievalTrace, retrieve_with_trace

JUDGE_PROMPT_PATH = PROJECT_ROOT / "eval" / "judge_prompt.md"
JUDGE_MAX_TOKENS = 300  # DESIGN §9.5
EST_ANSWER_TOKENS = 400  # 답변 출력 평균 가정(DESIGN §9.2). 상한은 MAX_TOKENS
BUDGET_RATIO_LIMIT = 0.2  # 예상치가 잔여 예산의 20%를 넘으면 중단
SCORES = ("correctness", "relevance", "faithfulness")
JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


# ---------------------------------------------------------------------------
# 예산 추정
# ---------------------------------------------------------------------------
@dataclass
class Plan:
    """문항 1개의 실행 계획(검색 결과 + 답변 프롬프트)."""

    question: dict[str, Any]
    trace: RetrievalTrace
    messages: list[Message]
    answer_cached: bool


@dataclass
class Estimate:
    """실행 전 예상 사용량."""

    n: int
    n_cached: int
    usage: Usage
    upper: Usage  # 답변이 매번 max_tokens까지 나올 때

    def report(self, remaining: float) -> str:
        """사용자에게 보여줄 한 줄 요약."""
        no_price = not (
            CREDIT_PER_1K_INPUT or CREDIT_PER_1K_OUTPUT or CREDIT_PER_1K_EMBED
        )
        return (
            f"답변 평가 {self.n}문항 (답변 캐시 hit {self.n_cached}) | "
            f"예상 입력 {self.usage.llm_in:,} / 출력 {self.usage.llm_out:,} 토큰 | "
            f"예상 {self.usage.est_credits:,.1f} 크레딧 (상한 {self.upper.est_credits:,.1f}) | "
            f"잔여 {remaining:,.1f}"
            + (" | 주의: CREDIT_PER_1K_* 단가 미설정 → 0으로 계산" if no_price else "")
        )


def plan(cfg: RetrievalConfig, questions: Sequence[dict[str, Any]]) -> list[Plan]:
    """문항별 검색·프롬프트 구성(LLM 호출 없음, 질의 임베딩은 캐시 경유)."""
    plans = []
    for q in questions:
        trace = retrieve_with_trace(q["question"], cfg)
        context = select_context(trace.results)
        messages = build_messages(q["question"], context) if context else []
        plans.append(Plan(q, trace, messages, not messages or is_cached(messages)))
    return plans


def _judge_input_tokens(p: Plan) -> int:
    return count_tokens(JUDGE_PROMPT_PATH.read_text(encoding="utf-8")) + sum(
        count_tokens(content) for _, content in p.messages[1:]
    )


def estimate(plans: Sequence[Plan]) -> Estimate:
    """답변 생성 + judge 예상 토큰. 캐시에 있는 답변은 0으로, judge는 답변이 새로 나올 때만 센다."""
    usage, upper = Usage(), Usage()
    for p in plans:
        if p.answer_cached:
            continue
        prompt = sum(count_tokens(content) for _, content in p.messages)
        judge_in = _judge_input_tokens(p) if not p.question["should_refuse"] else 0
        judge_out = JUDGE_MAX_TOKENS if judge_in else 0
        for u, out in ((usage, EST_ANSWER_TOKENS), (upper, MAX_TOKENS)):
            u.llm_in += prompt + judge_in + (out if judge_in else 0)
            u.llm_out += out + judge_out
            u.llm_calls += 1 + bool(judge_in)
    return Estimate(len(plans), sum(p.answer_cached for p in plans), usage, upper)


def check_budget(
    est: Estimate, ask: Callable[[str], str] = input, yes: bool = False
) -> bool:
    """예산 가드(DESIGN §9.5). 실행해도 되면 True."""
    remaining = usage_summary()["remaining"]
    print(est.report(remaining))
    if est.usage.est_credits > remaining * BUDGET_RATIO_LIMIT:
        print(
            f"중단: 예상치가 잔여 예산의 {BUDGET_RATIO_LIMIT:.0%}를 넘습니다. 사용자에게 보고하세요."
        )
        return False
    if yes or est.usage.llm_calls == 0:
        return True
    return ask("실행할까요? [y/N] ").strip().lower() in ("y", "yes")


# ---------------------------------------------------------------------------
# judge
# ---------------------------------------------------------------------------
def judge_messages(q: dict[str, Any], result: AskResult) -> list[Message]:
    """judge 입력 메시지."""
    sources = "\n\n".join(f"[{s.citation}]\n{s.content}" for s in result.sources)
    user = (
        f"질문: {q['question']}\n\n모범 답안: {q['reference_answer']}\n\n"
        f"필수 포함 요소: {', '.join(q.get('must_include', [])) or '(없음)'}\n\n"
        f"근거(sources):\n{sources or '(없음)'}\n\n평가 대상 답변:\n{result.answer}"
    )
    return [("system", JUDGE_PROMPT_PATH.read_text(encoding="utf-8")), ("user", user)]


def parse_judge(text: str) -> dict[str, Any] | None:
    """judge JSON 파싱. 점수가 1~5 정수가 아니면 None."""
    m = JSON_OBJECT.search(text)
    if not m:
        return None
    try:
        data = json.loads(m[0])
    except json.JSONDecodeError:
        return None
    if not all(isinstance(data.get(k), int) and 1 <= data[k] <= 5 for k in SCORES):
        return None
    return {k: data[k] for k in (*SCORES, "reason") if k in data}


def _default_judge(messages: Sequence[Message]) -> str:
    return cached_chat(messages, model=JUDGE_MODEL, max_tokens=JUDGE_MAX_TOKENS)


# ---------------------------------------------------------------------------
# 실행·집계
# ---------------------------------------------------------------------------
@dataclass
class AnswerResult:
    """문항 1개의 답변 평가 결과."""

    id: str
    type: str
    question: str
    should_refuse: bool
    answer: str
    citations: list[str]
    grounded: bool
    refused: bool
    warnings: list[str]
    must_include_hit: float | None  # 필수 포함 요소 중 답변에 있는 비율
    scores: dict[str, Any] | None = (
        None  # judge 점수(거절 문항·잘못 거절한 문항은 None)
    )
    sources: list[dict[str, Any]] = field(default_factory=list)

    @property
    def refusal_correct(self) -> bool:
        """거절해야 할 때만 거절했는지."""
        return self.refused == self.should_refuse


def run_answers(
    cfg: RetrievalConfig,
    plans: Sequence[Plan],
    chat: Callable[[Sequence[Message]], str] | None = None,
    judge: Callable[[Sequence[Message]], str] = _default_judge,
) -> list[AnswerResult]:
    """계획대로 답변을 만들고 채점한다."""
    out = []
    for p in plans:
        q = p.question
        kwargs = {"chat": chat} if chat else {}
        res = answer(q["question"], cfg, debug=True, trace=p.trace, **kwargs)
        refused = bool(res.debug and res.debug["refused"])
        must = q.get("must_include") or []
        r = AnswerResult(
            id=q["id"],
            type=q["type"],
            question=q["question"],
            should_refuse=q["should_refuse"],
            answer=res.answer,
            citations=[s.citation for s in res.sources if s.cited],
            grounded=res.grounded,
            refused=refused,
            warnings=res.warnings,
            must_include_hit=sum(m in res.answer for m in must) / len(must)
            if must
            else None,
            sources=[asdict(s) for s in res.sources],
        )
        if not q["should_refuse"]:
            # 답할 수 있는 문항을 거절하면 judge 없이 최저점
            r.scores = (
                {k: 1 for k in SCORES} | {"reason": "잘못된 거절"}
                if refused
                else parse_judge(judge(judge_messages(q, res)))
            )
        out.append(r)
    return out


def summarize_answers(results: Sequence[AnswerResult]) -> dict[str, Any]:
    """답변 지표: judge 평균, grounded·환각·숫자 불일치·거절 정확도, 필수 요소 포함률."""
    if not results:
        return {"n": 0}
    judged = [r for r in results if r.scores and "correctness" in r.scores]
    answerable = [r for r in results if not r.should_refuse]
    must = [r.must_include_hit for r in results if r.must_include_hit is not None]

    def rate(
        pred: Callable[[AnswerResult], bool], rs: Sequence[AnswerResult]
    ) -> float | None:
        return round(sum(map(pred, rs)) / len(rs), 4) if rs else None

    out: dict[str, Any] = {
        "n": len(results),
        "n_judged": len(judged),
        "judge_parse_fail": len(answerable) - len(judged),
        **{
            k: round(statistics.mean(r.scores[k] for r in judged), 3)
            if judged
            else None
            for k in SCORES
        },
        "grounded_rate": rate(lambda r: r.grounded, results),
        "hallucinated_citation_rate": rate(
            lambda r: any(w.startswith("근거에 없는 인용") for w in r.warnings), results
        ),
        "number_mismatch_rate": rate(
            lambda r: any(w.startswith("근거 텍스트에 없는 숫자") for w in r.warnings),
            results,
        ),
        "refusal_accuracy": rate(lambda r: r.refusal_correct, results),
        "false_refusal_rate": rate(lambda r: r.refused, answerable),
        "must_include": round(statistics.mean(must), 4) if must else None,
    }
    return out
