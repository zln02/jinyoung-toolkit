"""크롤링 엔진 모듈.

CrawlConfig, LegalComplianceChecker, CrawlResult, CrawlerEngine 구현.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.robotparser
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pandas as pd
from bs4 import BeautifulSoup
from pydantic import BaseModel

from shared.logger import get_logger

from .drivers import APIDriver, BaseDriver, HttpxDriver, SeleniumDriver
from .rate_limiter import RateLimiter

logger = get_logger(__name__)


class DriverType(str, Enum):
    """크롤링 드라이버 종류."""

    SELENIUM = "selenium"
    HTTPX = "httpx"
    API = "api"


class CrawlConfig(BaseModel):
    """크롤링 설정."""

    preset_name: str
    target_urls: list[str]
    max_pages: int = 100
    delay_seconds: float = 1.5
    max_retries: int = 3
    timeout_seconds: int = 30
    output_dir: Path = Path("./output")
    driver_type: DriverType = DriverType.HTTPX
    respect_robots_txt: bool = True
    filter_pii: bool = True


class LegalComplianceChecker:
    """크롤링 법적 준수 검사기.

    robots.txt 파싱, PII 마스킹, 법적 고지문을 제공한다.
    """

    _EMAIL_PATTERN = re.compile(
        r"([A-Za-z0-9_.+-])[A-Za-z0-9_.+-]*"
        r"(@)"
        r"([A-Za-z0-9-])[A-Za-z0-9.-]*"
        r"(\.[A-Za-z]{2,})"
    )
    _PHONE_PATTERN = re.compile(
        r"(0\d{1,2})-(\d{3,4})-(\d{4})"
    )
    _RRN_PATTERN = re.compile(
        r"(\d{6})-(\d{7})"
    )

    @staticmethod
    def check_robots_txt(
        url: str,
        user_agent: str = "JinyoungToolkit/1.0",
    ) -> bool:
        """robots.txt를 확인해 크롤링 허용 여부를 반환한다.

        Args:
            url: 크롤링 대상 URL
            user_agent: 검사에 사용할 User-Agent 문자열

        Returns:
            크롤링이 허용되면 True, 금지되면 False
        """
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            rp.read()
            allowed = rp.can_fetch(user_agent, url)
            logger.debug(
                "robots.txt 확인: url=%s allowed=%s robots_url=%s",
                url,
                allowed,
                robots_url,
            )
            return allowed
        except Exception as exc:
            logger.warning(
                "robots.txt 확인 중 오류 발생 (허용으로 처리): url=%s error=%s",
                url,
                exc,
            )
            return True

    @staticmethod
    def mask_pii(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
        """개인정보 자동 마스킹.

        패턴:
            - 이메일: u***@d***.com
            - 전화번호: 010-****-5678
            - 주민번호: 901231-*******

        Args:
            df: 마스킹할 DataFrame
            columns: PII가 포함된 컬럼 이름 목록

        Returns:
            PII가 마스킹된 DataFrame (원본 불변, 복사본 반환)
        """

        def _mask_email(text: str) -> str:
            def _repl(m: re.Match) -> str:
                local_first = m.group(1)
                at = m.group(2)
                domain_first = m.group(3)
                tld = m.group(4)
                return f"{local_first}***{at}{domain_first}***{tld}"

            return LegalComplianceChecker._EMAIL_PATTERN.sub(_repl, text)

        def _mask_phone(text: str) -> str:
            def _repl(m: re.Match) -> str:
                prefix = m.group(1)
                last = m.group(3)
                return f"{prefix}-****-{last}"

            return LegalComplianceChecker._PHONE_PATTERN.sub(_repl, text)

        def _mask_rrn(text: str) -> str:
            def _repl(m: re.Match) -> str:
                birth = m.group(1)
                return f"{birth}-*******"

            return LegalComplianceChecker._RRN_PATTERN.sub(_repl, text)

        def _apply_masks(value: object) -> object:
            if not isinstance(value, str):
                return value
            value = _mask_email(value)
            value = _mask_phone(value)
            value = _mask_rrn(value)
            return value

        result = df.copy()
        for col in columns:
            if col in result.columns:
                try:
                    result[col] = result[col].apply(_apply_masks)
                except Exception as exc:
                    logger.warning("PII 마스킹 중 오류: col=%s error=%s", col, exc)
        return result

    @staticmethod
    def get_legal_disclaimer() -> str:
        """크롤링 관련 법적 고지문을 반환한다.

        Returns:
            법적 고지문 문자열
        """
        return (
            "[법적 고지] 본 도구는 수집 대상 사이트의 이용약관 및 robots.txt를 준수합니다. "
            "수집된 데이터는 개인정보보호법, 저작권법 등 관련 법령에 따라 적법하게 활용해야 합니다. "
            "무단 상업적 이용, 개인정보 무단 수집·처리는 금지됩니다."
        )


@dataclass
class CrawlResult:
    """크롤링 실행 결과."""

    total_collected: int
    total_failed: int
    data: pd.DataFrame
    errors: list[dict[str, Any]] = field(default_factory=list)
    elapsed_seconds: float = 0.0


class CrawlerEngine:
    """범용 크롤링 엔진.

    프리셋의 selectors를 사용하여 HTML 파싱 후 DataFrame으로 변환한다.
    BeautifulSoup4를 사용해 데이터를 추출한다.

    Args:
        config: 크롤링 설정 객체
        preset: 크롤링 프리셋 딕셔너리 (selectors 포함)
    """

    def __init__(
        self,
        config: CrawlConfig,
        preset: dict[str, Any] | None = None,
    ) -> None:
        self._config = config
        self._preset = preset or {}
        self._rate_limiter = RateLimiter(
            requests_per_minute=30,
            delay_between_requests=config.delay_seconds,
        )
        self._pause_event = asyncio.Event()
        self._pause_event.set()

        pagination = self._preset.get("pagination", {}) or {}
        self._pagination_type: str = pagination.get("type", "none")
        self._next_button_selector: str = pagination.get("next_button_selector", "")
        preset_max_pages = pagination.get("max_pages", config.max_pages)
        # 프리셋과 사용자 입력 중 작은 값 사용
        self._pagination_max_pages: int = min(preset_max_pages, config.max_pages)
        # url_param 페이지네이션용 (네이버 블로그 start=1,11,21... 등)
        self._pagination_url_template: str = pagination.get("url_template", "")
        self._pagination_start: int = pagination.get("start", 1)
        self._pagination_step: int = pagination.get("step", 1)

    def _create_driver(self) -> BaseDriver:
        """config.driver_type에 따라 적절한 드라이버 인스턴스를 생성한다.

        프리셋의 `driver` 섹션 옵션을 모두 반영한다 (headless, wait_seconds, base_url 등).

        Returns:
            BaseDriver 구현체 인스턴스

        Raises:
            ValueError: 알 수 없는 DriverType인 경우
        """
        driver_type = self._config.driver_type
        timeout = self._config.timeout_seconds
        max_retries = self._config.max_retries
        driver_opts: dict[str, Any] = self._preset.get("driver", {}) or {}

        if driver_type == DriverType.HTTPX:
            return HttpxDriver(
                timeout=timeout,
                max_retries=max_retries,
                user_agent=driver_opts.get("user_agent", "JinyoungToolkit/1.0"),
                headers=driver_opts.get("headers"),
            )
        elif driver_type == DriverType.SELENIUM:
            scroll_iters = 0
            if self._pagination_type == "scroll":
                scroll_iters = self._pagination_max_pages
            return SeleniumDriver(
                headless=driver_opts.get("headless", True),
                wait_seconds=driver_opts.get("wait_seconds", 3),
                scroll_to_bottom=driver_opts.get("scroll_to_bottom", False),
                scroll_iterations=scroll_iters,
                user_agent=driver_opts.get("user_agent"),
                stealth=driver_opts.get("stealth", True),
                scroll_into_view_selector=driver_opts.get(
                    "scroll_into_view_selector"
                ),
            )
        elif driver_type == DriverType.API:
            from shared.config import get_settings

            # 평문 프리셋 키 의존을 줄이려 config(.env)의 공공데이터 키로 폴백
            query_params = dict(driver_opts.get("query_params") or {})
            api_key = driver_opts.get("api_key") or get_settings().public_data_api_key
            # auth_param 지정 시 쿼리 파라미터 인증(공공데이터포털 serviceKey 등),
            # 미지정 시 기존 Authorization Bearer 헤더 방식.
            auth_param = driver_opts.get("auth_param")
            if auth_param and api_key:
                query_params[auth_param] = api_key
            return APIDriver(
                base_url=driver_opts.get("base_url", ""),
                api_key=(None if auth_param else api_key),
                headers=driver_opts.get("headers"),
                query_params=query_params or None,
            )
        else:
            raise ValueError(f"알 수 없는 DriverType: {driver_type}")

    def _expand_urls(self, urls: list[str]) -> list[str]:
        """url_param 페이지네이션이면 첫 URL을 url_template으로 N개로 확장한다.

        url_template은 `{page}` 토큰을 포함해야 하며, 절대 URL이면 그대로,
        상대형이면 입력 URL의 base와 합쳐 사용한다. `{base}` 토큰이 있으면
        입력 URL을 그대로 치환한다.

        Args:
            urls: 입력 URL 리스트

        Returns:
            확장된 URL 리스트. url_param이 아니면 입력 그대로 반환.
        """
        if self._pagination_type != "url_param":
            return urls
        if not urls:
            return urls
        template = self._pagination_url_template
        if not template:
            logger.warning("url_param 페이지네이션이지만 url_template이 비어 있음")
            return urls

        base_url = urls[0]
        n = self._pagination_max_pages
        start = self._pagination_start
        step = self._pagination_step

        expanded: list[str] = []
        for i in range(n):
            page_value = start + step * i
            replaced = template.replace("{page}", str(page_value))
            replaced = replaced.replace("{base}", base_url)

            if replaced.startswith("http://") or replaced.startswith("https://"):
                final_url = replaced
            else:
                # 상대 경로 → base_url 기준으로 결합
                final_url = urljoin(base_url, replaced)
            expanded.append(final_url)

        logger.debug(
            "url_param 확장: base=%s template=%s n=%d → %d개",
            base_url,
            template,
            n,
            len(expanded),
        )
        return expanded

    def _parse_page(self, html: str, selectors: dict[str, Any]) -> list[dict[str, Any]]:
        """HTML 또는 JSON에서 selectors 기반으로 데이터를 추출한다.

        selectors 구조:
            - "format": "json"인 경우 JSON 모드 (점 표기법). 없으면 BS4 HTML 모드.
            - "container": 반복 항목의 CSS 셀렉터 또는 점 표기법 경로
            - "fields": {필드명: CSS 셀렉터 또는 점 표기법} 딕셔너리

        Args:
            html: 파싱할 HTML/JSON 문자열
            selectors: container와 fields를 담은 딕셔너리

        Returns:
            추출된 데이터 딕셔너리의 리스트
        """
        records: list[dict[str, Any]] = []
        if not html:
            return records

        if selectors.get("format") == "json":
            return self._parse_json(html, selectors)

        try:
            soup = BeautifulSoup(html, "html.parser")
            container_selector = selectors.get("container", "")
            fields: dict[str, str] = selectors.get("fields", {})

            if not container_selector:
                logger.warning("selectors에 'container' 키가 없어 파싱 불가")
                return records

            containers = soup.select(container_selector)
            logger.debug(
                "파싱: container=%s 개수=%d",
                container_selector,
                len(containers),
            )

            for container in containers:
                record: dict[str, Any] = {}
                for field_name, css_selector in fields.items():
                    try:
                        # "selector@attr" 형식이면 해당 속성값 추출 (예: div.rating@aria-label)
                        attr_name: str | None = None
                        sel = css_selector
                        if "@" in css_selector:
                            sel, attr_name = css_selector.rsplit("@", 1)
                        element = container.select_one(sel)
                        if element is None:
                            record[field_name] = ""
                        elif attr_name:
                            record[field_name] = element.get(attr_name, "") or ""
                        else:
                            record[field_name] = element.get_text(strip=True)
                    except Exception as exc:
                        logger.warning(
                            "필드 추출 실패: field=%s selector=%s error=%s",
                            field_name,
                            css_selector,
                            exc,
                        )
                        record[field_name] = ""
                records.append(record)

        except Exception as exc:
            logger.error("HTML 파싱 중 예외: %s", exc)

        return records

    @staticmethod
    def _dot_get(obj: Any, path: str) -> Any:
        """점(.) 구분 키 경로로 dict에서 값을 추출한다.

        예: obj={"a": {"b": "c"}}, path="a.b" → "c"
        중간에 dict가 아니거나 키가 없으면 "" 반환.

        Args:
            obj: 탐색 대상 객체
            path: 점 구분 키 경로

        Returns:
            추출된 값 또는 ""
        """
        if not path:
            return ""
        cur: Any = obj
        for key in path.split("."):
            if isinstance(cur, dict):
                if key not in cur:
                    return ""
                cur = cur[key]
            else:
                return ""
        return cur

    def _parse_json(self, body: str, selectors: dict[str, Any]) -> list[dict[str, Any]]:
        """JSON 본문에서 selectors 기반으로 데이터를 추출한다.

        - container: 점 표기법 경로 (예: "feed.entry") → list 또는 dict
        - fields: {필드명: 점 표기법} 매핑 (예: "im:rating.label")

        Args:
            body: JSON 문자열
            selectors: container/fields 포함 dict

        Returns:
            추출된 레코드 리스트
        """
        records: list[dict[str, Any]] = []
        try:
            root: Any = json.loads(body)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("JSON 파싱 실패: %s", exc)
            return records

        container_path: str = selectors.get("container", "")
        fields: dict[str, str] = selectors.get("fields", {})

        if not container_path:
            logger.warning("JSON 모드: selectors에 'container' 키가 없어 파싱 불가")
            return records

        items: Any = self._dot_get(root, container_path)
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            logger.warning("JSON container 결과가 list/dict 아님: type=%s", type(items).__name__)
            return records

        for item in items:
            record: dict[str, Any] = {}
            for field_name, field_path in fields.items():
                try:
                    value = self._dot_get(item, field_path)
                    record[field_name] = value if value is not None else ""
                except Exception as exc:
                    logger.warning(
                        "JSON 필드 추출 실패: field=%s path=%s error=%s",
                        field_name,
                        field_path,
                        exc,
                    )
                    record[field_name] = ""
            records.append(record)

        logger.debug("JSON 파싱: container=%s 개수=%d", container_path, len(records))
        return records

    async def _paginate_with_click(
        self,
        driver: SeleniumDriver,
        selectors: dict[str, Any],
        all_records: list[dict[str, Any]],
        errors: list[dict[str, Any]],
        initial_url: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """클릭 기반 페이지네이션을 수행한다.

        2페이지부터 max_pages까지 다음 버튼을 클릭하며 파싱한다.
        중단 조건: click_next=False, 빈 HTML, 파싱 결과 0건, 예외.

        Args:
            driver: SeleniumDriver 인스턴스
            selectors: 파싱용 셀렉터 dict
            all_records: 누적 레코드 리스트 (in-place 확장)
            errors: 누적 에러 리스트 (in-place 확장)
            initial_url: 1페이지 URL (로깅/progress용)

        Yields:
            진행 상태 dict (run_with_progress용). 호출자가 무시하면 단순 루프로 동작.
        """
        max_pages = self._pagination_max_pages
        for page in range(2, max_pages + 1):
            await self._pause_event.wait()
            await self._rate_limiter.wait()

            try:
                clicked = await driver.click_next(
                    self._next_button_selector,
                    wait_seconds=None,
                )
            except Exception as exc:
                logger.error(
                    "페이지네이션 클릭 예외: url=%s page=%d error=%s",
                    initial_url,
                    page,
                    exc,
                )
                errors.append(
                    {"url": f"{initial_url}#page={page}", "error": str(exc)}
                )
                break

            if not clicked:
                logger.info(
                    "페이지네이션 종료(마지막 페이지): url=%s page=%d",
                    initial_url,
                    page,
                )
                break

            try:
                html = await driver.get_page_source()
            except Exception as exc:
                logger.error(
                    "페이지네이션 page_source 예외: url=%s page=%d error=%s",
                    initial_url,
                    page,
                    exc,
                )
                errors.append(
                    {"url": f"{initial_url}#page={page}", "error": str(exc)}
                )
                break

            if not html:
                logger.warning(
                    "페이지네이션 종료(빈 HTML): url=%s page=%d",
                    initial_url,
                    page,
                )
                break

            try:
                records = self._parse_page(html, selectors)
            except Exception as exc:
                logger.error(
                    "페이지네이션 파싱 예외: url=%s page=%d error=%s",
                    initial_url,
                    page,
                    exc,
                )
                errors.append(
                    {"url": f"{initial_url}#page={page}", "error": str(exc)}
                )
                break

            if not records:
                logger.info(
                    "페이지네이션 종료(파싱 결과 0건): url=%s page=%d",
                    initial_url,
                    page,
                )
                break

            all_records.extend(records)
            logger.debug(
                "페이지네이션 파싱 완료: url=%s page=%d records=%d",
                initial_url,
                page,
                len(records),
            )
            yield {
                "page": page,
                "current_url": f"{initial_url}#page={page}",
                "collected": len(all_records),
            }

    async def run(self) -> CrawlResult:
        """전체 크롤링을 실행한다.

        실행 순서:
            1. robots.txt 확인 (respect_robots_txt=True인 경우)
            2. 드라이버 생성
            3. 각 URL에 대해 fetch + parse
            4. PII 마스킹 (filter_pii=True인 경우)
            5. CrawlResult 반환

        Returns:
            CrawlResult: 수집 결과
        """
        start_time = time.perf_counter()
        all_records: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        selectors: dict[str, Any] = self._preset.get("selectors", {})
        pii_columns: list[str] = self._preset.get("pii_columns", [])

        urls = self._expand_urls(self._config.target_urls)
        urls = urls[: self._config.max_pages]
        driver = self._create_driver()

        use_pagination = (
            self._pagination_type == "click"
            and bool(self._next_button_selector)
            and isinstance(driver, SeleniumDriver)
        )

        try:
            for url in urls:
                await self._pause_event.wait()

                if self._config.respect_robots_txt:
                    try:
                        allowed = LegalComplianceChecker.check_robots_txt(url)
                        if not allowed:
                            logger.warning("robots.txt 차단: url=%s", url)
                            errors.append({"url": url, "error": "robots.txt에 의해 차단됨"})
                            continue
                    except Exception as exc:
                        logger.warning("robots.txt 확인 실패, 계속 진행: url=%s error=%s", url, exc)

                await self._rate_limiter.wait()

                try:
                    page_result = await driver.fetch(url)
                except Exception as exc:
                    logger.error("fetch 예외: url=%s error=%s", url, exc)
                    errors.append({"url": url, "error": str(exc)})
                    continue

                if not page_result.success:
                    logger.warning(
                        "fetch 실패: url=%s error=%s",
                        url,
                        page_result.error,
                    )
                    errors.append({"url": url, "error": page_result.error or "unknown"})
                    continue

                try:
                    records = self._parse_page(page_result.html, selectors)
                    all_records.extend(records)
                    logger.debug("파싱 완료: url=%s records=%d", url, len(records))
                except Exception as exc:
                    logger.error("파싱 예외: url=%s error=%s", url, exc)
                    errors.append({"url": url, "error": str(exc)})
                    continue

                if use_pagination and records:
                    async for _progress in self._paginate_with_click(
                        driver,  # type: ignore[arg-type]
                        selectors,
                        all_records,
                        errors,
                        initial_url=url,
                    ):
                        pass

        finally:
            try:
                await driver.close()
            except Exception as exc:
                logger.error("드라이버 종료 중 예외: %s", exc)

        df = pd.DataFrame(all_records) if all_records else pd.DataFrame()

        if self._config.filter_pii and not df.empty and pii_columns:
            try:
                df = LegalComplianceChecker.mask_pii(df, pii_columns)
            except Exception as exc:
                logger.error("PII 마스킹 중 예외: %s", exc)

        elapsed = time.perf_counter() - start_time

        if len(all_records) == 0:
            logger.error(
                "크롤링 0건: preset=%s urls=%d errors=%d — 셀렉터 또는 사이트 차단 의심",
                self._config.preset_name,
                len(urls),
                len(errors),
            )
            # errors 리스트가 비어있으면 "0 records extracted" 사유 명시
            if not errors:
                errors.append({"url": urls[0] if urls else "", "error": "파싱 결과 0건 — 셀렉터 확인 필요"})

        logger.info(
            "크롤링 완료: collected=%d failed=%d elapsed=%.2fs",
            len(all_records),
            len(errors),
            elapsed,
        )

        return CrawlResult(
            total_collected=len(all_records),
            total_failed=len(errors),
            data=df,
            errors=errors,
            elapsed_seconds=elapsed,
        )

    async def run_with_progress(
        self,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Streamlit UI용 진행률 포함 크롤링을 실행한다.

        Yields:
            진행 상태 딕셔너리:
                - "progress": 0.0 ~ 1.0 진행률
                - "collected": 수집된 레코드 수
                - "current_url": 현재 처리 중인 URL
                - "status": "running" | "paused" | "done" | "error"
        """
        all_records: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        selectors: dict[str, Any] = self._preset.get("selectors", {})
        pii_columns: list[str] = self._preset.get("pii_columns", [])

        urls = self._expand_urls(self._config.target_urls)
        urls = urls[: self._config.max_pages]
        total = len(urls)
        driver = self._create_driver()

        use_pagination = (
            self._pagination_type == "click"
            and bool(self._next_button_selector)
            and isinstance(driver, SeleniumDriver)
        )

        try:
            for idx, url in enumerate(urls):
                if not self._pause_event.is_set():
                    yield {
                        "progress": idx / total if total else 1.0,
                        "collected": len(all_records),
                        "current_url": url,
                        "status": "paused",
                    }
                await self._pause_event.wait()

                yield {
                    "progress": idx / total if total else 1.0,
                    "collected": len(all_records),
                    "current_url": url,
                    "status": "running",
                }

                if self._config.respect_robots_txt:
                    try:
                        allowed = LegalComplianceChecker.check_robots_txt(url)
                        if not allowed:
                            logger.warning("robots.txt 차단: url=%s", url)
                            errors.append({"url": url, "error": "robots.txt에 의해 차단됨"})
                            continue
                    except Exception as exc:
                        logger.warning(
                            "robots.txt 확인 실패, 계속 진행: url=%s error=%s", url, exc
                        )

                await self._rate_limiter.wait()

                try:
                    page_result = await driver.fetch(url)
                except Exception as exc:
                    logger.error("fetch 예외: url=%s error=%s", url, exc)
                    errors.append({"url": url, "error": str(exc)})
                    yield {
                        "progress": (idx + 1) / total if total else 1.0,
                        "collected": len(all_records),
                        "current_url": url,
                        "status": "error",
                    }
                    continue

                if not page_result.success:
                    logger.warning(
                        "fetch 실패: url=%s error=%s", url, page_result.error
                    )
                    errors.append({"url": url, "error": page_result.error or "unknown"})
                    continue

                try:
                    records = self._parse_page(page_result.html, selectors)
                    all_records.extend(records)
                except Exception as exc:
                    logger.error("파싱 예외: url=%s error=%s", url, exc)
                    errors.append({"url": url, "error": str(exc)})
                    continue

                if use_pagination and records:
                    async for page_progress in self._paginate_with_click(
                        driver,  # type: ignore[arg-type]
                        selectors,
                        all_records,
                        errors,
                        initial_url=url,
                    ):
                        yield {
                            "progress": (idx + 1) / total if total else 1.0,
                            "collected": len(all_records),
                            "current_url": page_progress.get("current_url", url),
                            "status": "running",
                        }

        finally:
            try:
                await driver.close()
            except Exception as exc:
                logger.error("드라이버 종료 중 예외: %s", exc)

        df = pd.DataFrame(all_records) if all_records else pd.DataFrame()

        if self._config.filter_pii and not df.empty and pii_columns:
            try:
                df = LegalComplianceChecker.mask_pii(df, pii_columns)
            except Exception as exc:
                logger.error("PII 마스킹 중 예외: %s", exc)

        logger.info(
            "run_with_progress 완료: collected=%d failed=%d",
            len(all_records),
            len(errors),
        )

        yield {
            "progress": 1.0,
            "collected": len(all_records),
            "current_url": "",
            "status": "done",
        }

    def pause(self) -> None:
        """크롤링을 일시 정지한다."""
        self._pause_event.clear()
        logger.info("크롤링 일시 정지")

    def resume(self) -> None:
        """일시 정지된 크롤링을 재개한다."""
        self._pause_event.set()
        logger.info("크롤링 재개")
