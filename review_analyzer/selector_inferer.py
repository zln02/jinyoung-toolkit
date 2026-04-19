"""LLM 기반 자동 셀렉터 추론 모듈.

URL → fetch → HTML 압축 → Claude Haiku 호출 → JSON 셀렉터 응답 → 검증 →
메모리 dict preset 반환. 디스크 저장 없음. 명시적 옵트인이 전제.

`infer_preset_from_url(url)` 한 함수가 핵심 진입점이다.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from shared.config import AppSettings, get_settings
from shared.logger import get_logger

from .crawler.drivers import BaseDriver, HttpxDriver

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 예외
# ---------------------------------------------------------------------------


class SelectorInferenceError(RuntimeError):
    """LLM 셀렉터 추론 실패 (API 키 없음, 응답 파싱 실패, 검증 실패 등)."""


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

_DEFAULT_MAX_HTML_CHARS = 25_000

_REMOVE_TAGS = (
    "script",
    "style",
    "noscript",
    "svg",
    "iframe",
    "meta",
    "link",
    "img",
    "picture",
    "source",
    "video",
    "audio",
    "canvas",
    "template",
)

_REMOVE_ATTR_PREFIXES = ("on",)  # onclick, onload 등
_KEEP_DATA_ATTRS = ("data-testid",)

_SYSTEM_PROMPT = (
    "너는 웹 페이지 HTML에서 반복되는 리뷰/댓글/검색결과 항목의 CSS 셀렉터를 "
    "찾는 전문가야. 사용자가 제공한 압축 HTML을 분석해서 가장 안정적인 CSS "
    "셀렉터를 JSON 형식으로만 응답해. 부가 설명이나 마크다운 코드블럭 없이 "
    "순수 JSON 객체만 출력해."
)

_USER_PROMPT_TEMPLATE = """다음 페이지에서 반복되는 리뷰/댓글/검색결과 항목의 CSS 셀렉터를 찾아줘.

URL: {url}

규칙:
- container는 페이지에서 5개 이상 매칭되는 가장 안정적인 셀렉터여야 함
- container 안에서 추출 가능한 fields(title, content, reviewer, rating, date 등)의 셀렉터를 함께 찾아줘
- 자동 생성된 해시 클래스명(예: css-1abc23)은 피하고 의미 있는 클래스/태그를 우선
- 응답은 반드시 아래 스키마에 맞는 JSON 한 개만 출력 (마크다운 X, 설명 X)

스키마:
{{
  "container": "CSS 셀렉터 문자열",
  "fields": {{
    "title": "CSS 셀렉터",
    "content": "CSS 셀렉터",
    "reviewer": "CSS 셀렉터",
    "rating": "CSS 셀렉터",
    "date": "CSS 셀렉터"
  }}
}}

(fields 중 페이지에 존재하지 않는 항목은 키 자체를 생략. 최소 1개 이상 포함.)

