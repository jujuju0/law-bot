"""시행령 별표 `별표내용`(고정폭 텍스트, 표는 box-drawing 문자) 파서. 규칙은 DESIGN §3.2 "별표 파싱"."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from rag.legal_text import join_wrapped, merge_wrapped_lines

logger = logging.getLogger(__name__)

HEADER_MARK = re.compile(r"^■.*\[별표\s*(\d+)\]")
EFFECTIVE_NOTE = re.compile(r"^\[시행일:[^\]]*\].*")
TOP_NUMBER = re.compile(r"^(\d+)\.\s*(.*)")
SUB_NUMBER = re.compile(r"^([가-하])\.\s*(.*)")
UNIT_NOTE = re.compile(r"^\(단위:\s*([^)]+)\)")
TABLE_START, TABLE_END, TABLE_SPLIT = "┌", "└", "├"
CELL_SEP = "│"
BOX_RULE = re.compile(r"[─━┬┴┼├┤┌┐└┘]")
BROKEN_CHAR = re.compile(r"[가-힣]\?[가-힣]")


@dataclass
class AnnexItem:
    """번호 단위 블록: `1.` 아래 `가.` 1개(세목 1) 포함). 목이 없는 번호는 sub=None."""

    number: str  # "1"
    sub: str | None  # "가"
    intro: str  # 상위 번호의 도입 문장 ("1. ... 본다.")
    text: str  # 목 텍스트 (세목은 줄바꿈으로 이어짐)


@dataclass
class AnnexTable:
    """표: 열 머리글과 행(셀 텍스트 리스트)."""

    headers: list[str]
    rows: list[list[str]]
    unit: str | None = None  # "만원"


@dataclass
class AnnexSection:
    """최상위 번호(`1. 일반기준`) 단위 구역."""

    number: str
    heading: str
    items: list[AnnexItem] = field(default_factory=list)
    table: AnnexTable | None = None
    text: str = ""  # 구역 전체 텍스트(표 제외)


@dataclass
class ParsedAnnex:
    """별표 1개의 파싱 결과."""

    number: int
    title: str
    effective_note: str | None
    sections: list[AnnexSection]
    warnings: list[str] = field(default_factory=list)


def parse_annex(raw_text: str) -> ParsedAnnex:
    """`as_text(별표내용)`을 머리 메타·번호 구역·표로 파싱한다."""
    lines = raw_text.splitlines()
    number, effective_note, title = 0, None, ""
    body_start = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if m := HEADER_MARK.match(s):
            number = int(m[1])
        elif EFFECTIVE_NOTE.match(s):
            effective_note = s
        elif not title and s:
            title = s
        else:
            body_start = i
            break
    warnings = [
        f"별표 {number}: 깨진 문자 의심 '{m.group(0)}' (원문 ㆍ→? , DESIGN §2.4)"
        for m in BROKEN_CHAR.finditer(raw_text)
    ]
    for w in warnings:
        logger.warning(w)
    sections = _split_sections(lines[body_start:])
    return ParsedAnnex(number, title, effective_note, sections, warnings)


def _split_sections(lines: list[str]) -> list[AnnexSection]:
    sections: list[AnnexSection] = []
    buffer: list[str] = []
    table_lines: list[str] = []
    in_table = False
    unit: str | None = None

    def flush() -> None:
        if not buffer:
            return
        merged = merge_wrapped_lines(buffer)
        head = TOP_NUMBER.match(merged[0])
        if head is None:  # 번호 없는 본문(드묾) → 단일 구역
            sections.append(AnnexSection("", "", text="\n".join(merged)))
        else:
            sec = AnnexSection(head[1], head[2], text="\n".join(merged))
            sec.items = _items(head[1], merged)
            sections.append(sec)
        buffer.clear()

    for line in lines:
        s = line.strip()
        if in_table:
            table_lines.append(line)
            if s.startswith(TABLE_END):
                in_table = False
                if sections:
                    sections[-1].table = _parse_table(table_lines, unit)
                table_lines.clear()
            continue
        if s.startswith(TABLE_START):
            flush()
            in_table = True
            table_lines.append(line)
            continue
        if m := UNIT_NOTE.match(s):
            unit = m[1].strip()
            continue
        if TOP_NUMBER.match(s) and buffer:
            flush()
        buffer.append(line)
    flush()
    return sections


def _items(number: str, merged: list[str]) -> list[AnnexItem]:
    """구역의 논리 줄에서 `가.` 목 단위 블록을 만든다. 세목(1))은 목에 포함."""
    intro = merged[0]
    items: list[AnnexItem] = []
    for line in merged[1:]:
        if m := SUB_NUMBER.match(line):
            items.append(AnnexItem(number, m[1], intro, line))
        elif items:
            items[-1].text += "\n" + line
        else:
            intro += "\n" + line
    if not items:
        items.append(AnnexItem(number, None, intro, ""))
    return items


def _cells(line: str) -> list[str]:
    parts = line.strip().split(CELL_SEP)
    return [p for p in parts[1:-1]] if line.strip().endswith(CELL_SEP) else parts[1:]


def _parse_table(lines: list[str], unit: str | None) -> AnnexTable:
    """box-drawing 표를 머리글/행으로 나눈다. 행 경계 = 목 번호로 시작하는 첫 칸 또는 빈 줄."""
    split = next(i for i, ln in enumerate(lines) if ln.strip().startswith(TABLE_SPLIT))
    ncols = lines[split].count("┼") + 1

    header_parts: list[list[str]] = [[] for _ in range(ncols)]
    for line in lines[1:split]:
        if not line.strip().startswith(CELL_SEP):
            continue
        cells = [c for c in _cells(line) if not BOX_RULE.search(c)]
        if len(cells) == ncols:
            for col, c in enumerate(cells):
                if c.strip():
                    header_parts[col].append(c.strip())
        elif cells:
            # 열 수가 적은 줄: 앞 칸은 같은 열, 마지막 칸은 남은 열 전체의 묶음 머리글
            for col, c in enumerate(cells[:-1]):
                if c.strip():
                    header_parts[col].append(c.strip())
            group = cells[-1].strip()
            if group:
                for col in range(len(cells) - 1, ncols):
                    header_parts[col].insert(0, group)
    headers = [" ".join(p) for p in header_parts]

    rows: list[list[str]] = []
    current: list[str] | None = None
    for line in lines[split + 1 :]:
        if not line.strip().startswith(CELL_SEP):
            continue
        cells = [c.strip() for c in _cells(line)]
        cells += [""] * (ncols - len(cells))
        if not any(cells):
            current = None
            continue
        if current is None or SUB_NUMBER.match(cells[0]):
            current = [""] * ncols
            rows.append(current)
        for col, c in enumerate(cells[:ncols]):
            current[col] = join_wrapped(current[col], c)
    return AnnexTable(headers, rows, unit)
