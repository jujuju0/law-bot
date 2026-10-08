"""답변 후검증 (DESIGN §5.2): 인용 대조·제거, 숫자 근거 확인, grounded 판정."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from rag.prompts import REFUSAL

CITATION = re.compile(r"\[([^\[\]]+)\]")
# 금액: "3천만원", "1,000만원", "500 만원", "2억원"
MONEY = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(억|천만|백만|십만|만|천|백)?\s*원")
MONEY_UNIT = {
    "억": 10**8,
    "천만": 10**7,
    "백만": 10**6,
    "십만": 10**5,
    "만": 10**4,
    "천": 1000,
    "백": 100,
}
# 금액 외 숫자: 기간·비율·인원·횟수 — 정규화 문자열로 대조
OTHER_NUMBER = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*(?:일|개월|년|퍼센트|%|명|시간|배|회|차)"
)
TABLE_UNIT = re.compile(r"단위\s*:\s*(억|천만|백만|십만|만|천|백)?\s*원")
BARE_NUMBER = re.compile(r"(?<![\d,.])\d[\d,]*(?![\d,.])")
_SPACE_COMMA = re.compile(r"[\s,]")


def _amount(number: str, unit: str | None) -> float:
    return float(number.replace(",", "")) * MONEY_UNIT.get(unit or "", 1)


def evidence_amounts(text: str) -> set[float]:
    """근거 텍스트의 금액(원 단위). 표에 "(단위: 만원)"이 있으면 표의 맨 숫자도 그 단위로 읽는다."""
    amounts = {_amount(m[1], m[2]) for m in MONEY.finditer(text)}
    if unit := TABLE_UNIT.search(text):
        amounts |= {_amount(m[0], unit[1]) for m in BARE_NUMBER.finditer(text)}
    return amounts


@dataclass
class GroundingReport:
    """후검증 결과."""

    answer: str  # 무효 인용을 지운 답변
    cited: list[str] = field(
        default_factory=list
    )  # 유효 인용(답변 등장 순서, 중복 제거)
    invalid_citations: list[str] = field(default_factory=list)
    unsupported_numbers: list[str] = field(default_factory=list)
    refused: bool = False

    @property
    def warnings(self) -> list[str]:
        """사람이 읽는 경고 목록(API debug·평가 공통)."""
        return [f"근거에 없는 인용 제거: [{c}]" for c in self.invalid_citations] + [
            f"근거 텍스트에 없는 숫자: {n}" for n in self.unsupported_numbers
        ]

    @property
    def grounded(self) -> bool:
        """거절이거나, 유효 인용이 1개 이상이고 근거 없는 숫자가 없으면 True."""
        return self.refused or (bool(self.cited) and not self.unsupported_numbers)


def _norm(text: str) -> str:
    return _SPACE_COMMA.sub("", text)


def match_citation(cited: str, available: Iterable[str]) -> str | None:
    """답변 인용과 맞는 근거 citation. 조 단위 인용이 항·호 근거와, 항 인용이 조 전체 근거와 맞는 것도 허용.

    예: "법 제31조" ↔ "법 제31조 제2항", "법 제31조 제2항" ↔ "법 제31조"(small-to-big으로 조 전체가 근거).
    "법 제3조" ↔ "법 제31조"처럼 번호 접두만 같은 것은 불일치.
    """
    c = cited.strip()
    for a in available:
        if c == a:
            return a
        short, long_ = sorted((c, a), key=len)
        if len(long_) > len(short) and long_.startswith(short + " "):
            return a
    return None


def check_answer(
    answer: str, citations: Iterable[str], evidence: Iterable[str]
) -> GroundingReport:
    """답변을 근거 citation 집합·근거 텍스트(청크별)와 대조한다. 무효 인용은 답변에서 지운다."""
    available = list(dict.fromkeys(citations))
    report = GroundingReport(answer=answer, refused=REFUSAL in answer)
    for m in CITATION.finditer(answer):
        raw = m[1]
        # "[법 제31조 제2항, 영 제23조]"처럼 한 괄호에 여러 개
        for part in (p.strip() for p in re.split(r"[,;]", raw)):
            if not part:
                continue
            if match_citation(part, available):
                if part not in report.cited:
                    report.cited.append(part)
            elif part not in report.invalid_citations:
                report.invalid_citations.append(part)
    if report.invalid_citations:
        cleaned = CITATION.sub(lambda m: _keep_valid(m[1], available), answer)
        report.answer = re.sub(r"[ \t]+([.,])", r"\1", cleaned).strip()
    texts = list(evidence)
    amounts = set().union(*(evidence_amounts(t) for t in texts))
    evidence_norm = _norm("\n".join(texts))
    for m in MONEY.finditer(answer):
        if _amount(m[1], m[2]) not in amounts:
            report.unsupported_numbers.append(m[0].strip())
    for m in OTHER_NUMBER.finditer(answer):
        if _norm(m[0]) not in evidence_norm:
            report.unsupported_numbers.append(m[0].strip())
    report.unsupported_numbers = list(dict.fromkeys(report.unsupported_numbers))
    return report


def _keep_valid(raw: str, available: list[str]) -> str:
    parts = [p.strip() for p in re.split(r"[,;]", raw) if p.strip()]
    valid = [p for p in parts if match_citation(p, available)]
    return f"[{', '.join(valid)}]" if valid else ""
