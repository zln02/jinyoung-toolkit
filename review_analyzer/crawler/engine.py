"""크롤링 엔진 모듈.

CrawlConfig, LegalComplianceChecker, CrawlResult, CrawlerEngine 구현.
"""

from __future__ import annotations

import asyncio
import re
import time
import urllib.robotparser
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

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

    def _create_driver(self) -> BaseDriver:
        """config.driver_type에 따라 적절한 드라이버 인스턴스를 생성한다.

        Returns:
            BaseDriver 구현체 인스턴스

        Raises:
            ValueError: 알 수 없는 DriverType인 경우
        """
        driver_type = self._config.driver_type
        timeout = self._config.timeout_seconds
        max_retries = self._config.max_retries

        if driver_type == DriverType.HTTPX:
            return HttpxDriver(timeout=timeout, max_retries=max_retries)
        elif driver_type == DriverType.SELENIUM:
            return SeleniumDriver(headless=True)
        elif driver_type == DriverType.API:
            return APIDriver()
        else:
            raise ValueError(f"알 수 없는 DriverType: {driver_type}")

    def _parse_page(self, html: str, selectors: dict[str, Any]) -> list[dict[str, Any]]:
        """HTML에서 selectors 기반으로 데이터를 추출한다.

        selectors 구조:
            - "container": 반복 항목의 CSS 셀렉터 (예: ".review-item")
            - "fields": {필드명: CSS 셀렉터} 딕셔너리

        Args:
            html: 파싱할 HTML 문자열
            selectors: container와 fields를 담은 딕셔너리

        Returns:
            추출된 데이터 딕셔너리의 리스트
        """
        records: list[dict[str, Any]] = []
        if not html:
            return records

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
                        element = container.select_one(css_selector)
                        record[field_name] = element.get_text(strip=True) if element else ""
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

        urls = self._config.target_urls[: self._config.max_pages]
        driver = self._create_driver()

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

        urls = self._config.target_urls[: self._config.max_pages]
        total = len(urls)
        driver = self._create_driver()

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
