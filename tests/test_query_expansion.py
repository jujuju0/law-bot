"""rag/query_expansion.py · common/cache.py · common/usage.py 단위테스트 (LLM 호출 없이)."""

import json

import pytest

from common import cache, usage
from common.usage import Usage
from rag import query_expansion
from rag.query_expansion import TermExpander, get_term_expander, parse_queries


def test_term_expander() -> None:
    e = TermExpander({"고영향 인공지능": ["위험한 AI"], "표시": ["워터마크"]})
    assert e.expand("위험한 ai인지 궁금") == "위험한 ai인지 궁금 고영향 인공지능"
    assert e.expand("고영향 인공지능인 위험한 AI") == "고영향 인공지능인 위험한 AI"
    assert e.expand("상관없는 질문") == "상관없는 질문"


def test_synonym_file_loads() -> None:
    e = get_term_expander()
    assert "국내대리인" in e.matched_terms("해외 회사라 한국에 사무실이 없어요")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('["a", "b", "c", "d"]', ["a", "b", "c"]),
        ('결과:\n```json\n["a", "a", " ", 3]\n```', ["a"]),
        ("JSON 아님", []),
        ("[깨진 json", []),
        ('{"q": ["a"]}', ["a"]),
    ],
)
def test_parse_queries(text: str, expected: list[str]) -> None:
    assert parse_queries(text, 3) == expected


def test_multi_queries_drops_original(monkeypatch) -> None:
    monkeypatch.setattr(
        query_expansion, "cached_chat", lambda *a, **k: '["원 질문", "법률 질의"]'
    )
    assert query_expansion.multi_queries("원 질문", 3) == ["법률 질의"]


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cache, "get_llm_cache", lambda: cache.LlmCache(tmp_path / "llm.sqlite")
    )
    store = cache.LlmCache(tmp_path / "llm.sqlite")
    monkeypatch.setattr(cache, "get_llm_cache", lambda: store)
    return store


def test_cached_chat_hits_cache_and_tracks_usage(tmp_cache) -> None:
    calls = []

    def fake_invoke(messages, model, temperature, max_tokens):
        calls.append(messages)
        return {"text": "답", "llm_in": 10, "llm_out": 3}

    before = usage.tracker.snapshot()
    msgs = [("user", "질문")]
    for _ in range(2):
        assert (
            cache.cached_chat(msgs, model="m", temperature=0, invoke=fake_invoke)
            == "답"
        )
    delta = usage.tracker.snapshot() - before
    assert len(calls) == 1
    assert (delta.llm_in, delta.llm_out, delta.llm_calls, delta.cache_hits) == (
        10,
        3,
        1,
        1,
    )

    # temperature > 0은 캐시하지 않음
    cache.cached_chat(msgs, model="m", temperature=0.7, invoke=fake_invoke)
    cache.cached_chat(msgs, model="m", temperature=0.7, invoke=fake_invoke)
    assert len(calls) == 3


def test_cache_key_changes_with_settings() -> None:
    msgs = [("user", "q")]
    keys = {
        cache.cache_key(msgs, "m", 0, 100),
        cache.cache_key(msgs, "m2", 0, 100),
        cache.cache_key(msgs, "m", 0, 200),
        cache.cache_key([("user", "q2")], "m", 0, 100),
    }
    assert len(keys) == 4


def test_usage_ledger_summary(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(usage, "CREDIT_PER_1K_INPUT", 1.0)
    monkeypatch.setattr(usage, "CREDIT_PER_1K_OUTPUT", 4.0)
    monkeypatch.setattr(usage, "CREDIT_PER_1K_EMBED", 0.0)
    monkeypatch.setattr(usage, "LLM_BUDGET_CREDITS", 100.0)
    ledger = tmp_path / "ledger.jsonl"
    usage.record("eval_retrieval", "E6", Usage(llm_in=2000, llm_out=500), ledger)
    usage.record("eval_answer", "E9", Usage(llm_in=1000, embed=50), ledger)
    row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert row["est_credits"] == 4.0 and row["config"] == "E6"
    s = usage.summarize(ledger)
    assert s["used_credits"] == 5.0 and s["remaining"] == 95.0
    assert s["total"]["llm_in"] == 3000
