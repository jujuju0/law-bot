"""국가법령정보 공동활용 Open API(DRF) 클라이언트와 응답 정규화 유틸.

- law.go.kr 호출은 이 모듈의 `LawApiClient`로만 한다(CLAUDE.md).
- 인증 실패는 HTTP 200 + JSON `{"result","msg"}`로 오므로 target별 기대 루트 키로 감지한다.
- OC 마스킹은 캐시 저장 경로(`_write_cache`) 한 곳에서만 처리한다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from common.config import LAW_API_BASE, LAW_OC, RAW_DIR

logger = logging.getLogger(__name__)
# httpx는 INFO 레벨에서 요청 URL(OC 원문 포함)을 그대로 로그에 남긴다 → 로그는 이 모듈이 redact_oc로 남긴다
logging.getLogger("httpx").setLevel(logging.WARNING)

# 목록(lawSearch.do) 루트 키 — T0.7 실측 (DESIGN §2.4)
SEARCH_ROOT: dict[str, str] = {
    "law": "LawSearch",
    "admrul": "AdmRulSearch",
    "lstrm": "LsTrmSearch",
    "expc": "Expc",
    "licbyl": "licBylSearch",
}
# 본문(lawService.do) 루트 키 — 맵에 없는 target은 에러 형태만 검사하고 경고를 남긴다
SERVICE_ROOT: dict[str, str] = {
    "law": "법령",
    "admrul": "AdmRulService",
    "lstrm": "LsTrmService",  # trmSeqs=로 조회. query=는 정확히 일치하지 않으면 {"Law": "<안내문>"}
}

MASK = "***"


class LawApiError(RuntimeError):
    """Open API 호출 실패(네트워크·형식 오류)."""


class LawApiAuthError(LawApiError):
    """인증 실패: 기대 루트 키가 없는 응답(HTTP 200 + `{"result","msg"}` 포함)."""

    def __init__(self, result: str | None, msg: str | None, url: str = "") -> None:
        self.result = result
        self.msg = msg
        super().__init__(
            f"law.go.kr 인증 실패: result={result!r}, msg={msg!r} ({url}). "
            "OC 값·등록 IP/도메인·API별 활용 신청 승인 상태를 확인하세요."
        )


# ---------------------------------------------------------------------------
# 정규화 유틸
# ---------------------------------------------------------------------------
def as_list(x: Any) -> list:
    """단건 dict / 다건 list가 섞여 오는 필드를 항상 list로 만든다(None→[])."""
    if x is None or x == "":
        return []
    if isinstance(x, list):
        return x
    return [x]


def as_text(x: Any) -> str:
    """str·중첩 list·`{"content": ...}` dict를 줄바꿈으로 이은 텍스트로 평탄화한다."""
    if x is None:
        return ""
    if isinstance(x, str):
        return x.strip()
    if isinstance(x, list):
        return "\n".join(t for t in (as_text(i) for i in x) if t)
    if isinstance(x, dict):
        return as_text(x.get("content", ""))
    return str(x).strip()


def article_key(no: str | int, sub: str | int | None = None) -> str:
    """조 번호와 가지번호로 로컬 키를 만든다: ("22", "2") → "22_2", ("31", None) → "31"."""
    sub_s = str(sub or "").strip()
    no_s = str(int(no)) if str(no).strip().isdigit() else str(no).strip()
    return f"{no_s}_{int(sub_s)}" if sub_s and sub_s.strip("0") else no_s


def redact_oc(text: str, oc: str | None = LAW_OC) -> str:
    """URL·본문 문자열 속 OC 값을 `***`로 바꾼다(로그·캐시 저장용)."""
    text = re.sub(r"(OC=)[^&\"'\s]*", rf"\1{MASK}", text)
    if oc:
        text = text.replace(oc, MASK)
    return text


def strip_oc_param(url: str) -> str:
    """URL에서 OC 쿼리 파라미터를 제거한다(manifest 기록용)."""
    parts = urlsplit(url)
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "OC"
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))


# ---------------------------------------------------------------------------
# 조문 정규화
# ---------------------------------------------------------------------------
@dataclass
class Item:
    """호(1.) 또는 목(가.). 텍스트에는 번호 기호가 이미 포함돼 있다."""

    no: str
    text: str
    children: list[Item] = field(default_factory=list)


@dataclass
class Paragraph:
    """항(①). `no`가 빈 문자열이면 항 번호 없이 호만 있는 단일 항이다."""

    no: str
    text: str
    items: list[Item] = field(default_factory=list)


@dataclass
class Article:
    """정규화된 조문단위 1행. `is_heading`이면 장·절 제목(전문) 행이다."""

    key: str  # article_key: "31", "22_2"
    no: int
    sub: int
    is_heading: bool
    title: str
    content: str  # 조문내용(항 list인 조는 머리만, 항 없는 조는 머리+본문)
    effective_date: str
    paragraphs: list[Paragraph] = field(default_factory=list)
    items: list[Item] = field(
        default_factory=list
    )  # 항번호 없는 dict 항의 호(조의 직접 자식)


def _items(raw: Any) -> list[Item]:
    return [
        Item(
            no=as_text(h.get("호번호")),
            text=as_text(h.get("호내용")),
            children=[
                Item(no=as_text(m.get("목번호")), text=as_text(m.get("목내용")))
                for m in as_list(h.get("목"))
            ],
        )
        for h in as_list(raw)
    ]


def normalize_article(unit: dict) -> Article:
    """`조문단위` 1행을 `Article`로 정규화한다(dict 항·항번호 없는 항 처리 포함)."""
    no = str(unit.get("조문번호", "0")).strip() or "0"
    sub = str(unit.get("조문가지번호", "") or "").strip() or "0"
    paragraphs: list[Paragraph] = []
    direct_items: list[Item] = []
    for p in as_list(unit.get("항")):
        p_no = as_text(p.get("항번호"))
        if not p_no and not as_text(p.get("항내용")):
            # 단일 항 dict: 항번호·항내용 없이 호만 → 호를 조의 직접 자식으로
            direct_items.extend(_items(p.get("호")))
            continue
        paragraphs.append(
            Paragraph(no=p_no, text=as_text(p.get("항내용")), items=_items(p.get("호")))
        )
    return Article(
        key=article_key(no, sub),
        no=int(no),
        sub=int(sub),
        is_heading=unit.get("조문여부") == "전문",
        title=as_text(unit.get("조문제목")),
        content=as_text(unit.get("조문내용")),
        effective_date=as_text(unit.get("조문시행일자")),
        paragraphs=paragraphs,
        items=direct_items,
    )


# ---------------------------------------------------------------------------
# 클라이언트
# ---------------------------------------------------------------------------
def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


@dataclass(frozen=True)
class CacheKey:
    """캐시 위치: `{raw_dir}/{source_type}/{name}.json`."""

    source_type: str
    name: str

    @property
    def rel_path(self) -> str:
        return f"{self.source_type}/{self.name}.json"


class LawApiClient:
    """DRF 목록·본문 호출 + 재시도 + 호출 간격 + 캐시(저장 시 OC 마스킹)."""

    def __init__(
        self,
        oc: str | None = LAW_OC,
        base_url: str = LAW_API_BASE,
        raw_dir: Path = RAW_DIR,
        refresh: bool = False,
        min_interval: float = 0.5,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.oc = oc
        self.base_url = base_url.rstrip("/")
        self.raw_dir = Path(raw_dir)
        self.refresh = refresh
        self.min_interval = min_interval
        self._http = http_client or httpx.Client(timeout=timeout)
        self._last_call = 0.0

    # -- public -------------------------------------------------------------
    def search(
        self, target: str, query: str, cache: CacheKey | None = None, **params: Any
    ) -> list[dict]:
        """목록 조회. 모든 페이지의 항목 리스트를 반환한다(0건이면 [])."""
        root_key = SEARCH_ROOT[target]
        items: list[dict] = []
        page = 1
        while True:
            page_cache = None
            if cache is not None:
                name = cache.name if page == 1 else f"{cache.name}_p{page}"
                page_cache = CacheKey(cache.source_type, name)
            data = self._get(
                "lawSearch.do",
                {
                    "target": target,
                    "query": query,
                    "display": 100,
                    "page": page,
                    **params,
                },
                root_key=root_key,
                cache=page_cache,
            )
            root = data[root_key]
            items.extend(as_list(root.get(target)))
            total = int(root.get("totalCnt") or 0)
            if len(items) >= total or not as_list(root.get(target)):
                return items
            page += 1

    def service(
        self, target: str, cache: CacheKey | None = None, **params: Any
    ) -> dict:
        """본문 조회. 응답 전체(dict)를 반환한다. 루트 키는 `SERVICE_ROOT` 참고."""
        return self._get(
            "lawService.do",
            {"target": target, **params},
            root_key=SERVICE_ROOT.get(target),
            cache=cache,
        )

    def close(self) -> None:
        """HTTP 클라이언트를 닫는다."""
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- internal -----------------------------------------------------------
    def _get(
        self,
        endpoint: str,
        params: dict[str, Any],
        root_key: str | None,
        cache: CacheKey | None,
    ) -> dict:
        if cache is not None and not self.refresh:
            path = self.raw_dir / cache.rel_path
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                self._check_root(data, root_key, cache.rel_path)
                return data

        if not self.oc:
            raise LawApiError("LAW_OC가 설정되지 않았습니다(.env의 LAW_OC 확인).")
        url = f"{self.base_url}/{endpoint}"
        query = {"OC": self.oc, "type": "JSON", **params}
        response = self._request(url, query)
        logger.info("GET %s", redact_oc(str(response.url), self.oc))

        try:
            data = response.json()
        except ValueError as e:
            raise LawApiAuthError(
                None, response.text[:200], redact_oc(str(response.url))
            ) from e
        self._check_root(data, root_key, redact_oc(str(response.url), self.oc))

        if cache is not None:
            self._write_cache(cache, response)
        return data

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _request(self, url: str, query: dict[str, Any]) -> httpx.Response:
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            response = self._http.get(url, params=query)
        finally:
            self._last_call = time.monotonic()
        response.raise_for_status()
        return response

    @staticmethod
    def _check_root(data: Any, root_key: str | None, where: str) -> None:
        if not isinstance(data, dict):
            raise LawApiAuthError(
                None, f"JSON 객체가 아닌 응답: {type(data).__name__}", where
            )
        if len(data) == 1 and isinstance(next(iter(data.values())), str):
            # 예: {"Law": "일치하는 법령용어가 없습니다. ..."} — 인증은 됐지만 결과 없음
            raise LawApiError(
                f"결과 없음: {next(iter(data.values())).strip()} ({where})"
            )
        if root_key is not None:
            if root_key not in data:
                raise LawApiAuthError(data.get("result"), data.get("msg"), where)
        elif set(data) <= {"result", "msg"}:
            raise LawApiAuthError(data.get("result"), data.get("msg"), where)
        elif len(data) == 1:
            logger.warning(
                "루트 키 미등록 target 응답(%s): 루트=%s", where, next(iter(data))
            )

    def _write_cache(self, cache: CacheKey, response: httpx.Response) -> None:
        """응답 원문과 manifest를 저장한다. OC 마스킹은 이 함수에서만 한다."""
        body = redact_oc(response.text, self.oc).encode("utf-8")
        path = self.raw_dir / cache.rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

        manifest_path = self.raw_dir / "manifest.json"
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.exists()
            else {}
        )
        manifest[cache.rel_path] = {
            "url_without_oc": strip_oc_param(str(response.url)),
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "content_type": response.headers.get("content-type", ""),
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
        )
