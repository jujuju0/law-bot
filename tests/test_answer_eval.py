"""eval/answer_eval.py 단위테스트 (LLM·Qdrant 없이)."""

import pytest

from common.usage import Usage
from eval import answer_eval
from eval.answer_eval import Estimate, Plan, parse_judge
from rag.chunk_store import get_chunk_store
from rag.config import get_preset
from rag.prompts import REFUSAL, build_messages
from rag.retriever import RetrievalTrace, RetrievedChunk

LAW43 = RetrievedChunk.from_payload(get_chunk_store().by_id["law:a43"], 0.9, "dense")


def q(qid: str, refuse: bool = False, must=("과태료",)) -> dict:
    return {
        "id": qid,
        "type": "out_of_scope" if refuse else "cross_ref",
        "question": f"{qid}: " + ("날씨?" if refuse else "고지 안 하면?"),
        "gold": [] if refuse else ["law:제43조"],
        "reference_answer": "" if refuse else "3천만원 이하의 과태료",
        "must_include": [] if refuse else list(must),
        "should_refuse": refuse,
        "split": "dev",
    }


def make_plan(question: dict, cached: bool = False) -> Plan:
    trace = RetrievalTrace(
        results=[LAW43], candidates=[LAW43], queries=[question["question"]]
    )
    return Plan(question, trace, build_messages(question["question"], [LAW43]), cached)


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        (
            '{"correctness": 4, "relevance": 5, "faithfulness": 3, "reason": "누락"}',
            True,
        ),
        ('```json\n{"correctness": 5, "relevance": 5, "faithfulness": 5}\n```', True),
        ('{"correctness": 6, "relevance": 5, "faithfulness": 5}', False),
        ('{"correctness": "4", "relevance": 5, "faithfulness": 5}', False),
        ("채점 불가", False),
    ],
)
def test_parse_judge(text: str, ok: bool) -> None:
    assert (parse_judge(text) is not None) is ok


def test_estimate_skips_cached_and_refusal_judge() -> None:
    est = answer_eval.estimate(
        [
            make_plan(q("a")),
            make_plan(q("b"), cached=True),
            make_plan(q("c", refuse=True)),
        ]
    )
    assert est.n == 3 and est.n_cached == 1
    assert est.usage.llm_calls == 3  # a: 답변+judge, c: 답변만
    assert (
        est.usage.llm_out
        == 2 * answer_eval.EST_ANSWER_TOKENS + answer_eval.JUDGE_MAX_TOKENS
    )
    assert est.upper.llm_out > est.usage.llm_out


def test_check_budget(monkeypatch) -> None:
    monkeypatch.setattr(answer_eval, "usage_summary", lambda: {"remaining": 100.0})
    cheap = Estimate(1, 0, Usage(llm_calls=1), Usage(llm_calls=1))
    assert answer_eval.check_budget(cheap, ask=lambda _: "y")
    assert not answer_eval.check_budget(cheap, ask=lambda _: "n")
    assert answer_eval.check_budget(cheap, ask=lambda _: "n", yes=True)

    monkeypatch.setattr(Usage, "est_credits", property(lambda self: 30.0))
    pricey = Estimate(1, 0, Usage(llm_calls=1), Usage(llm_calls=1))
    assert not answer_eval.check_budget(
        pricey, ask=lambda _: "y", yes=True
    )  # 20% 초과는 무조건 중단


def test_run_and_summarize_answers() -> None:
    plans = [
        make_plan(q("ok")),
        make_plan(q("wrong_refusal")),
        make_plan(q("oos", refuse=True)),
    ]
    replies = {
        "ok": "3천만원 이하의 과태료입니다 [법 제43조 제1항]. 4천만원 [법 제99조].",
        "wrong_refusal": REFUSAL,
        "oos": REFUSAL,
    }
    by_question = {p.question["id"]: p for p in plans}

    def chat(messages):
        qid = next(k for k, p in by_question.items() if p.messages == list(messages))
        return replies[qid]

    judged = []

    def judge(messages):
        judged.append(messages)
        return '{"correctness": 4, "relevance": 5, "faithfulness": 2, "reason": "숫자 오류"}'

    results = answer_eval.run_answers(
        get_preset("E5_router"), plans, chat=chat, judge=judge
    )
    ok, wrong, oos = results
    assert len(judged) == 1  # 잘못 거절·거절 문항은 judge 호출 안 함
    assert "법 제99조" not in ok.answer and ok.citations == ["법 제43조"]
    assert ok.must_include_hit == 1.0 and not ok.grounded  # 4천만원 근거 없음
    assert wrong.refused and wrong.scores["correctness"] == 1
    assert oos.refusal_correct and oos.scores is None

    s = answer_eval.summarize_answers(results)
    assert s["n"] == 3 and s["n_judged"] == 2 and s["judge_parse_fail"] == 0
    assert s["correctness"] == 2.5 and s["faithfulness"] == 1.5
    assert s["refusal_accuracy"] == round(2 / 3, 4)
    assert s["false_refusal_rate"] == 0.5
    assert s["hallucinated_citation_rate"] == round(1 / 3, 4)
    assert s["number_mismatch_rate"] == round(1 / 3, 4)
