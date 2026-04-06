"""크롤링 드라이버 모듈.

BaseDriver ABC와 HttpxDriver, SeleniumDriver, APIDriver 구현을 제공한다.
"""

from __future__ import annotations

import asyncio
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from shared.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PageResult:
    """단일 페이지 크롤링 결과."""

    url: str
    html: str
    status_code: int
    elapsed_seconds: float
    success: bool
    error: str | None = None


class BaseDriver(ABC):
    """크롤링 드라이버 추상 베이스 클래스."""

    @abstractmethod
    async def fetch(self, url: str) -> PageResult:
        """URL을 가져와 PageResult를 반환한다."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """드라이버 리소스를 해제한다."""
        ...

    async def __aenter__(self) -> "BaseDriver":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


class HttpxDriver(BaseDriver):
    """httpx 기반 비동기 HTTP 드라이버 (기본).

    Args:
        timeout: 요청 타임아웃(초), 기본 30
        max_retries: 최대 재시도 횟수, 기본 3
        user_agent: User-Agent 헤더, 기본 "JinyoungToolkit/1.0"
        headers: 추가 HTTP 헤더 딕셔너리 (선택)
    """

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        user_agent: str = "JinyoungToolkit/1.0",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self._base_headers: dict[str, str] = {"User-Agent": user_agent}
        if headers:
            self._base_headers.update(headers)
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """AsyncClient 인스턴스를 반환한다 (지연 초기화)."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self._base_headers,
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._client

    async def fetch(self, url: str) -> PageResult:
        """URL을 가져와 PageResult를 반환한다.

        재시도 로직이 내장되어 있으며 elapsed_seconds를 측정한다.

        Args:
            url: 가져올 URL

        Returns:
            PageResult: 크롤링 결과
        """
        client = self._get_client()
        last_error: str | None = None

        for attempt in range(1, self.max_retries + 1):
            start = time.perf_counter()
            try:
                response = await client.get(url)
                elapsed = time.perf_counter() - start
                response.raise_for_status()
                logger.debug(
                    "HttpxDriver fetch 성공: url=%s status=%d attempt=%d",
                    url,
                    response.status_code,
                    attempt,
                )
                return PageResult(
                    url=url,
                    html=response.text,
                    status_code=response.status_code,
                    elapsed_seconds=elapsed,
                    success=True,
                )
            except httpx.HTTPStatusError as exc:
                elapsed = time.perf_counter() - start
                last_error = f"HTTP {exc.response.status_code}: {exc}"
                logger.warning(
                    "HttpxDriver HTTP 에러: url=%s attempt=%d/%d error=%s",
                    url,
                    attempt,
                    self.max_retries,
                    last_error,
                )
                if attempt == self.max_retries:
                    return PageResult(
                        url=url,
                        html="",
                        status_code=exc.response.status_code,
                        elapsed_seconds=elapsed,
                        success=False,
                        error=last_error,
                    )
            except httpx.RequestError as exc:
                elapsed = time.perf_counter() - start
                last_error = str(exc)
                logger.warning(
                    "HttpxDriver 요청 에러: url=%s attempt=%d/%d error=%s",
                    url,
                    attempt,
                    self.max_retries,
                    last_error,
                )
                if attempt == self.max_retries:
                    return PageResult(
                        url=url,
                        html="",
                        status_code=0,
                        elapsed_seconds=elapsed,
                        success=False,
                        error=last_error,
                    )
            except Exception as exc:
                elapsed = time.perf_counter() - start
                last_error = str(exc)
                logger.error(
                    "HttpxDriver 예외: url=%s attempt=%d/%d error=%s",
                    url,
                    attempt,
                    self.max_retries,
                    last_error,
                )
                if attempt == self.max_retries:
                    return PageResult(
                        url=url,
                        html="",
                        status_code=0,
                        elapsed_seconds=elapsed,
                        success=False,
                        error=last_error,
                    )

        # 도달하지 않아야 하지만 타입 안전을 위해
        return PageResult(
            url=url,
            html="",
            status_code=0,
            elapsed_seconds=0.0,
            success=False,
            error=last_error,
        )

    async def close(self) -> None:
        """httpx.AsyncClient를 종료한다."""
        if self._client and not self._client.is_closed:
            try:
                await self._client.aclose()
                logger.debug("HttpxDriver 클라이언트 종료 완료")
            except Exception as exc:
                logger.error("HttpxDriver 종료 중 예외: %s", exc)


