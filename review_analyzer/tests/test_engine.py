"""CrawlerEngine, CrawlConfig, LegalComplianceChecker 테스트."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from review_analyzer.crawler.engine import (
    CrawlConfig,
    CrawlerEngine,
    CrawlResult,
    DriverType,
    LegalComplianceChecker,
)
from review_analyzer.crawler.drivers import PageResult, SeleniumDriver


class TestCrawlerEngine:

    def test_crawl_config_validation(self):
        """CrawlConfig가 올바르게 생성되는지 확인."""
        config = CrawlConfig(
            preset_name="naver_shopping",
            target_urls=["https://example.com/page/1", "https://example.com/page/2"],
            max_pages=10,
            delay_seconds=0.5,
            driver_type=DriverType.HTTPX,
            respect_robots_txt=False,
            filter_pii=True,
        )

        assert config.preset_name == "naver_shopping"
        assert len(config.target_urls) == 2
        assert config.max_pages == 10
        assert config.delay_seconds == 0.5
        assert config.driver_type == DriverType.HTTPX
        assert config.respect_robots_txt is False
        assert config.filter_pii is True

    @pytest.mark.asyncio
    async def test_crawl_respects_max_pages(self):
        """max_pages 설정이 크롤링에 반영되는지 확인.

        httpx를 mock하여 max_pages만큼만 요청하는지 검증.
        """
        urls = [f"https://example.com/page/{i}" for i in range(10)]
        config = CrawlConfig(
            preset_name="test",
            target_urls=urls,
            max_pages=3,
            delay_seconds=0.0,
            respect_robots_txt=False,
            filter_pii=False,
        )
        preset = {
            "selectors": {
                "container": "div.item",
                "fields": {"content": "span.text"},
            }
        }

        mock_page_result = PageResult(
            url="https://example.com",
            html="<div class='item'><span class='text'>테스트</span></div>",
            status_code=200,
            elapsed_seconds=0.01,
            success=True,
        )

        mock_driver = AsyncMock()
        mock_driver.fetch = AsyncMock(return_value=mock_page_result)
        mock_driver.close = AsyncMock()

        with patch(
            "review_analyzer.crawler.engine.HttpxDriver",
            return_value=mock_driver,
        ):
            engine = CrawlerEngine(config=config, preset=preset)
            result = await engine.run()

        assert isinstance(result, CrawlResult)
        # max_pages=3이므로 fetch는 최대 3회
        assert mock_driver.fetch.call_count == 3
        assert result.total_collected == 3

    @pytest.mark.asyncio
    async def test_crawl_handles_network_error(self):
        """네트워크 에러 발생 시 errors 리스트에 추가되는지 확인.

        httpx.fetch를 mock해서 Exception 발생시키기.
        """
        config = CrawlConfig(
            preset_name="test",
            target_urls=["https://example.com/page/1"],
            max_pages=5,
            delay_seconds=0.0,
            respect_robots_txt=False,
            filter_pii=False,
        )

        mock_driver = AsyncMock()
        mock_driver.fetch = AsyncMock(
            side_effect=Exception("Connection refused")
        )
        mock_driver.close = AsyncMock()

        with patch(
            "review_analyzer.crawler.engine.HttpxDriver",
            return_value=mock_driver,
        ):
            engine = CrawlerEngine(config=config)
            result = await engine.run()

        assert result.total_failed == 1
        assert len(result.errors) == 1
        assert "Connection refused" in result.errors[0]["error"]
        assert result.total_collected == 0

    def test_legal_compliance_pii_masking(self):
        """PII 마스킹이 올바르게 동작하는지 확인.

        이메일, 전화번호, 주민번호가 마스킹되는지 검증.
        """
        df = pd.DataFrame(
            {
                "content": [
                    "연락처 hong@example.com 으로 주세요.",
                    "전화 010-1234-5678 입니다.",
                    "주민번호 901231-1234567 확인 바랍니다.",
                    "개인정보 없는 일반 리뷰입니다.",
                ]
            }
        )

        masked_df = LegalComplianceChecker.mask_pii(df, columns=["content"])

        # 이메일 마스킹 확인
        assert "hong@example.com" not in masked_df["content"][0]
        assert "h***@e***" in masked_df["content"][0] or "***@" in masked_df["content"][0]

        # 전화번호 마스킹 확인 — 중간 4자리가 ****로 치환
        assert "010-****-5678" in masked_df["content"][1]

        # 주민번호 마스킹 확인 — 뒷자리가 *******로 치환
        assert "901231-*******" in masked_df["content"][2]

        # 마스킹 불필요한 행은 원본 유지
        assert masked_df["content"][3] == "개인정보 없는 일반 리뷰입니다."

        # 원본 df 불변 검증
        assert "010-1234-5678" in df["content"][1]


class TestPagination:
    """페이지네이션(클릭 기반) 테스트."""

    _SELECTORS = {
        "container": "div.item",
        "fields": {"content": "span.text"},
    }
    _PRESET_WITH_PAGINATION = {
        "selectors": _SELECTORS,
        "pagination": {
            "type": "click",
            "next_button_selector": "a.next",
            "max_pages": 5,
        },
    }

    @staticmethod
    def _make_html(text: str) -> str:
        return f"<div class='item'><span class='text'>{text}</span></div>"

    @pytest.mark.asyncio
    async def test_pagination_click_multi_pages(self):
        """SeleniumDriver + click_next 2회 성공 → 3페이지(1+2) 수집."""
        config = CrawlConfig(
            preset_name="test",
            target_urls=["https://example.com/reviews"],
            max_pages=10,
            delay_seconds=0.0,
            driver_type=DriverType.SELENIUM,
            respect_robots_txt=False,
            filter_pii=False,
        )

        page1_html = self._make_html("page1")
        page2_html = self._make_html("page2")
        page3_html = self._make_html("page3")

        mock_driver = MagicMock(spec=SeleniumDriver)
        mock_driver.fetch = AsyncMock(
            return_value=PageResult(
                url="https://example.com/reviews",
                html=page1_html,
                status_code=200,
                elapsed_seconds=0.01,
                success=True,
            )
        )
        # 2번 성공, 3번째는 마지막 페이지(False)
        mock_driver.click_next = AsyncMock(side_effect=[True, True, False])
        mock_driver.get_page_source = AsyncMock(side_effect=[page2_html, page3_html])
        mock_driver.close = AsyncMock()

        with patch.object(
            CrawlerEngine, "_create_driver", return_value=mock_driver
        ):
            engine = CrawlerEngine(
                config=config, preset=self._PRESET_WITH_PAGINATION
            )
            result = await engine.run()

        assert result.total_collected == 3
        assert mock_driver.click_next.call_count == 3
        assert mock_driver.get_page_source.call_count == 2
        contents = sorted(result.data["content"].tolist())
        assert contents == ["page1", "page2", "page3"]

    @pytest.mark.asyncio
    async def test_pagination_disabled_for_httpx(self):
        """HttpxDriver는 pagination 설정이 있어도 URL 순회만 수행."""
        urls = [
            "https://example.com/page/1",
            "https://example.com/page/2",
        ]
        config = CrawlConfig(
            preset_name="test",
            target_urls=urls,
            max_pages=10,
            delay_seconds=0.0,
            driver_type=DriverType.HTTPX,
            respect_robots_txt=False,
            filter_pii=False,
        )

        mock_driver = AsyncMock()
        mock_driver.fetch = AsyncMock(
            return_value=PageResult(
                url="https://example.com",
                html=self._make_html("data"),
                status_code=200,
                elapsed_seconds=0.01,
                success=True,
            )
        )
        mock_driver.close = AsyncMock()
        # HttpxDriver는 click_next 메서드 자체가 없어야 정상 — mock에 추가하지 않음
        assert not hasattr(mock_driver, "click_next") or isinstance(
            mock_driver.click_next, AsyncMock
        )

        with patch(
            "review_analyzer.crawler.engine.HttpxDriver",
            return_value=mock_driver,
        ):
            engine = CrawlerEngine(
                config=config, preset=self._PRESET_WITH_PAGINATION
            )
            result = await engine.run()

        # URL 순회만 → fetch 2회, click_next 호출 0회 보장
        assert mock_driver.fetch.call_count == 2
        assert result.total_collected == 2

    @pytest.mark.asyncio
    async def test_pagination_stops_on_empty_page(self):
        """click_next True지만 파싱 결과 0건 → 페이지네이션 중단."""
        config = CrawlConfig(
            preset_name="test",
            target_urls=["https://example.com/reviews"],
            max_pages=10,
            delay_seconds=0.0,
            driver_type=DriverType.SELENIUM,
            respect_robots_txt=False,
            filter_pii=False,
        )

        page1_html = self._make_html("page1")
        empty_html = "<html><body>nothing here</body></html>"

        mock_driver = MagicMock(spec=SeleniumDriver)
        mock_driver.fetch = AsyncMock(
            return_value=PageResult(
                url="https://example.com/reviews",
                html=page1_html,
                status_code=200,
                elapsed_seconds=0.01,
                success=True,
            )
        )
        mock_driver.click_next = AsyncMock(return_value=True)
        mock_driver.get_page_source = AsyncMock(return_value=empty_html)
        mock_driver.close = AsyncMock()

        with patch.object(
            CrawlerEngine, "_create_driver", return_value=mock_driver
        ):
            engine = CrawlerEngine(
                config=config, preset=self._PRESET_WITH_PAGINATION
            )
            result = await engine.run()

        # 1페이지만 수집되고 빈 페이지 검출 시 break
        assert result.total_collected == 1
        # click_next는 page=2 한 번만 호출되고 중단되어야 함
        assert mock_driver.click_next.call_count == 1
        assert mock_driver.get_page_source.call_count == 1

    @pytest.mark.asyncio
    async def test_pagination_no_config_fallback(self):
        """pagination 섹션이 없으면 기존 동작(URL 순회) 유지."""
        urls = [
            "https://example.com/page/1",
            "https://example.com/page/2",
        ]
        config = CrawlConfig(
            preset_name="test",
            target_urls=urls,
            max_pages=10,
            delay_seconds=0.0,
            driver_type=DriverType.SELENIUM,
            respect_robots_txt=False,
            filter_pii=False,
        )
        preset_no_pagination = {"selectors": self._SELECTORS}

        mock_driver = MagicMock(spec=SeleniumDriver)
        mock_driver.fetch = AsyncMock(
            return_value=PageResult(
                url="https://example.com",
                html=self._make_html("data"),
                status_code=200,
                elapsed_seconds=0.01,
                success=True,
            )
        )
        mock_driver.click_next = AsyncMock(return_value=True)
        mock_driver.get_page_source = AsyncMock(return_value="")
        mock_driver.close = AsyncMock()

        with patch.object(
            CrawlerEngine, "_create_driver", return_value=mock_driver
        ):
            engine = CrawlerEngine(config=config, preset=preset_no_pagination)
            result = await engine.run()

        # pagination 미설정 → click_next 호출 안 됨, fetch만 2회
        assert mock_driver.fetch.call_count == 2
        assert mock_driver.click_next.call_count == 0
        assert result.total_collected == 2


class TestUrlParamPagination:
    """url_param 페이지네이션 (_expand_urls) 테스트."""

    def test_expand_urls_url_param(self):
        """url_template + max_pages → N개 URL 생성 (네이버 블로그 start=1,11,21...)."""
        config = CrawlConfig(
            preset_name="naver_blog",
            target_urls=["https://search.naver.com/search.naver?query=python&where=blog"],
            max_pages=3,
            delay_seconds=0.0,
            respect_robots_txt=False,
            filter_pii=False,
        )
        preset = {
            "selectors": {"container": "li.bx", "fields": {"title": "a"}},
            "pagination": {
                "type": "url_param",
                "url_template": "{base}&start={page}",
                "start": 1,
                "step": 10,
                "max_pages": 3,
            },
        }
        engine = CrawlerEngine(config=config, preset=preset)
        expanded = engine._expand_urls(config.target_urls)

        assert len(expanded) == 3
        assert expanded[0].endswith("&start=1")
        assert expanded[1].endswith("&start=11")
        assert expanded[2].endswith("&start=21")

    def test_expand_urls_no_pagination(self):
        """pagination 없으면 그대로 반환."""
        config = CrawlConfig(
            preset_name="test",
            target_urls=["https://a.com", "https://b.com"],
            max_pages=10,
            delay_seconds=0.0,
            respect_robots_txt=False,
            filter_pii=False,
        )
        engine = CrawlerEngine(config=config, preset={})
        result = engine._expand_urls(config.target_urls)
        assert result == ["https://a.com", "https://b.com"]

    def test_expand_urls_absolute_template(self):
        """url_template이 절대 URL이면 그대로 사용."""
        config = CrawlConfig(
            preset_name="apple",
            target_urls=["https://itunes.apple.com/rss/customerreviews/id=1234/json"],
            max_pages=5,
            delay_seconds=0.0,
            respect_robots_txt=False,
            filter_pii=False,
        )
        preset = {
            "selectors": {"format": "json", "container": "feed.entry", "fields": {"x": "y"}},
            "pagination": {
                "type": "url_param",
                "url_template": "{base}?page={page}",
                "start": 1,
                "step": 1,
                "max_pages": 3,
            },
        }
        engine = CrawlerEngine(config=config, preset=preset)
        expanded = engine._expand_urls(config.target_urls)
        assert len(expanded) == 3
        assert all(u.startswith("https://itunes.apple.com/") for u in expanded)
        assert expanded[0].endswith("?page=1")
        assert expanded[2].endswith("?page=3")


class TestJsonParseMode:
    """selectors.format=json 파싱 모드 테스트."""

    def test_parse_page_json_mode(self):
        """selectors.format=json + 점 표기법 fields → 정상 추출."""
        sample = {
            "feed": {
                "entry": [
                    {
                        "author": {"name": {"label": "Alice"}},
                        "im:rating": {"label": "5"},
                        "title": {"label": "Great app"},
                        "content": {"label": "I love it"},
                    },
                    {
                        "author": {"name": {"label": "Bob"}},
                        "im:rating": {"label": "3"},
                        "title": {"label": "OK"},
                        "content": {"label": "Average"},
                    },
                ]
            }
        }
        body = json.dumps(sample)
        selectors = {
            "format": "json",
            "container": "feed.entry",
            "fields": {
                "reviewer": "author.name.label",
                "rating": "im:rating.label",
                "title": "title.label",
                "content": "content.label",
            },
        }
        config = CrawlConfig(
            preset_name="apple",
            target_urls=["https://example.com"],
            max_pages=1,
            delay_seconds=0.0,
            respect_robots_txt=False,
            filter_pii=False,
        )
        engine = CrawlerEngine(config=config, preset={"selectors": selectors})
        records = engine._parse_page(body, selectors)

        assert len(records) == 2
        assert records[0]["reviewer"] == "Alice"
        assert records[0]["rating"] == "5"
        assert records[0]["title"] == "Great app"
        assert records[0]["content"] == "I love it"
        assert records[1]["reviewer"] == "Bob"

    def test_parse_page_json_missing_keys(self):
        """JSON 모드에서 키가 없으면 빈 문자열 반환."""
        body = json.dumps({"feed": {"entry": [{"author": {}}]}})
        selectors = {
            "format": "json",
            "container": "feed.entry",
            "fields": {"reviewer": "author.name.label"},
        }
        config = CrawlConfig(
            preset_name="t",
            target_urls=["https://e.com"],
            respect_robots_txt=False,
            filter_pii=False,
        )
        engine = CrawlerEngine(config=config, preset={"selectors": selectors})
        records = engine._parse_page(body, selectors)
        assert len(records) == 1
        assert records[0]["reviewer"] == ""


class TestSeleniumScrollIterations:
    """SeleniumDriver scroll_iterations 통합 테스트."""

    def test_selenium_scroll_iterations_passed(self):
        """SeleniumDriver 생성 시 scroll_iterations가 pagination.max_pages로 설정됨."""
        config = CrawlConfig(
            preset_name="youtube",
            target_urls=["https://youtube.com/watch?v=xxx"],
            max_pages=15,
            delay_seconds=0.0,
            driver_type=DriverType.SELENIUM,
            respect_robots_txt=False,
            filter_pii=False,
        )
        preset = {
            "driver": {
                "type": "selenium",
                "headless": True,
                "wait_seconds": 4,
                "scroll_to_bottom": True,
            },
            "pagination": {
                "type": "scroll",
                "max_pages": 12,
            },
            "selectors": {"container": "div.x", "fields": {"c": "p"}},
        }

        captured: dict = {}

        def fake_init(
            headless=True,
            wait_seconds=3,
            scroll_to_bottom=False,
            scroll_iterations=0,
            user_agent=None,
            stealth=True,
            scroll_into_view_selector=None,
        ):
            captured["headless"] = headless
            captured["wait_seconds"] = wait_seconds
            captured["scroll_to_bottom"] = scroll_to_bottom
            captured["scroll_iterations"] = scroll_iterations
            return MagicMock(spec=SeleniumDriver)

        with patch(
            "review_analyzer.crawler.engine.SeleniumDriver",
            side_effect=fake_init,
        ):
            engine = CrawlerEngine(config=config, preset=preset)
            engine._create_driver()

        # min(config.max_pages=15, preset max_pages=12) = 12
        assert captured["scroll_iterations"] == 12
        assert captured["wait_seconds"] == 4
        assert captured["scroll_to_bottom"] is True
        assert captured["headless"] is True
