"""법령 본문 텍스트 유틸: 참조·위임 탐지 정규식, 개정 표시, 고정폭 줄 병합.

정규식 기준은 `.claude/skills/law-structure/SKILL.md`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rag.korean import get_kiwi

# 개정 표시: <개정 2026.1.20>, <개정 2026.7.20, 2026.8.18>, <신설 2026. 1. 20.>, [제목개정 ...]
AMEND = re.compile(
    r"<(개정|신설|전문개정)\s*([\d.,\s]+)>|\[(?:본조신설|제목개정|전문개정)[^\]]*\]"
)
DELEGATE = re.compile(
    r"대통령령으로\s*정(한다|하는|하여)|고시(하여야|하고|한다|하는)|정하여\s*고시|부령으로\s*정"
)
# 정의어 별칭: 「…기본법」(이하 "법"이라 한다) → 법, 같은 법 시행령(이하 '영'이라 한다) → 영
_Q = "\"'“”‘’"
LAW_ALIAS = re.compile(rf"「[^」]+」\s*\(이하\s*[{_Q}]법[{_Q}]이라\s*한다\)")
DECREE_ALIAS = re.compile(
    rf"(?:같은\s*법\s*)?시행령\s*\(이하\s*[{_Q}]영[{_Q}]이라\s*한다\)"
)
# 「다른 법률」 + 뒤따르는 조항 연쇄(제129조부터 제132조까지, 제29조, 제30조 및 …)는 참조 탐지 전에 마스킹
_ART = r"제\d+조(?:의\d+)?(?:제\d+항)?(?:제\d+호)?(?:[가-하]목)?"
OTHER_LAW = re.compile(rf"「[^」]+」(?:\s*{_ART}(?:\s*(?:부터|까지|및|또는|,|ㆍ))*)*")
SAME_OTHER_LAW = re.compile(
    rf"같은\s*(?:법|영|규칙)\s*{_ART}(?:\s*(?:부터|까지|및|또는|,|ㆍ)\s*{_ART})*"
)
# "법 제N조" — 시행령·별표·고시에서 상위 법률을 가리킴 ("기본법 제", "같은 법 제"는 제외)
LAW_REF = re.compile(r"(?<![가-힣])법\s*제(\d+)조(?:의(\d+))?(?:제(\d+)항)?")
# 고시에서 시행령을 가리킴: "영 제15조", "시행령(이하 '영'이라 한다) 제15조"
DECREE_REF = re.compile(
    r"(?:(?<![가-힣])영|시행령(?:\([^)]*\))?)\s*제(\d+)조(?:의(\d+))?"
)
INTERNAL = re.compile(r"제(\d+)조(?:의(\d+))?(?:제(\d+)항)?")
# 시행령 → 법률 위임 근거. kind: define(에서 "…대통령령으로 정하는") | act(에 따라) | adnominal(에 따른)
FROM_LAW = re.compile(
    r"(?<![가-힣])법\s*제(\d+)조(?:의(\d+))?(?:제(\d+)항)?(?:제(\d+)호)?(?:[가-하]목)?"
    r"(?:\s*각\s*호(?:\s*외의\s*부분)?)?(?:\s*(?:본문|단서|전단|후단))?"
    rf"(?:(?P<define>에서\s*[{_Q}][^{_Q}]{{0,100}}?대통령령으로\s*정하는)|(?P<act>에\s*따라)|(?P<adnominal>에\s*따른))"
)
# "에 따른 X"를 위임으로 보는 위치: 항·조 첫머리(+ "…장관은 " 같은 주어). 호 첫머리·문장 중간은 정의 인용
SENTENCE_HEAD = re.compile(
    r"\s*(?:[①-⑳]\s*)?(?:제\d+조(?:의\d+)?\([^)]*\)\s*)?(?:[가-힣ㆍ·\s]{1,30}(?:은|는)\s+)?"
)
# 시행령 부칙 → 법률 부칙: 법률 제20676호 … 부칙 제3조에서 "…대통령령으로 정하는
ADDENDUM_FROM_LAW = re.compile(
    rf"법률\s*제(\d+)호[^\n]{{0,60}}?부칙\s*제\d+조에서\s*[{_Q}][^{_Q}]{{0,40}}?대통령령으로"
)
ANNEX_REF = re.compile(r"별표\s*(\d+)(?:의(\d+))?")
ADMRUL_ART = re.compile(r"^\s*제(\d+)조(?:의(\d+))?\(([^)]+)\)", re.MULTILINE)
PARA_SYM = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"

# 별표·고시 본문의 번호 줄: 1. / 가. / 1)
NUMBERED_LINE = re.compile(r"^\s*(\d+\.|[가-하]\.|\d+\))\s")


def article_ref(source_type: str, no: str | int, sub: str | int | None = None) -> str:
    """조 단위 참조 키: ("law", 31) → "law:a31", ("decree", 22, 2) → "decree:a22_2"."""
    sub_i = int(sub or 0)
    return f"{source_type}:a{int(no)}" + (f"_{sub_i}" if sub_i else "")


def paragraph_no(symbol: str) -> int | None:
    """항 기호(②)를 번호(2)로 바꾼다."""
    symbol = symbol.strip()
    return PARA_SYM.index(symbol[0]) + 1 if symbol and symbol[0] in PARA_SYM else None


def extract_amendments(text: str) -> list[str]:
    """개정·신설 표시를 원문 그대로 뽑는다."""
    return [m.group(0) for m in AMEND.finditer(text)]


def strip_amendments(text: str) -> str:
    """개정·신설 표시를 지운다(embed_text용)."""
    return re.sub(r"[ \t]{2,}", " ", AMEND.sub("", text)).strip()


def is_delegating(text: str) -> bool:
    """하위 법령(대통령령·고시·부령)에 위임하는 문장이 있는지."""
    return bool(DELEGATE.search(text))


def _blank(m: re.Match) -> str:
    return " " * len(m.group(0))


def _mask(text: str) -> str:
    """정의어 별칭을 `법`·`영`으로 바꾸고 다른 법률 참조를 공백으로 지운다."""
    text = LAW_ALIAS.sub("법", text)
    text = DECREE_ALIAS.sub("영", text)
    text = OTHER_LAW.sub(_blank, text)
    return SAME_OTHER_LAW.sub(_blank, text)


def find_refs(text: str, source_type: str, self_ref: str | None = None) -> list[str]:
    """본문의 조 참조를 조 단위 키로 뽑는다(다른 법률 참조·자기 자신 제외, 순서 유지).

    - law: "제N조" → law
    - decree/annex/admrul: "법 제N조" → law, "영 제N조"(고시) → decree,
      접두 없는 "제N조" → decree(시행령 본문만; 별표·고시는 자기 문서 조라 제외)
    - "별표 N" → annex:N
    """
    masked = _mask(text)
    refs: list[str] = []
    if source_type == "law":
        refs += [article_ref("law", m[1], m[2]) for m in INTERNAL.finditer(masked)]
    else:
        refs += [article_ref("law", m[1], m[2]) for m in LAW_REF.finditer(masked)]
        masked = LAW_REF.sub(_blank, masked)
        refs += [article_ref("decree", m[1], m[2]) for m in DECREE_REF.finditer(masked)]
        masked = DECREE_REF.sub(_blank, masked)
        if source_type == "decree":
            refs += [
                article_ref("decree", m[1], m[2]) for m in INTERNAL.finditer(masked)
            ]
    if source_type in ("law", "decree"):
        refs += [f"annex:{int(m[1])}" for m in ANNEX_REF.finditer(masked)]
    return [r for r in dict.fromkeys(refs) if r != self_ref]


@dataclass(frozen=True)
class DelegationSource:
    """시행령 문장이 가리키는 위임 근거 법률 위치."""

    key: str  # law:a33
    paragraph: int | None = None
    item: int | None = None


def find_delegation_sources(text: str) -> list[DelegationSource]:
    """시행령 본문에서 위임 근거 법률 조항을 뽑는다.

    `에서 "…대통령령으로 정하는"`·`에 따라`는 항상, `에 따른 X`는 항·조 첫머리(문장 주어)일 때만 근거로 본다.
    """
    masked = _mask(text)
    found: list[DelegationSource] = []
    for m in FROM_LAW.finditer(masked):
        if m["adnominal"]:
            line_start = masked.rfind("\n", 0, m.start()) + 1
            if not SENTENCE_HEAD.fullmatch(masked[line_start : m.start()]):
                continue
        found.append(
            DelegationSource(
                article_ref("law", m[1], m[2]),
                int(m[3]) if m[3] else None,
                int(m[4]) if m[4] else None,
            )
        )
    return list(dict.fromkeys(found))


def find_addendum_sources(text: str) -> list[str]:
    """시행령 부칙이 위임 근거로 드는 법률 부칙의 공포번호: ["20676"]."""
    return list(dict.fromkeys(m[1] for m in ADDENDUM_FROM_LAW.finditer(text)))


# ---------------------------------------------------------------------------
# 고정폭 줄 병합 (별표 본문, 표 셀)
# ---------------------------------------------------------------------------
def _space_at_boundary(prev: str, nxt: str) -> bool:
    """줄 경계에 공백이 필요한지: 경계 앞뒤 두 어절만 kiwi로 띄어 써 경계 위치를 본다."""
    left = " ".join(prev.split()[-2:])
    right = " ".join(nxt.split()[:2])
    spaced = get_kiwi().space(left + right, reset_whitespace=False)
    # 경계까지의 비공백 문자 수만큼 진행한 위치 바로 뒤가 공백인지 확인
    target = len(left.replace(" ", ""))
    count = 0
    for i, ch in enumerate(spaced):
        if ch != " ":
            count += 1
        if count == target:
            return i + 1 < len(spaced) and spaced[i + 1] == " "
    return False


def join_wrapped(prev: str, nxt: str) -> str:
    """고정폭으로 줄바꿈된 두 줄을 잇는다(단어 중간이면 붙이고, 띄어쓰기 자리면 공백)."""
    prev, nxt = prev.rstrip(), nxt.strip()
    if not prev:
        return nxt
    if not nxt:
        return prev
    if prev[-1] in ",:;」" or nxt[0] == "「":
        sep = " "
    elif prev[-1].isdigit() and (nxt[0].isdigit() or nxt[0] in "조항호목의,."):
        sep = ""
    elif not ("가" <= prev[-1] <= "힣" and "가" <= nxt[0] <= "힣"):
        sep = " " if prev[-1] in ".)" else ""
    else:
        sep = " " if _space_at_boundary(prev, nxt) else ""
    return prev + sep + nxt


def merge_wrapped_lines(lines: list[str]) -> list[str]:
    """번호(1. / 가. / 1))로 시작하지 않는 줄을 앞 줄에 이어 붙여 논리 줄 리스트로 만든다."""
    merged: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        if merged and not NUMBERED_LINE.match(line):
            merged[-1] = join_wrapped(merged[-1], line)
        else:
            merged.append(line.strip())
    return merged
