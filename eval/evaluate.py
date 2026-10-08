"""Golden Set 검색 평가 (DESIGN §7.3): Hit@1/3/5, Recall@5, Full-Recall@5, MRR, p50 지연, 유형별 집계.

확장(ref/delegation)은 top_k 뒤에 청크를 덧붙이므로 @k 지표는 그대로 두고,
LLM에 실제로 들어가는 전체 결과 기준 `recall@ctx`·`full_recall@ctx`를 따로 계산한다.

사용: uv run python -m eval.evaluate --config E0_naive,E1_structure,E2_header [--split dev] [--limit 5]
      uv run python -m eval.evaluate --config full --answer [--yes]   # 답변+judge, 실행 전 예산 확인
      uv run python -m eval.evaluate --validate-only
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from common.config import PROJECT_ROOT
from common.usage import Usage, record, tracker
from eval import answer_eval
from eval.configs import get_preset
from rag.config import RetrievalConfig
from rag.embeddings import get_embedding_cache
from rag.retriever import (
    RetrievedChunk,
    prepare_queries,
    retrieve_with_trace,
    warmup,
)

GOLDEN_PATH = PROJECT_ROOT / "eval" / "golden_set.jsonl"
RESULTS_DIR = PROJECT_ROOT / "eval" / "results"
KS = (1, 3, 5)
TYPES = (
    "definition",
    "article_lookup",
    "colloquial",
    "obligation",
    "cross_ref",
    "delegation",
    "annex",
    "out_of_scope",
)
REQUIRED = {
    "id",
    "type",
    "question",
    "gold",
    "reference_answer",
    "should_refuse",
    "split",
}
GOLD_ARTICLE = re.compile(r"^(?:(law|decree):)?제(\d+)조(?:의(\d+))?$")
GOLD_ANNEX = re.compile(r"^annex:별표(\d+)(?:의\d+)?$")


# ---------------------------------------------------------------------------
# gold 매칭
# ---------------------------------------------------------------------------
def gold_matcher(gold: str) -> Callable[[RetrievedChunk], bool]:
    """gold 문자열(DESIGN §7.1) → 청크 적중 판정 함수. 조 단위로 비교한다."""
    if m := GOLD_ARTICLE.match(gold):
        key = f"{m[1] or 'law'}:a{int(m[2])}" + (f"_{int(m[3])}" if m[3] else "")
        return lambda c: key in c.keys
    if m := GOLD_ANNEX.match(gold):
        key = f"annex:{int(m[1])}"
        return lambda c: key in c.keys
    source, _, ref = gold.partition(":")
    if ref == "부칙" and source in ("law", "decree"):
        return lambda c: (
            c.source_type == source and c.payload.get("chunk_type") == "addendum"
        )
    if source == "admrul":
        return lambda c: c.source_type == "admrul" and c.doc_title == ref
    if source == "term":
        return lambda c: c.article_key == f"term:{ref}"
    raise ValueError(f"해석할 수 없는 gold: {gold}")


@dataclass
class QuestionResult:
    """문항 1개의 검색 결과와 지표."""

    id: str
    type: str
    question: str
    gold: list[str]
    should_refuse: bool
    latency_ms: float
    retrieved: list[dict[str, Any]]
    gold_ranks: dict[str, int | None] = field(
        default_factory=dict
    )  # gold별 첫 적중 순위(1부터)
    first_hit: int | None = None
    candidate_recall: float | None = None  # 1단계 후보(candidate_k개) 안의 gold 비율
    queries: list[str] = field(
        default_factory=list
    )  # 검색에 쓴 질의(term/multi-query 결과)
    query_prep_ms: float = (
        0.0  # 질의 준비(Multi-Query LLM 호출 등) 시간 — latency_ms와 별도
    )

    def hit(self, k: int) -> bool:
        """상위 k 안에 gold가 하나라도 있는지."""
        return self.first_hit is not None and self.first_hit <= k

    def recall(self, k: int | None = None) -> float:
        """상위 k 안에 들어온 gold 비율(k=None이면 확장 청크 포함 전체 결과)."""
        found = [
            r
            for r in self.gold_ranks.values()
            if r is not None and (k is None or r <= k)
        ]
        return len(found) / len(self.gold_ranks) if self.gold_ranks else 0.0


def score_question(
    q: dict[str, Any], chunks: list[RetrievedChunk], latency_ms: float
) -> QuestionResult:
    """검색 결과를 gold와 대조해 문항 지표를 계산한다."""
    ranks: dict[str, int | None] = {}
    for g in q["gold"]:
        match = gold_matcher(g)
        ranks[g] = next((i for i, c in enumerate(chunks, 1) if match(c)), None)
    found = [r for r in ranks.values() if r is not None]
    return QuestionResult(
        id=q["id"],
        type=q["type"],
        question=q["question"],
        gold=q["gold"],
        should_refuse=q["should_refuse"],
        latency_ms=latency_ms,
        retrieved=[
            {
                "rank": i,
                "chunk_id": c.chunk_id,
                "citation": c.citation,
                "source_type": c.source_type,
                "score": round(c.score, 4),
                "stage_scores": {k: round(v, 4) for k, v in c.stage_scores.items()},
                "added_by": c.added_by,
                "via": c.via,
            }
            for i, c in enumerate(chunks, 1)
        ],
        gold_ranks=ranks,
        first_hit=min(found) if found else None,
    )


def candidate_recall(gold: list[str], candidates: list[RetrievedChunk]) -> float | None:
    """후보 목록 안에 들어온 gold 비율(gold가 없으면 None)."""
    if not gold:
        return None
    return sum(any(gold_matcher(g)(c) for c in candidates) for g in gold) / len(gold)


# ---------------------------------------------------------------------------
# 집계
# ---------------------------------------------------------------------------
def aggregate(results: Iterable[QuestionResult]) -> dict[str, float | int]:
    """검색 지표 평균. `should_refuse` 문항은 제외, Full-Recall@5는 gold 2개 이상 문항만."""
    rs = [r for r in results if not r.should_refuse]
    if not rs:
        return {"n": 0}
    multi = [r for r in rs if len(r.gold) >= 2]
    out: dict[str, float | int] = {"n": len(rs)}
    for k in KS:
        out[f"hit@{k}"] = sum(r.hit(k) for r in rs) / len(rs)
    out["recall@5"] = sum(r.recall(5) for r in rs) / len(rs)
    out["full_recall@5"] = (
        sum(r.recall(5) == 1.0 for r in multi) / len(multi) if multi else float("nan")
    )
    out["recall@ctx"] = sum(r.recall() for r in rs) / len(rs)
    out["full_recall@ctx"] = (
        sum(r.recall() == 1.0 for r in multi) / len(multi) if multi else float("nan")
    )
    out["avg_ctx_chunks"] = sum(len(r.retrieved) for r in rs) / len(rs)
    out["n_multi"] = len(multi)
    out["mrr"] = sum(1 / r.first_hit if r.first_hit else 0.0 for r in rs) / len(rs)
    cand = [r.candidate_recall for r in rs if r.candidate_recall is not None]
    if cand:
        out["cand_hit"] = sum(c > 0 for c in cand) / len(
            cand
        )  # 후보 안에 gold가 하나라도
        out["cand_recall"] = sum(cand) / len(cand)
    return {k: round(v, 4) if isinstance(v, float) else v for k, v in out.items()}


def summarize(results: list[QuestionResult]) -> dict[str, Any]:
    """전체·유형별 지표와 p50 지연."""
    by_type: dict[str, list[QuestionResult]] = defaultdict(list)
    for r in results:
        by_type[r.type].append(r)
    return {
        "overall": aggregate(results),
        "by_type": {
            t: aggregate(by_type[t])
            for t in TYPES
            if t in by_type and t != "out_of_scope"
        },
        "p50_latency_ms": round(statistics.median(r.latency_ms for r in results), 1)
        if results
        else None,
        "p50_query_prep_ms": round(
            statistics.median(r.query_prep_ms for r in results), 1
        )
        if results
        else None,
        "refusal_top1_scores": [
            r.retrieved[0]["score"] for r in results if r.should_refuse and r.retrieved
        ],
    }


# ---------------------------------------------------------------------------
# 골든셋
# ---------------------------------------------------------------------------
def load_golden(path: Path = GOLDEN_PATH, split: str = "dev") -> list[dict[str, Any]]:
    """골든셋을 읽어 split으로 거른다(`all`이면 전체)."""
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [q for q in rows if split == "all" or q["split"] == split]


def validate_golden(rows: list[dict[str, Any]]) -> list[str]:
    """스키마·gold 형식 오류 목록(비어 있으면 정상)."""
    errors: list[str] = []
    seen: set[str] = set()
    for q in rows:
        qid = q.get("id", "?")
        if missing := REQUIRED - q.keys():
            errors.append(f"{qid}: 필드 누락 {sorted(missing)}")
        if qid in seen:
            errors.append(f"{qid}: id 중복")
        seen.add(qid)
        if q.get("type") not in TYPES:
            errors.append(f"{qid}: 알 수 없는 type {q.get('type')}")
        for g in q.get("gold", []):
            try:
                gold_matcher(g)
            except ValueError as e:
                errors.append(f"{qid}: {e}")
        if bool(q.get("should_refuse")) == bool(q.get("gold")):
            errors.append(f"{qid}: should_refuse와 gold 유무가 맞지 않음")
    return errors


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
def run(cfg: RetrievalConfig, questions: list[dict[str, Any]]) -> list[QuestionResult]:
    """프리셋 하나로 모든 문항을 검색·채점한다.

    질의 준비(Term expansion·Multi-Query LLM 호출)는 문항별로 먼저 하고 `query_prep_ms`에 따로 기록한다.
    모든 질의 임베딩은 한 번의 배치로 캐시에 넣는다(게이트웨이 분당 요청 한도 대응).
    따라서 latency_ms에는 LLM·임베딩 API 시간이 포함되지 않는다. BM25·CrossEncoder 로딩도 미리 끝낸다.
    """
    prepared: list[tuple[list[str], float]] = []
    for q in questions:
        start = time.perf_counter()
        queries = prepare_queries(q["question"], cfg)
        prepared.append((queries, (time.perf_counter() - start) * 1000))
    get_embedding_cache().embed(
        list(dict.fromkeys(x for queries, _ in prepared for x in queries))
    )
    warmup(cfg)
    results = []
    for q, (queries, prep_ms) in zip(questions, prepared, strict=True):
        start = time.perf_counter()
        trace = retrieve_with_trace(q["question"], cfg, queries=queries)
        latency = (time.perf_counter() - start) * 1000
        result = score_question(q, trace.results, latency)
        result.candidate_recall = candidate_recall(q["gold"], trace.candidates)
        result.queries = queries
        result.query_prep_ms = prep_ms
        results.append(result)
    return results


def save(
    cfg: RetrievalConfig,
    split: str,
    results: list[QuestionResult],
    usage: Usage | None = None,
) -> Path:
    """결과 JSON을 eval/results/{timestamp}_{config}.json으로 저장한다(덮어쓰지 않음)."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{datetime.now().astimezone():%Y%m%d-%H%M%S}_{cfg.name}.json"
    payload = {
        "config": asdict(cfg),
        "split": split,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": summarize(results),
        "usage": (usage or Usage()).to_dict(),
        "questions": [asdict(r) for r in results],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _fmt_row(name: str, s: dict[str, Any]) -> str:
    o = s["overall"]
    cols = [
        o.get("hit@1"),
        o.get("hit@3"),
        o.get("hit@5"),
        o.get("full_recall@5"),
        o.get("mrr"),
        o.get("cand_recall", float("nan")),
        o.get("full_recall@ctx"),
        o.get("avg_ctx_chunks"),
    ]
    return (
        f"| {name} | "
        + " | ".join(f"{c:.3f}" for c in cols)
        + f" | {s['p50_latency_ms']:.0f}ms |"
    )


def main() -> None:
    """CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", default="baseline", help="프리셋 이름(쉼표로 여러 개)"
    )
    parser.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--limit", type=int, help="앞에서 N문항만(개발 중 빠른 확인용)")
    parser.add_argument(
        "--answer",
        action="store_true",
        help="답변 생성 + LLM judge (최종 후보 config에만, DESIGN §9)",
    )
    parser.add_argument("--yes", action="store_true", help="--answer 예산 확인 생략")
    args = parser.parse_args()

    questions = load_golden(split=args.split)[: args.limit]
    if errors := validate_golden(load_golden(split="all")):
        raise SystemExit("골든셋 오류:\n" + "\n".join(errors))
    if args.validate_only:
        print(f"골든셋 정상: {args.split} {len(questions)}문항")
        return

    print(
        "| config | Hit@1 | Hit@3 | Hit@5 | Full-R@5 | MRR | Cand-R | Full-R@ctx | ctx | p50 |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|")
    for name in args.config.split(","):
        cfg = get_preset(name)
        before = tracker.snapshot()
        results = run(cfg, questions)
        usage = tracker.snapshot() - before
        path = save(cfg, args.split, results, usage)
        record("eval_retrieval", name, usage)
        print(_fmt_row(name, summarize(results)), f"→ {path.relative_to(PROJECT_ROOT)}")
        if args.answer:
            run_answer_eval(cfg, args.split, questions, yes=args.yes)


def run_answer_eval(
    cfg: RetrievalConfig, split: str, questions: list[dict[str, Any]], yes: bool
) -> Path | None:
    """답변 평가: 예산 가드 → 답변·judge → `{timestamp}_{config}_answer.json` + 장부 기록."""
    plans = answer_eval.plan(cfg, questions)
    if not answer_eval.check_budget(answer_eval.estimate(plans), yes=yes):
        print(f"{cfg.name}: 답변 평가 건너뜀")
        return None
    before = tracker.snapshot()
    results = answer_eval.run_answers(cfg, plans)
    usage = tracker.snapshot() - before
    record("eval_answer", cfg.name, usage)
    summary = answer_eval.summarize_answers(results)
    by_type: dict[str, list[answer_eval.AnswerResult]] = defaultdict(list)
    for r in results:
        by_type[r.type].append(r)
    path = RESULTS_DIR / (
        f"{datetime.now().astimezone():%Y%m%d-%H%M%S}_{cfg.name}_answer.json"
    )
    payload = {
        "config": asdict(cfg),
        "split": split,
        "judge_model": answer_eval.JUDGE_MODEL,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": summary,
        "by_type": {t: answer_eval.summarize_answers(rs) for t, rs in by_type.items()},
        "usage": usage.to_dict(),
        "questions": [asdict(r) for r in results],
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"{cfg.name} 답변: " + json.dumps(summary, ensure_ascii=False),
        f"→ {path.relative_to(PROJECT_ROOT)}",
    )
    return path


if __name__ == "__main__":
    main()