class SeleniumDriver(BaseDriver):
    """Selenium WebDriver 기반 드라이버 (JS 렌더링 필요 시).

    Args:
        headless: 헤드리스 모드, 기본 True
        wait_seconds: 페이지 로드 대기(초), 기본 3
        scroll_to_bottom: 페이지 하단 스크롤 여부, 기본 False
    """

    def __init__(
        self,
        headless: bool = True,
        wait_seconds: int = 3,
        scroll_to_bottom: bool = False,
    ) -> None:
        self.headless = headless
        self.wait_seconds = wait_seconds
        self.scroll_to_bottom = scroll_to_bottom
        self._driver: object | None = None
        self._selenium_available = self._check_selenium()

    def _check_selenium(self) -> bool:
        """selenium 패키지 설치 여부를 확인한다."""
        try:
            import selenium  # noqa: F401

            return True
        except ImportError:
            logger.warning(
                "selenium 미설치. SeleniumDriver를 사용하려면 "
                "`pip install selenium webdriver-manager` 실행 필요"
            )
            return False

    def _create_driver(self) -> object:
        """Chrome WebDriver 인스턴스를 생성한다.

        Returns:
            selenium.webdriver.Chrome 인스턴스

        Raises:
            ImportError: selenium 또는 webdriver-manager 미설치 시
        """
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
        except ImportError as exc:
            raise ImportError(
                "selenium 또는 webdriver-manager 패키지가 설치되지 않았음. "
                "`pip install selenium webdriver-manager` 실행 필요"
            ) from exc

        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        return driver

    def _sync_fetch(self, url: str) -> PageResult:
        """동기 방식으로 URL을 가져온다 (asyncio.to_thread로 호출됨).

        Args:
            url: 가져올 URL

        Returns:
            PageResult: 크롤링 결과
        """
        try:
            import time as _time

            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError as exc:
            return PageResult(
                url=url,
                html="",
                status_code=0,
                elapsed_seconds=0.0,
                success=False,
                error=str(exc),
            )

        if self._driver is None:
            try:
                self._driver = self._create_driver()
            except Exception as exc:
                logger.error("SeleniumDriver 초기화 실패: %s", exc)
                return PageResult(
                    url=url,
                    html="",
                    status_code=0,
                    elapsed_seconds=0.0,
                    success=False,
                    error=str(exc),
                )

        start = _time.perf_counter()
        try:
            self._driver.get(url)  # type: ignore[attr-defined]
            _time.sleep(self.wait_seconds)

            if self.scroll_to_bottom:
                self._driver.execute_script(  # type: ignore[attr-defined]
                    "window.scrollTo(0, document.body.scrollHeight);"
                )
                _time.sleep(1)

            html = self._driver.page_source  # type: ignore[attr-defined]
            elapsed = _time.perf_counter() - start
            logger.debug("SeleniumDriver fetch 성공: url=%s", url)
            return PageResult(
                url=url,
                html=html,
                status_code=200,
                elapsed_seconds=elapsed,
                success=True,
            )
        except Exception as exc:
            elapsed = _time.perf_counter() - start
            logger.error("SeleniumDriver fetch 실패: url=%s error=%s", url, exc)
            return PageResult(
                url=url,
                html="",
                status_code=0,
                elapsed_seconds=elapsed,
                success=False,
                error=str(exc),
            )

    async def fetch(self, url: str) -> PageResult:
        """URL을 비동기로 가져온다 (내부적으로 asyncio.to_thread 사용).

        Args:
            url: 가져올 URL

        Returns:
            PageResult: 크롤링 결과
        """
        if not self._selenium_available:
            return PageResult(
                url=url,
                html="",
                status_code=0,
                elapsed_seconds=0.0,
                success=False,
                error="selenium 패키지가 설치되지 않았음",
            )
        return await asyncio.to_thread(self._sync_fetch, url)

    def _sync_close(self) -> None:
        """WebDriver를 동기 방식으로 종료한다."""
        if self._driver is not None:
            try:
                self._driver.quit()  # type: ignore[attr-defined]
                self._driver = None
                logger.debug("SeleniumDriver 종료 완료")
            except Exception as exc:
                logger.error("SeleniumDriver 종료 중 예외: %s", exc)

    async def close(self) -> None:
        """WebDriver를 비동기로 종료한다."""
        await asyncio.to_thread(self._sync_close)


