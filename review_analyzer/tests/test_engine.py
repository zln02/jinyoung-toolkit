"""CrawlerEngine, CrawlConfig, LegalComplianceChecker 테스트."""

from __future__ import annotations

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
from review_analyzer.crawler.drivers import PageResult


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