압축 HTML:
{html}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def infer_preset_from_url(
    url: str,
    settings: AppSettings | None = None,
    fetch_driver: BaseDriver | None = None,
) -> dict[str, Any]:
    """URL 1개를 LLM에 보내 임시 preset dict를 추론·검증·반환.

    흐름:
        1. fetch_driver(기본 HttpxDriver)로 url fetch
        2. _compress_html(): script/style/svg/meta 등 제거 + body 일부만 (~25KB)
        3. _build_messages(): 압축 HTML + 컨텍스트 prompt 구성
        4. anthropic.AsyncAnthropic().messages.create(): JSON 응답 강제
        5. _parse_response(): {container, fields:{...}} 추출
        6. _validate_with_bs4(): 원본 HTML에 셀렉터 적용해 container >=2 확인
        7. 검증 통과 시 임시 preset dict 빌드 (PresetLoader._validate_schema 통과 가능 형태)

    Args:
        url: 셀렉터를 추론할 페이지 URL.
        settings: AppSettings 인스턴스. None이면 get_settings() 사용.
        fetch_driver: HTML을 가져올 드라이버. None이면 HttpxDriver 사용.
            JS 렌더링 페이지의 경우 SeleniumDriver를 주입할 수 있음.

    Returns:
        PresetLoader._validate_schema를 통과할 수 있는 preset dict.

    Raises:
        SelectorInferenceError: API 키 없음, 페이지 fetch 실패, 응답 파싱 실패,
            셀렉터 검증 실패 시.
    """
    settings = settings or get_settings()

    api_key = settings.anthropic_api_key
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY 미설정 — 자동 셀렉터 추론 불가")
        raise SelectorInferenceError(
            "ANTHROPIC_API_KEY가 설정되지 않았습니다. .env 파일에 키를 추가하세요."
        )

    # 1) 페이지 fetch
    own_driver = fetch_driver is None
    driver: BaseDriver = fetch_driver or HttpxDriver(timeout=settings.request_timeout)

    try:
        page = await driver.fetch(url)
    finally:
        if own_driver:
            try:
                await driver.close()
            except Exception as exc:  # pragma: no cover - close 실패는 비치명적
                logger.warning("fetch_driver 종료 중 예외: %s", exc)

    if not page.success or not page.html:
        raise SelectorInferenceError(
            f"페이지 fetch 실패: url={url} status={page.status_code} error={page.error}"
        )

    raw_html = page.html
    compressed = _compress_html(raw_html, max_chars=_DEFAULT_MAX_HTML_CHARS)
    logger.info(
        "HTML 압축 완료: url=%s raw=%d chars compressed=%d chars",
        url,
        len(raw_html),
        len(compressed),
    )

    # 2) Anthropic 호출
    try:
        from anthropic import AsyncAnthropic  # type: ignore
    except ImportError as exc:
        raise SelectorInferenceError(
            "anthropic 패키지가 설치되지 않았습니다. `pip install anthropic` 실행 필요."
        ) from exc

    client = AsyncAnthropic(api_key=api_key)
    messages = _build_messages(compressed, url)

    try:
        response = await client.messages.create(
            model=settings.selector_inference_model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )
    except Exception as exc:
        raise SelectorInferenceError(
            f"Anthropic API 호출 실패: {exc}"
        ) from exc

    text = _extract_text_from_response(response)
    if not text:
        raise SelectorInferenceError("Anthropic 응답이 비어있습니다.")

    logger.debug("LLM 응답: %s", text[:500])

    # 3) 응답 파싱
    selectors = _parse_response(text)

    # 4) 검증
    ok, count = _validate_with_bs4(raw_html, selectors)
    if not ok:
        raise SelectorInferenceError(
            f"추론된 셀렉터가 페이지에서 충분히 매칭되지 않습니다 "
            f"(container 매칭 수={count}, 최소 2개 필요). "
            f"selectors={selectors}"
        )

    logger.info(
        "셀렉터 검증 통과: container=%s fields=%d개 매칭=%d개",
        selectors["container"],
        len(selectors["fields"]),
        count,
    )

    # 5) preset dict 빌드
    preset = _build_preset_dict(url=url, selectors=selectors)
    return preset


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _compress_html(html: str, max_chars: int = _DEFAULT_MAX_HTML_CHARS) -> str:
    """HTML을 LLM 토큰 절약을 위해 압축한다.

    BS4로 파싱 후 script/style/svg/iframe/meta/link/img 등을 제거하고,
    on*/style 속성 및 (예외를 제외한) data-* 속성도 제거한다.
    body만 추출해 max_chars로 자른다.

    Args:
        html: 원본 HTML 문자열.
        max_chars: 잘라낼 최대 문자 수.

    Returns:
        압축된 HTML 문자열 (body만, 최대 max_chars).
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:
        logger.warning("BS4 파싱 실패, 원본 사용: %s", exc)
        return html[:max_chars]

    for tag_name in _REMOVE_TAGS:
        for el in soup.find_all(tag_name):
            el.decompose()

    # 모든 태그의 속성 정리
    for el in soup.find_all(True):
        if not isinstance(el, Tag):
            continue
        attrs = dict(el.attrs)
        for attr in list(attrs.keys()):
            attr_lower = attr.lower()
            if attr_lower == "style":
                del el.attrs[attr]
                continue
            if any(attr_lower.startswith(p) for p in _REMOVE_ATTR_PREFIXES):
                del el.attrs[attr]
                continue
            if attr_lower.startswith("data-") and attr_lower not in _KEEP_DATA_ATTRS:
                del el.attrs[attr]
                continue

    body = soup.body
    if body is None:
        text = str(soup)
    else:
        text = str(body)

    # 연속 공백 압축
    text = re.sub(r"\s+", " ", text)
    text = text.strip()

    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def _build_messages(compressed_html: str, url: str) -> list[dict[str, str]]:
    """Anthropic messages 페이로드를 구성한다.

    Args:
        compressed_html: _compress_html()로 압축된 HTML.
        url: 원본 URL (LLM 컨텍스트용).

    Returns:
        messages 리스트 (user 1개).
    """
    user_content = _USER_PROMPT_TEMPLATE.format(url=url, html=compressed_html)
    return [{"role": "user", "content": user_content}]


def _extract_text_from_response(response: Any) -> str:
    """Anthropic Message 응답에서 텍스트를 추출한다.

    Args:
        response: AsyncAnthropic.messages.create() 응답 객체.

    Returns:
        합쳐진 텍스트 문자열. 비어있으면 "".
    """
    content = getattr(response, "content", None)
    if not content:
        return ""

    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
        elif isinstance(block, dict) and "text" in block:
            parts.append(str(block["text"]))
    return "".join(parts).strip()


def _parse_response(text: str) -> dict[str, Any]:
    """LLM 응답에서 JSON 셀렉터 dict를 추출·검증한다.

    Args:
        text: LLM 응답 문자열 (마크다운 코드블럭 포함 가능).

    Returns:
        {"container": str, "fields": dict[str, str]} 형태의 dict.

    Raises:
        SelectorInferenceError: JSON 파싱 실패 또는 필수 키 누락.
    """
    cleaned = text.strip()

    # 마크다운 코드블럭 제거
    code_block_match = re.search(
        r"```(?:json)?\s*(.*?)\s*```",
        cleaned,
        re.DOTALL | re.IGNORECASE,
    )
    if code_block_match:
        cleaned = code_block_match.group(1).strip()

    # JSON 객체 부분만 추출 (LLM이 추가 텍스트 붙인 경우 대비)
    if not cleaned.startswith("{"):
        brace_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if brace_match:
            cleaned = brace_match.group(0)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise SelectorInferenceError(
            f"LLM 응답 JSON 파싱 실패: {exc}. 원문 일부: {text[:200]}"
        ) from exc

    if not isinstance(data, dict):
        raise SelectorInferenceError(
            f"LLM 응답이 dict가 아닙니다: {type(data).__name__}"
        )

    container = data.get("container")
    if not isinstance(container, str) or not container.strip():
        raise SelectorInferenceError(
            "LLM 응답에 container 키가 없거나 비어있습니다."
        )

    fields = data.get("fields")
    if not isinstance(fields, dict) or len(fields) == 0:
        raise SelectorInferenceError(
            "LLM 응답에 fields 키가 없거나 비어있습니다."
        )

    # fields 값이 모두 문자열인지 확인 + 빈 값 제거
    cleaned_fields: dict[str, str] = {}
    for k, v in fields.items():
        if isinstance(k, str) and isinstance(v, str) and v.strip():
            cleaned_fields[k] = v.strip()

    if not cleaned_fields:
        raise SelectorInferenceError(
            "LLM 응답의 fields에 유효한 셀렉터가 1개도 없습니다."
        )

    return {"container": container.strip(), "fields": cleaned_fields}


def _validate_with_bs4(
    html: str, selectors: dict[str, Any]
) -> tuple[bool, int]:
    """추론된 셀렉터를 원본 HTML에 적용해 매칭 가능 여부를 검증한다.

    container가 2개 이상 매칭되고, 첫 항목에서 최소 1개 이상의 field
    셀렉터가 매칭되어야 통과로 판단한다.

    Args:
        html: 원본 HTML 문자열 (압축 전).
        selectors: {"container": ..., "fields": {...}} dict.

    Returns:
        (성공 여부, container 매칭 개수).
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:
        logger.warning("검증 단계 BS4 파싱 실패: %s", exc)
        return False, 0

    container_sel = selectors["container"]
    fields = selectors["fields"]

    try:
        containers = soup.select(container_sel)
    except Exception as exc:
        logger.warning(
            "container 셀렉터 평가 실패: selector=%s error=%s",
            container_sel,
            exc,
        )
        return False, 0

    count = len(containers)
    if count < 2:
        return False, count

    # 첫 번째 container에서 fields 중 최소 1개가 매칭되는지
    first = containers[0]
    matched_fields = 0
    for field_name, sel in fields.items():
        try:
            if first.select_one(sel) is not None:
                matched_fields += 1
        except Exception as exc:
            logger.debug(
                "필드 셀렉터 평가 실패(무시): field=%s sel=%s err=%s",
                field_name,
                sel,
                exc,
            )

    if matched_fields == 0:
        return False, count

    return True, count


