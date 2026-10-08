"""원천별 구조 청킹 → `Chunk[]` + 참조·위임 메타 + 위임 그래프.

payload 스키마는 `docs/DESIGN.md §3.3`, chunk_id·citation 규칙은 `/law-structure` 스킬이 기준.
사용: uv run python -m rag.chunker [--dry-run] [--sources law,decree,annex,admrul,term]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from common.config import PROCESSED_DIR
from common.law_api import Article, Item
from rag.annex_parser import AnnexSection, parse_annex
from rag.legal_text import (
    ADMRUL_ART,
    DelegationSource,
    article_ref,
    extract_amendments,
    find_addendum_sources,
    find_delegation_sources,
    find_refs,
    is_delegating,
    paragraph_no,
    strip_amendments,
)
from rag.loader import SOURCE_TYPES, LawDocument, load_documents

logger = logging.getLogger(__name__)

SOURCE_LABEL = {
    "law": "법률",
    "decree": "시행령",
    "annex": "시행령 별표",
    "admrul": "고시",
    "term": "법령용어",
}
DOC_SHORT = {
    "law": "법",
    "decree": "영",
    "annex": "별표",
    "admrul": "고시",
    "term": "용어",
}
PRIORITY = {"law": 1, "decree": 1, "annex": 2, "admrul": 2, "term": 3}

MAX_ARTICLE_CHARS = 700  # 넘으면 항(없으면 호) 단위로 나눈다
ITEM_LEVEL_ARTICLES = {("law", 2)}  # 정의 조항: 길이와 무관하게 호 단위
NOTE_SECTION_HEADINGS = ("일반기준",)  # 별표에서 1청크로 두는 구역
HEADING = re.compile(r"^제(\d+)(장|절)\s*(.*)")
ANNEX_PARENT = re.compile(r"\(제(\d+)조(?:의(\d+))?(?:제\d+항)?\s*관련\)")
ADMRUL_BASIS_TITLE = "목적"  # 고시는 제1조(목적)에 적힌 법·영 조항만 위임 근거로 본다


@dataclass
class Chunk:
    """Qdrant payload (DESIGN §3.3)."""

    chunk_id: str
    source_type: str
    doc_id: str
    doc_title: str
    doc_short: str
    chunk_type: str  # article|paragraph|item|addendum|annex_item|annex_note|annex_row|admrul_article|term
    text: str
    embed_text: str
    parent_text: str
    article_key: (
        str  # 조 단위 키: law:a31, decree:a22_2, annex:2, admrul:{ID}-a3, term:{용어}
    )
    citation: str
    priority: int
    chapter: str | None = None
    section: str | None = None
    article_no: int | None = None
    article_sub: int = 0
    article: str | None = None  # "제31조", "별표 2", "부칙"
    article_title: str | None = None
    paragraph: str | None = None  # "②"
    item: str | None = None  # "4."
    effective_date: str | None = None
    refs: list[str] = field(default_factory=list)  # article_key 목록
    delegated: bool = False
    delegates_to: list[str] = field(default_factory=list)  # 하위 법령 article_key
    delegated_from: list[str] = field(default_factory=list)  # 상위 법령 article_key
    amended: list[str] = field(default_factory=list)  # <개정 ...> 표시 원문
    covers: list[str] = field(
        default_factory=list
    )  # naive 청크가 걸친 조 키(평가용, 구조 청크는 [])


def _date(yyyymmdd: str | None) -> str | None:
    s = (yyyymmdd or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else None


def _header(*parts: str | None) -> str:
    return "[" + " > ".join(p for p in parts if p) + "]"


def _new_chunk(
    doc: LawDocument,
    *,
    header: str,
    text: str,
    embed_body: str | None = None,
    self_ref: str | None = None,
    **fields: Any,
) -> Chunk:
    """문서 공통 필드와 텍스트 파생 필드(embed_text·refs·delegated·amended)를 채워 Chunk를 만든다."""
    src = doc.source_type
    fields.setdefault("doc_title", doc.title)
    fields.setdefault("refs", find_refs(text, src, self_ref=self_ref))
    fields.setdefault("delegated", is_delegating(text))
    return Chunk(
        source_type=src,
        doc_id=doc.doc_id,
        doc_short=DOC_SHORT[src],
        priority=PRIORITY[src],
        text=text,
        embed_text=strip_amendments(f"{header} {embed_body or text}"),
        amended=extract_amendments(text),
        **fields,
    )


# ---------------------------------------------------------------------------
# 법률·시행령
# ---------------------------------------------------------------------------
def _item_text(item: Item) -> str:
    return "\n".join([item.text, *[c.text for c in item.children]])


def article_text(a: Article) -> str:
    """조 전체 텍스트(머리+항+호+목)."""
    lines = [a.content]
    for p in a.paragraphs:
        lines.append(p.text)
        lines += [_item_text(i) for i in p.items]
    lines += [_item_text(i) for i in a.items]
    return "\n".join(line for line in lines if line)


def _is_deleted(a: Article) -> bool:
    return not a.paragraphs and not a.items and bool(re.search(r"삭제\s*<", a.content))


def _article_chunks(
    doc: LawDocument, a: Article, context: dict[str, Any]
) -> list[Chunk]:
    """조 1개 → 조/항/호 청크. `context`는 장·절 등 조 공통 필드."""
    src = doc.source_type
    label = f"제{a.no}조" + (f"의{a.sub}" if a.sub else "")
    key = article_ref(src, a.no, a.sub)
    local = key.split(":", 1)[1]
    full = article_text(a)
    title_head = f"{label}({a.title})" if a.title else label
    base_cite = f"{DOC_SHORT[src]} {label}"
    common = {
        **context,
        "self_ref": key,
        "article_key": key,
        "article_no": a.no,
        "article_sub": a.sub,
        "article": label,
        "article_title": a.title or None,
        "parent_text": full,
        "effective_date": _date(a.effective_date),
    }

    item_level = (src, a.no) in ITEM_LEVEL_ARTICLES or (
        len(full) > MAX_ARTICLE_CHARS and not a.paragraphs and a.items
    )
    if item_level and a.items:
        # 도입 문장("…이란 다음 각 호에 해당하는 …")은 조문내용에 있으므로 호마다 앞에 붙인다
        return [
            _new_chunk(
                doc,
                **common,
                chunk_id=f"{src}:{local}-i{it.no.rstrip('.')}",
                chunk_type="item",
                item=it.no,
                text=f"{a.content}\n{_item_text(it)}",
                citation=f"{base_cite} 제{it.no.rstrip('.')}호",
            )
            for it in a.items
        ]
    if len(full) > MAX_ARTICLE_CHARS and a.paragraphs:
        chunks = []
        for p in a.paragraphs:
            n = paragraph_no(p.no)
            text = "\n".join([p.text, *[_item_text(i) for i in p.items]])
            chunks.append(
                _new_chunk(
                    doc,
                    **common,
                    chunk_id=f"{src}:{local}-p{n}",
                    chunk_type="paragraph",
                    paragraph=p.no,
                    text=text,
                    embed_body=f"{title_head} {text}",
                    citation=f"{base_cite} 제{n}항",
                )
            )
        return chunks
    return [
        _new_chunk(
            doc,
            **common,
            chunk_id=f"{src}:{local}",
            chunk_type="article",
            text=full,
            citation=base_cite,
        )
    ]


def chunk_law_document(doc: LawDocument) -> list[Chunk]:
    """법률·시행령: 조(≤700자) / 항(>700자) / 호(정의 조항·항 없는 긴 조), 부칙 1건 = 1청크."""
    src = doc.source_type
    chunks: list[Chunk] = []
    chapter: str | None = None
    section: str | None = None
    for a in doc.units:
        if a.is_heading:
            if m := HEADING.match(a.content):
                chapter, section = (
                    (a.content, None) if m[2] == "장" else (chapter, a.content)
                )
            continue
        if _is_deleted(a):
            continue
        header = _header(SOURCE_LABEL[src], chapter, section)
        context = {"header": header, "chapter": chapter, "section": section}
        chunks += _article_chunks(doc, a, context)

    for i, add in enumerate(doc.addenda, start=1):
        label = f"부칙 <제{add['promulgation_no']}호>"
        chunks.append(
            _new_chunk(
                doc,
                header=f"[{SOURCE_LABEL[src]} {label}]",
                text=add["text"],
                chunk_id=f"{src}:add{i}",
                chunk_type="addendum",
                parent_text=add["text"],
                article_key=f"{src}:add{i}",
                article="부칙",
                article_title=label,
                citation=f"{DOC_SHORT[src]} {label}",
                effective_date=_date(add["promulgation_date"]),
                refs=[],  # 부칙의 "제N조"는 부칙 자신의 조라 본문 참조로 보지 않는다
            )
        )
    return chunks


# ---------------------------------------------------------------------------
# 별표
# ---------------------------------------------------------------------------
def _table_text(sec: AnnexSection) -> str:
    t = sec.table
    assert t is not None
    unit = f"(단위: {t.unit})\n" if t.unit else ""
    return unit + "\n".join(" | ".join(r) for r in [t.headers, *t.rows])


def chunk_annex_document(doc: LawDocument) -> list[Chunk]:
    """별표: 번호·목 단위(별표 1) / 일반기준 1청크 + 개별기준 표 행 1개 = 1청크(별표 2)."""
    parsed = parse_annex(doc.units[0]["text"])
    n = parsed.number or doc.meta["number"]
    short_title = doc.meta.get("short_title") or parsed.title
    parent = ANNEX_PARENT.search(parsed.title)
    delegated_from = [article_ref("decree", parent[1], parent[2])] if parent else []
    common = {
        "doc_title": doc.meta["parent_title"],
        "article_key": f"annex:{n}",
        "article": f"별표 {n}",
        "article_title": parsed.title,
        "citation": f"영 별표 {n}",
        "effective_date": _date(doc.meta.get("effective_date")),
    }

    def make(
        local: str, chunk_type: str, sec: AnnexSection, text: str, parent_text: str
    ) -> Chunk:
        heading = (
            f"{sec.number}. {sec.heading}"
            if sec.number and len(sec.heading) < 30
            else None
        )
        return _new_chunk(
            doc,
            **common,
            header=_header(f"시행령 별표 {n} {short_title}", heading),
            text=text,
            chunk_id=f"annex:{local}",
            chunk_type=chunk_type,
            parent_text=parent_text,
            delegated_from=list(delegated_from),
        )

    chunks: list[Chunk] = []
    row_no = 0
    for sec in parsed.sections:
        if (t := sec.table) is not None:
            unit = f" (단위: {t.unit})" if t.unit else ""
            for row in t.rows:
                row_no += 1
                text = f"{parsed.title} > {sec.heading}{unit}\n{' | '.join(t.headers)}\n{' | '.join(row)}"
                chunks.append(
                    make(f"{n}-r{row_no}", "annex_row", sec, text, _table_text(sec))
                )
        elif sec.heading in NOTE_SECTION_HEADINGS:
            chunks.append(make(f"{n}-note", "annex_note", sec, sec.text, sec.text))
        else:
            for item in sec.items:
                local = f"{n}-{sec.number}" + (f"-{item.sub}" if item.sub else "")
                text = "\n".join(t for t in (item.intro, item.text) if t)
                chunks.append(make(local, "annex_item", sec, text, sec.text))
    return chunks


# ---------------------------------------------------------------------------
# 행정규칙·용어
# ---------------------------------------------------------------------------
def _format_admrul(text: str) -> str:
    """줄바꿈 없이 이어 붙은 항(①)·호(1.) 앞에 줄바꿈을 넣는다."""
    text = re.sub(r"(?<=\S)\s*(?=[①-⑳])", "\n", text)
    return re.sub(r"(?<=[가-힣.])(?=\d{1,2}\.\s)", "\n", text)


def chunk_admrul_document(doc: LawDocument) -> list[Chunk]:
    """행정규칙: 조 1개 = 1청크 (`조문내용` 문자열 1개 = 조 1개)."""
    short = doc.meta.get("short_name") or doc.title
    # 위임 근거는 제1조(목적)에 적힌 법·영 조항 → 고시 전체 조가 공유한다
    basis: list[str] = []
    for unit in doc.units:
        m = ADMRUL_ART.match(unit["text"])
        if m and m[3] == ADMRUL_BASIS_TITLE:
            basis = [
                r
                for r in find_refs(unit["text"], "admrul")
                if r.startswith(("law:", "decree:"))
            ]
    chunks: list[Chunk] = []
    for unit in doc.units:
        m = ADMRUL_ART.match(unit["text"])
        if m is None:
            logger.warning("고시 조 머리를 찾지 못함: %s", unit["text"][:40])
            continue
        no, sub = int(m[1]), int(m[2] or 0)
        label = f"제{no}조" + (f"의{sub}" if sub else "")
        key = f"admrul:{doc.doc_id}-a{no}" + (f"_{sub}" if sub else "")
        text = _format_admrul(unit["text"])
        refs = find_refs(text, "admrul")
        chunks.append(
            _new_chunk(
                doc,
                header=f"[고시: {doc.title}]",
                text=text,
                chunk_id=key,
                chunk_type="admrul_article",
                parent_text=text,
                article_key=key,
                article_no=no,
                article_sub=sub,
                article=label,
                article_title=m[3],
                citation=f"고시 {short} {label}",
                effective_date=_date(doc.meta.get("effective_date")),
                refs=refs,
                delegated_from=list(basis),
            )
        )
    return chunks


def chunk_term_document(doc: LawDocument) -> list[Chunk]:
    """법령용어: 용어 1개 = 1청크 (인공지능기본법 출처 정의만, loader에서 필터)."""
    term = doc.title
    text = "\n".join(
        f"{term}: {u['definition']} (출처: {u['source']})" for u in doc.units
    )
    key = f"term:{term}"
    return [
        _new_chunk(
            doc,
            header=f"[법령용어 > {term}]",
            text=text,
            chunk_id=key,
            chunk_type="term",
            parent_text=text,
            article_key=key,
            article_title=term,
            citation=f"법령용어 {term}",
            refs=[],
            delegated=False,
        )
    ]


def naive_chunks(doc: LawDocument, size: int = 500) -> list[Chunk]:
    """비교용(E0): 법령 조문 텍스트를 이어 붙인 뒤 고정 `size`자로 자른다. 헤더·구조 메타 없음."""
    src = doc.source_type
    spans: list[tuple[int, int, str, str]] = []  # (start, end, article_key, label)
    parts: list[str] = []
    pos = 0
    for a in doc.units:
        if a.is_heading or _is_deleted(a):
            continue
        text = article_text(a)
        label = f"제{a.no}조" + (f"의{a.sub}" if a.sub else "")
        spans.append((pos, pos + len(text), article_ref(src, a.no, a.sub), label))
        parts.append(text)
        pos += len(text) + 1
    full = "\n".join(parts)

    chunks = []
    for i, start in enumerate(range(0, len(full), size), start=1):
        end = min(start + size, len(full))
        covered = [(k, lb) for s, e, k, lb in spans if s < end and e > start]
        text = full[start:end]
        labels = [lb for _, lb in covered]
        chunks.append(
            _new_chunk(
                doc,
                header="",
                text=text,
                embed_body=text,
                chunk_id=f"{src}:naive-{i:03d}",
                chunk_type="naive",
                parent_text=text,
                article_key=covered[0][0],
                citation=f"{DOC_SHORT[src]} "
                + (labels[0] if len(labels) == 1 else f"{labels[0]}~{labels[-1]}"),
                covers=[k for k, _ in covered],
                refs=[],
                delegated=False,
            )
        )
    return chunks


CHUNKERS = {
    "law": chunk_law_document,
    "decree": chunk_law_document,
    "annex": chunk_annex_document,
    "admrul": chunk_admrul_document,
    "term": chunk_term_document,
}


# ---------------------------------------------------------------------------
# 위임 연결 (DESIGN §3.4)
# ---------------------------------------------------------------------------
def _pick_parents(
    candidates: list[Chunk], child_key: str, src: DelegationSource
) -> list[Chunk]:
    """위임 근거 조의 청크 중 실제로 위임하는(`delegated`) 청크를 고른다.

    ① 하위 키를 refs에 가진 청크(예: "별표 2와 같다") ② 항·호가 일치하는 delegated 청크
    ③ 항만 지정됐으면 같은 조의 delegated 청크("제2항에 따른 … 필요한 사항은 대통령령으로") ④ 없으면 []
    """
    if picked := [c for c in candidates if child_key in c.refs]:
        return picked
    if src.item is not None:
        items = [
            c for c in candidates if c.item and int(c.item.rstrip(".")) == src.item
        ]
        if items:  # 호 단위 청크가 있으면 그 호만 본다(다른 호는 별개 개념)
            return [c for c in items if c.delegated]
    if src.paragraph is not None:
        paras = [
            c
            for c in candidates
            if c.paragraph and paragraph_no(c.paragraph) == src.paragraph
        ]
        if picked := [c for c in paras if c.delegated]:
            return picked
    return [c for c in candidates if c.delegated]


def link_delegations(chunks: list[Chunk]) -> list[dict[str, str]]:
    """하위 청크의 위임 근거를 찾아 `delegated_from`/`delegates_to`를 채우고 간선 목록을 반환한다.

    - 시행령: 본문의 `법 제N조…에 따라/에서 "…대통령령으로 정하는"`(근거 청크가 delegated일 때만)
    - 시행령 부칙: `법률 제N호 … 부칙 제M조에서 "…대통령령으로"` → 법률 부칙
    - 별표·고시: 청킹 때 정한 `delegated_from`(별표 제목 "(제N조 관련)", 고시 제1조)
    """
    by_key: dict[str, list[Chunk]] = defaultdict(list)
    for c in chunks:
        by_key[c.article_key].append(c)
    law_addenda = {
        c.article_title: c.article_key
        for c in chunks
        if c.source_type == "law" and c.chunk_type == "addendum"
    }

    edges: dict[tuple[str, str], str] = {}
    for c in chunks:
        static = [DelegationSource(k) for k in c.delegated_from]
        found: list[DelegationSource] = []
        if c.source_type == "decree" and c.chunk_type == "addendum":
            found = [
                DelegationSource(law_addenda[f"부칙 <제{no}호>"])
                for no in find_addendum_sources(c.text)
                if f"부칙 <제{no}호>" in law_addenda
            ]
        elif c.source_type == "decree":
            found = find_delegation_sources(c.text)
        for src in static + found:
            parents = _pick_parents(by_key.get(src.key, []), c.article_key, src)
            if not parents and src not in static:
                continue  # 근거 조에 위임 문장이 없으면 단순 인용(참조)으로 본다
            if src.key not in c.delegated_from:
                c.delegated_from.append(src.key)
            for p in parents:
                if c.article_key not in p.delegates_to:
                    p.delegates_to.append(c.article_key)
            edges[(src.key, c.article_key)] = "delegation"
        for r in c.refs:
            edges.setdefault((c.article_key, r), "ref")
    return [{"from": a, "to": b, "type": t} for (a, b), t in edges.items()]


def build_graph(chunks: list[Chunk], edges: list[dict[str, str]]) -> dict:
    """조 단위 노드 + 위임·참조 간선 (발표용 시각화 재료)."""
    nodes: dict[str, dict] = {}
    for c in chunks:
        if c.article_key not in nodes:
            label = (
                f"{c.doc_short} {c.article}"
                if c.source_type in ("law", "decree")
                else c.citation
            )
            nodes[c.article_key] = {
                "key": c.article_key,
                "source_type": c.source_type,
                "label": label,
                "title": c.article_title,
                "delegated": False,
            }
        nodes[c.article_key]["delegated"] |= c.delegated
    known = [e for e in edges if e["from"] in nodes and e["to"] in nodes]
    return {"nodes": list(nodes.values()), "edges": known}


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------
def chunk_documents(docs: Iterable[LawDocument]) -> tuple[list[Chunk], dict]:
    """문서들을 청킹하고 위임 연결까지 마친 청크와 위임 그래프를 반환한다."""
    chunks = [c for d in docs for c in CHUNKERS[d.source_type](d)]
    if dup := [k for k, v in Counter(c.chunk_id for c in chunks).items() if v > 1]:
        raise ValueError(f"chunk_id 중복: {dup}")
    edges = link_delegations(chunks)
    return chunks, build_graph(chunks, edges)


def write_outputs(
    chunks: list[Chunk], graph: dict, out_dir: Path = PROCESSED_DIR
) -> None:
    """chunks.jsonl, delegation_graph.json을 저장한다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
    (out_dir / "delegation_graph.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def load_chunks(path: Path = PROCESSED_DIR / "chunks.jsonl") -> list[Chunk]:
    """저장된 chunks.jsonl을 읽는다."""
    with path.open(encoding="utf-8") as f:
        return [Chunk(**json.loads(line)) for line in f if line.strip()]


def main() -> None:
    """CLI: 캐시에서 문서를 읽어 청킹 결과를 data/processed/에 저장하고 요약을 출력한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="청킹만 (적재 없음) + 샘플 출력"
    )
    parser.add_argument("--sources", default=",".join(SOURCE_TYPES))
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    chunks, graph = chunk_documents(load_documents(only=args.sources.split(",")))
    write_outputs(chunks, graph)
    print("청크 수:", dict(Counter(c.source_type for c in chunks)))
    print("유형별:", dict(Counter(c.chunk_type for c in chunks)))
    delegation = [e for e in graph["edges"] if e["type"] == "delegation"]
    print(
        f"위임 간선 {len(delegation)}개, 참조 간선 {len(graph['edges']) - len(delegation)}개"
    )
    if args.dry_run:
        for c in chunks[:: max(1, len(chunks) // 8)]:
            print(f"- {c.chunk_id} [{c.citation}] {c.embed_text[:100]}")


if __name__ == "__main__":
    main()
