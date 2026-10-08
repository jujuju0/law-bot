"""발표용 결과 정리 (T6.2): Ablation 표, 유형별 Hit@3 히트맵, 위임 그래프(Mermaid).

config마다 가장 최근 결과 JSON을 쓴다(`eval/results/{timestamp}_{config}.json`).
사용: uv run python -m eval.report [--split dev] [--chart] [--mermaid]
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

from common.config import PROCESSED_DIR, PROJECT_ROOT
from eval.evaluate import RESULTS_DIR, TYPES
from rag.config import PRESETS

REPORT_MD = RESULTS_DIR / "ablation.md"
CHART_PNG = RESULTS_DIR / "ablation_by_type.png"
MERMAID_MD = PROJECT_ROOT / "docs" / "delegation_graph.md"
TYPE_COLUMNS = [t for t in TYPES if t != "out_of_scope"]

# dataviz 기본 팔레트의 blue 순차 램프(100→700). 0 → 연함, 1 → 진함
BLUE_RAMP = [
    "#cde2fb",
    "#9ec5f4",
    "#6da7ec",
    "#3987e5",
    "#256abf",
    "#184f95",
    "#0d366b",
]
INK, INK_ON_DARK, SURFACE = "#1f1f1e", "#ffffff", "#ffffff"


def latest_results(split: str = "dev") -> dict[str, dict[str, Any]]:
    """config 이름 → 가장 최근 검색 평가 결과(프리셋 정의 순서)."""
    found: dict[str, tuple[str, dict[str, Any]]] = {}
    for path in sorted(RESULTS_DIR.glob("*.json")):
        if path.stem.endswith("_answer"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("split") != split:
            continue
        name = data["config"]["name"]
        found[name] = (path.name, data)  # 파일명 정렬 = 시간순 → 마지막이 최신
    order = {name: i for i, name in enumerate(PRESETS)}
    return {
        name: {**data, "file": fname}
        for name, (fname, data) in sorted(
            found.items(), key=lambda kv: order.get(kv[0], 999)
        )
    }


def _f(v: Any) -> str:
    return f"{v:.3f}" if isinstance(v, float) and not math.isnan(v) else "-"


def ablation_markdown(results: dict[str, dict[str, Any]]) -> str:
    """요약 표(전체 지표) + 유형별 Hit@3 표 + 직전 실험 대비 Δ."""
    head = "| config | sources | Hit@1 | Hit@3 | Hit@5 | MRR | Full-R@5 | Full-R@ctx | ctx | Cand-R | p50 |"
    lines = [head, "|---" * head.count(" | ") + "|---|"]
    prev = None
    for name, r in results.items():
        o = r["summary"]["overall"]
        delta = ""
        if prev is not None and "hit@3" in o:
            delta = f" ({o['hit@3'] - prev:+.3f})"
        prev = o.get("hit@3")
        lines.append(
            f"| {name} | {','.join(r['config']['sources'])} | {_f(o.get('hit@1'))} | "
            f"{_f(o.get('hit@3'))}{delta} | {_f(o.get('hit@5'))} | {_f(o.get('mrr'))} | "
            f"{_f(o.get('full_recall@5'))} | {_f(o.get('full_recall@ctx'))} | "
            f"{o.get('avg_ctx_chunks', '-')} | {_f(o.get('cand_recall'))} | "
            f"{r['summary'].get('p50_latency_ms')}ms |"
        )
    lines += ["", "유형별 Hit@3", "", "| config | " + " | ".join(TYPE_COLUMNS) + " |"]
    lines.append("|---" * (len(TYPE_COLUMNS) + 1) + "|")
    for name, r in results.items():
        by = r["summary"]["by_type"]
        lines.append(
            f"| {name} | "
            + " | ".join(_f(by.get(t, {}).get("hit@3")) for t in TYPE_COLUMNS)
            + " |"
        )
    files = ", ".join(f"`{r['file']}`" for r in results.values())
    return "\n".join(lines) + f"\n\n원본: {files}\n"


def heatmap(results: dict[str, dict[str, Any]], path: Path = CHART_PNG) -> Path:
    """실험(행) × 문항 유형(열) Hit@3 히트맵. 단일 hue 순차 램프, 칸마다 값 표기."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    names = list(results)
    grid = [
        [results[n]["summary"]["by_type"].get(t, {}).get("hit@3") for t in TYPE_COLUMNS]
        for n in names
    ]
    cmap = LinearSegmentedColormap.from_list("blue", BLUE_RAMP)
    fig, ax = plt.subplots(
        figsize=(1.3 * len(TYPE_COLUMNS) + 2, 0.5 * len(names) + 1.6)
    )
    fig.patch.set_facecolor(SURFACE)
    for i, row in enumerate(grid):
        for j, v in enumerate(row):
            color = cmap(v) if v is not None else "#f0efec"
            # 칸 사이 2px 표면 간격
            ax.add_patch(
                plt.Rectangle((j + 0.03, i + 0.05), 0.94, 0.9, color=color, lw=0)
            )
            label = f"{v:.2f}" if v is not None else "-"
            ax.text(
                j + 0.5,
                i + 0.5,
                label,
                ha="center",
                va="center",
                fontsize=9,
                color=INK_ON_DARK if v is not None and v >= 0.6 else INK,
            )
    ax.set_xlim(0, len(TYPE_COLUMNS))
    ax.set_ylim(len(names), 0)
    ax.set_xticks([j + 0.5 for j in range(len(TYPE_COLUMNS))], TYPE_COLUMNS, fontsize=9)
    ax.set_yticks([i + 0.5 for i in range(len(names))], names, fontsize=9)
    ax.tick_params(length=0, colors=INK)
    ax.xaxis.tick_top()
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title(
        "Hit@3 by question type (dev)", loc="left", color=INK, fontsize=11, pad=24
    )
    _korean_font(plt)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def _korean_font(plt: Any) -> None:
    """설치된 한글 폰트가 있으면 사용(없으면 기본 폰트 — 한글이 □로 보일 수 있음)."""
    from matplotlib import font_manager

    for name in (
        "Malgun Gothic",
        "AppleGothic",
        "NanumGothic",
        "Noto Sans CJK KR",
        "Noto Sans KR",
    ):
        if any(f.name == name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = name
            return


def delegation_mermaid(
    graph_path: Path = PROCESSED_DIR / "delegation_graph.json",
) -> str:
    """위임 간선만 Mermaid flowchart로(법 → 영 → 별표·고시). 원천별 subgraph."""
    g = json.loads(graph_path.read_text(encoding="utf-8"))
    labels = {n["key"]: n["label"] for n in g["nodes"]}
    titles = {n["key"]: n.get("title") or "" for n in g["nodes"]}
    edges = [e for e in g["edges"] if e["type"] == "delegation"]
    used = sorted(
        {k for e in edges for k in (e["from"], e["to"])},
        key=lambda k: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", k)],
    )

    def node_id(key: str) -> str:
        return key.replace(":", "_").replace("-", "_")

    groups = {"law": "법률", "decree": "시행령", "annex": "별표", "admrul": "고시"}
    out = ["```mermaid", "flowchart LR"]
    for src, title in groups.items():
        keys = [k for k in used if k.startswith(f"{src}:")]
        if not keys:
            continue
        out.append(f"  subgraph {src}[{title}]")
        for k in keys:
            label = labels.get(k, k)
            if titles.get(k):
                label += f"<br/>{titles[k]}"
            out.append(f'    {node_id(k)}["{label}"]')
        out.append("  end")
    out += [f"  {node_id(e['from'])} --> {node_id(e['to'])}" for e in edges]
    out.append("```")
    header = (
        "# 위임 그래프\n\n`data/processed/delegation_graph.json`의 위임 간선 "
        f"{len(edges)}개(법률 → 시행령 → 별표·고시). `uv run python -m eval.report --mermaid`로 재생성.\n\n"
    )
    return header + "\n".join(out) + "\n"


def main() -> None:
    """CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", default="dev")
    parser.add_argument(
        "--chart", action="store_true", help=f"히트맵 PNG → {CHART_PNG.name}"
    )
    parser.add_argument(
        "--mermaid", action="store_true", help="위임 그래프 → docs/delegation_graph.md"
    )
    args = parser.parse_args()
    results = latest_results(args.split)
    md = ablation_markdown(results)
    REPORT_MD.write_text(md, encoding="utf-8")
    print(md)
    if args.chart:
        print("→", heatmap(results).relative_to(PROJECT_ROOT))
    if args.mermaid:
        MERMAID_MD.write_text(delegation_mermaid(), encoding="utf-8")
        print("→", MERMAID_MD.relative_to(PROJECT_ROOT))


if __name__ == "__main__":
    main()