def _build_preset_dict(url: str, selectors: dict[str, Any]) -> dict[str, Any]:
    """검증된 셀렉터로 임시 preset dict를 구성한다.

    PresetLoader._validate_schema가 요구하는 필수 키(name, display_name,
    selectors.container, selectors.fields)를 모두 포함한다.

    Args:
        url: 원본 URL (이름/도메인 추출용).
        selectors: 검증을 통과한 selectors dict.

    Returns:
        preset dict.
    """
    parsed = urlparse(url)
    host = parsed.netloc or "unknown"
    safe_host = re.sub(r"[^a-zA-Z0-9_]", "_", host)

    fields = selectors["fields"]
    text_column = _pick_text_column(fields)

    preset: dict[str, Any] = {
        "name": f"auto_{safe_host}",
        "display_name": f"자동 추론 ({host})",
        "description": f"{host} 페이지에서 LLM이 자동 추론한 임시 프리셋",
        "driver": {
            "type": "httpx",
        },
        "pagination": {
            "type": "none",
        },
        "selectors": {
            "container": selectors["container"],
            "fields": fields,
        },
        "analysis": {
            "text_column": text_column,
            "sentiment_method": "rating_based",
        },
        "rate_limit": {
            "requests_per_minute": 20,
            "delay_between_pages": 2.0,
        },
    }
    return preset


def _pick_text_column(fields: dict[str, str]) -> str:
    """fields 중 분석 텍스트 컬럼으로 적합한 것을 선택한다.

    Args:
        fields: 추론된 fields dict.

    Returns:
        텍스트 컬럼명 (없으면 첫 번째 키).
    """
    for candidate in ("content", "review", "text", "body", "comment"):
        if candidate in fields:
            return candidate
    # fallback: 첫 번째 키
    return next(iter(fields))