class APIDriver(BaseDriver):
    """REST API 기반 드라이버 (공개 API 직접 호출 시).

    JSON 응답의 경우 html 필드에 JSON 문자열을 저장한다.

    Args:
        base_url: API 베이스 URL
        api_key: API 키 (선택)
        headers: 추가 HTTP 헤더 (선택)
    """

    def __init__(
        self,
        base_url: str = "",
        api_key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._base_headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if api_key:
            self._base_headers["Authorization"] = f"Bearer {api_key}"
        if headers:
            self._base_headers.update(headers)
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """AsyncClient 인스턴스를 반환한다 (지연 초기화)."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self._base_headers,
                timeout=30,
                follow_redirects=True,
            )
        return self._client

    def _build_url(self, url: str) -> str:
        """base_url과 url을 합쳐 최종 URL을 반환한다.

        Args:
            url: 엔드포인트 경로 또는 전체 URL

        Returns:
            완성된 URL 문자열
        """
        if url.startswith("http://") or url.startswith("https://"):
            return url
        return f"{self.base_url}/{url.lstrip('/')}"

    async def fetch(self, url: str) -> PageResult:
        """API 엔드포인트를 호출해 PageResult를 반환한다.

        JSON 응답은 json.dumps로 직렬화해 html 필드에 저장한다.

        Args:
            url: 엔드포인트 경로 또는 전체 URL

        Returns:
            PageResult: API 호출 결과
        """
        client = self._get_client()
        full_url = self._build_url(url)
        start = time.perf_counter()

        try:
            response = await client.get(full_url)
            elapsed = time.perf_counter() - start
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    body = json.dumps(response.json(), ensure_ascii=False)
                except Exception:
                    body = response.text
            else:
                body = response.text

            logger.debug(
                "APIDriver fetch 성공: url=%s status=%d",
                full_url,
                response.status_code,
            )
            return PageResult(
                url=full_url,
                html=body,
                status_code=response.status_code,
                elapsed_seconds=elapsed,
                success=True,
            )
        except httpx.HTTPStatusError as exc:
            elapsed = time.perf_counter() - start
            error_msg = f"HTTP {exc.response.status_code}: {exc}"
            logger.error("APIDriver HTTP 에러: url=%s error=%s", full_url, error_msg)
            return PageResult(
                url=full_url,
                html="",
                status_code=exc.response.status_code,
                elapsed_seconds=elapsed,
                success=False,
                error=error_msg,
            )
        except httpx.RequestError as exc:
            elapsed = time.perf_counter() - start
            error_msg = str(exc)
            logger.error("APIDriver 요청 에러: url=%s error=%s", full_url, error_msg)
            return PageResult(
                url=full_url,
                html="",
                status_code=0,
                elapsed_seconds=elapsed,
                success=False,
                error=error_msg,
            )
        except Exception as exc:
            elapsed = time.perf_counter() - start
            error_msg = str(exc)
            logger.error("APIDriver 예외: url=%s error=%s", full_url, error_msg)
            return PageResult(
                url=full_url,
                html="",
                status_code=0,
                elapsed_seconds=elapsed,
                success=False,
                error=error_msg,
            )

    async def close(self) -> None:
        """httpx.AsyncClient를 종료한다."""
        if self._client and not self._client.is_closed:
            try:
                await self._client.aclose()
                logger.debug("APIDriver 클라이언트 종료 완료")
            except Exception as exc:
                logger.error("APIDriver 종료 중 예외: %s", exc)
