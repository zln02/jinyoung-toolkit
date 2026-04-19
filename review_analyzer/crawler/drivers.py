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
        scroll_iterations: 무한 스크롤 반복 횟수 (0 = 비활성).
            > 0 이면 document.body.scrollHeight 변화가 멈추거나 N회 도달할 때까지 반복 스크롤.
    """

    # 봇 감지 우회용 기본 User-Agent (실제 Chrome 146 Linux)
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        headless: bool = True,
        wait_seconds: int = 3,
        scroll_to_bottom: bool = False,
        scroll_iterations: int = 0,
        user_agent: str | None = None,
        stealth: bool = True,
        scroll_into_view_selector: str | None = None,
    ) -> None:
        self.headless = headless
        self.wait_seconds = wait_seconds
        self.scroll_to_bottom = scroll_to_bottom
        self.scroll_iterations = scroll_iterations
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT
        self.stealth = stealth
        # 특정 요소(예: ytd-comments)로 먼저 점프한 뒤 스크롤 시작.
        # 기본 scroll_to_bottom만으로 lazy-load가 트리거 안 되는 사이트용.
        self.scroll_into_view_selector = scroll_into_view_selector
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
        """Chrome/Chromium WebDriver 인스턴스를 생성한다.

        시스템에 설치된 Chromium을 우선 사용하고, chromedriver도 시스템 경로를
        우선 탐색한다. 둘 다 없으면 webdriver-manager로 폴백한다.

        Returns:
            selenium.webdriver.Chrome 인스턴스

        Raises:
            ImportError: selenium 미설치 시
        """
        import os
        import shutil

        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
        except ImportError as exc:
            raise ImportError(
                "selenium 패키지가 설치되지 않았음. `pip install selenium` 실행 필요"
            ) from exc

        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-sync")
        options.add_argument("--disable-default-apps")
        options.add_argument("--window-size=1280,800")
        options.add_argument(f"--user-agent={self.user_agent}")
        options.add_argument("--lang=ko-KR,ko")

        # 봇 감지 우회 (navigator.webdriver 숨김)
        if self.stealth:
            options.add_argument("--disable-blink-features=AutomationControlled")
            try:
                options.add_experimental_option(
                    "excludeSwitches", ["enable-automation"]
                )
                options.add_experimental_option("useAutomationExtension", False)
            except Exception:
                # 일부 Selenium 버전에서 experimental_option 미지원
                pass

        # Chromium/Chrome binary 자동 감지 (Linux 우선)
        binary_candidates = [
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
        ]
        for path in binary_candidates:
            if os.path.exists(path):
                options.binary_location = path
                break
        # (macOS/Windows는 binary_location 없이 Selenium 기본 탐색에 맡김)

        # chromedriver 자동 감지: 시스템 우선, 없으면 webdriver-manager 폴백
        chromedriver_path = shutil.which("chromedriver")
        if chromedriver_path:
            service = Service(chromedriver_path)
        else:
            try:
                from webdriver_manager.chrome import ChromeDriverManager

                service = Service(ChromeDriverManager().install())
            except ImportError as exc:
                raise ImportError(
                    "chromedriver를 찾을 수 없고 webdriver-manager도 설치되지 않았음. "
                    "`sudo apt install chromium-driver` 또는 "
                    "`pip install webdriver-manager` 실행 필요"
                ) from exc

        driver = webdriver.Chrome(service=service, options=options)

        # navigator.webdriver 속성을 undefined로 덮어씀 (stealth)
        if self.stealth:
            try:
                driver.execute_cdp_cmd(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {
                        "source": (
                            "Object.defineProperty(navigator, 'webdriver', "
                            "{get: () => undefined})"
                        )
                    },
                )
            except Exception as exc:
                logger.debug("CDP stealth 스크립트 주입 실패(무시): %s", exc)

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

            # 특정 요소로 먼저 점프 (lazy-load 트리거용, 예: YouTube ytd-comments)
            if self.scroll_into_view_selector:
                try:
                    self._driver.execute_script(  # type: ignore[attr-defined]
                        "const el = document.querySelector(arguments[0]); "
                        "if (el) el.scrollIntoView({block: 'center'});",
                        self.scroll_into_view_selector,
                    )
                    _time.sleep(self.wait_seconds)
                except Exception as exc:
                    logger.warning(
                        "scroll_into_view 실패: selector=%s error=%s",
                        self.scroll_into_view_selector,
                        exc,
                    )

            # scroll_into_view를 쓸 때는 scrollTo(scrollHeight) 건너뛰기.
            # YouTube 등 lazy-load 사이트에서 맨 아래로 한 번에 가면 로드가 안 됨.
            incremental_mode = bool(self.scroll_into_view_selector)

            if self.scroll_to_bottom and not incremental_mode:
                self._driver.execute_script(  # type: ignore[attr-defined]
                    "window.scrollTo(0, document.body.scrollHeight);"
                )
                _time.sleep(1)

            if self.scroll_iterations > 0:
                # 점진 모드: scrollBy(innerHeight) — lazy-load 유발용 (YouTube 등)
                # 일반 모드: scrollTo(scrollHeight) — 페이지 끝으로 점프
                scroll_js = (
                    "window.scrollBy(0, window.innerHeight);"
                    if incremental_mode
                    else "window.scrollTo(0, document.body.scrollHeight);"
                )
                try:
                    prev_height = self._driver.execute_script(  # type: ignore[attr-defined]
                        "return document.body.scrollHeight;"
                    )
                except Exception as exc:
                    logger.warning("scroll_iterations 초기 높이 조회 실패: %s", exc)
                    prev_height = 0

                for _i in range(self.scroll_iterations):
                    try:
                        self._driver.execute_script(scroll_js)  # type: ignore[attr-defined]
                    except Exception as exc:
                        logger.warning("scroll_iterations 스크롤 실패: %s", exc)
                        break
                    _time.sleep(self.wait_seconds)
                    try:
                        new_height = self._driver.execute_script(  # type: ignore[attr-defined]
                            "return document.body.scrollHeight;"
                        )
                    except Exception as exc:
                        logger.warning("scroll_iterations 새 높이 조회 실패: %s", exc)
                        break
                    # 점진 모드에서는 높이 변화 없어도 계속 (YouTube는 댓글 로드돼도 height 안 변함)
                    if not incremental_mode and new_height == prev_height:
                        logger.debug(
                            "scroll_iterations 종료(높이 변화 없음): iter=%d height=%s",
                            _i + 1,
                            new_height,
                        )
                        break
                    prev_height = new_height

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

    def _sync_click_next(self, selector: str, wait_seconds: int | None = None) -> bool:
        """동기 방식으로 "다음" 페이지 버튼을 클릭한다.

        CSS 셀렉터로 다음 버튼을 찾아 scrollIntoView 후 클릭한다.
        disabled 속성/클래스가 있거나 요소가 없으면 마지막 페이지로 간주해 False 반환.

        Args:
            selector: 다음 버튼 CSS 셀렉터
            wait_seconds: 클릭 후 대기 시간(초). None이면 self.wait_seconds 사용.

        Returns:
            클릭 성공 시 True, 마지막 페이지(또는 클릭 불가)이면 False
        """
        if self._driver is None:
            logger.warning("SeleniumDriver click_next: 드라이버가 초기화되지 않았음")
            return False

        try:
            import time as _time

            from selenium.common.exceptions import (
                ElementClickInterceptedException,
                NoSuchElementException,
            )
            from selenium.webdriver.common.by import By
        except ImportError as exc:
            logger.error("SeleniumDriver click_next: import 실패 error=%s", exc)
            return False

        wait = wait_seconds if wait_seconds is not None else self.wait_seconds

        try:
            element = self._driver.find_element(By.CSS_SELECTOR, selector)  # type: ignore[attr-defined]
        except NoSuchElementException:
            logger.debug("SeleniumDriver click_next: 다음 버튼 없음 (마지막 페이지) selector=%s", selector)
            return False
        except Exception as exc:
            logger.warning("SeleniumDriver click_next: 요소 검색 실패 error=%s", exc)
            return False

        try:
            disabled_attr = element.get_attribute("disabled")
            aria_disabled = element.get_attribute("aria-disabled")
            class_attr = element.get_attribute("class") or ""
            if (
                disabled_attr
                or (aria_disabled and aria_disabled.lower() == "true")
                or "disabled" in class_attr.lower()
            ):
                logger.debug(
                    "SeleniumDriver click_next: 버튼 비활성화 상태 selector=%s",
                    selector,
                )
                return False
        except Exception as exc:
            logger.debug("SeleniumDriver click_next: disabled 체크 실패(무시) error=%s", exc)

        try:
            self._driver.execute_script(  # type: ignore[attr-defined]
                "arguments[0].scrollIntoView({block: 'center'});", element
            )
            _time.sleep(0.3)
            element.click()
            _time.sleep(wait)
            logger.debug("SeleniumDriver click_next: 클릭 성공 selector=%s", selector)
            return True
        except ElementClickInterceptedException as exc:
            logger.warning("SeleniumDriver click_next: 클릭 차단 error=%s", exc)
            try:
                self._driver.execute_script("arguments[0].click();", element)  # type: ignore[attr-defined]
                _time.sleep(wait)
                return True
            except Exception as exc2:
                logger.warning("SeleniumDriver click_next: JS 클릭도 실패 error=%s", exc2)
                return False
        except Exception as exc:
            logger.warning("SeleniumDriver click_next: 클릭 예외 error=%s", exc)
            return False

    async def click_next(self, selector: str, wait_seconds: int | None = None) -> bool:
        """다음 페이지 버튼을 비동기로 클릭한다.

        Args:
            selector: 다음 버튼 CSS 셀렉터
            wait_seconds: 클릭 후 대기 시간(초). None이면 self.wait_seconds 사용.

        Returns:
            클릭 성공 시 True, 마지막 페이지이면 False
        """
        if not self._selenium_available:
            return False
        return await asyncio.to_thread(self._sync_click_next, selector, wait_seconds)

    def _sync_get_page_source(self) -> str:
        """현재 DOM의 page_source를 동기 방식으로 반환한다."""
        if self._driver is None:
            return ""
        try:
            return self._driver.page_source  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("SeleniumDriver get_page_source: 예외 error=%s", exc)
            return ""

    async def get_page_source(self) -> str:
        """현재 DOM의 page_source를 비동기로 반환한다."""
        if not self._selenium_available:
            return ""
        return await asyncio.to_thread(self._sync_get_page_source)

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
