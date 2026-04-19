"""selector_inferer 단위 테스트 (모킹 기반).

실 네트워크/LLM 호출 없이 selector_inferer 모듈의 핵심 함수를 검증한다.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from review_analyzer.crawler.drivers import PageResult
from review_analyzer.selector_inferer import (
    SelectorInferenceError,
    _build_messages,
    _build_preset_dict,
    _compress_html,
    _extract_text_from_response,
    _parse_response,
    _validate_with_bs4,
    infer_preset_from_url,
)
from shared.config import AppSettings


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _make_settings(api_key: str | None = "test-key") -> AppSettings:
    """테스트용 AppSettings 생성 (.env 무시)."""
    return AppSettings(
        anthropic_api_key=api_key,
        selector_inference_model="claude-haiku-4-5-20251001",
        _env_file=None,  # type: ignore[call-arg]
    )


def _make_anthropic_response(text: str) -> SimpleNamespace:
    """AsyncAnthropic.messages.create() 응답 mock."""
    block = SimpleNamespace(text=text, type="text")
    return SimpleNamespace(content=[block])


_REVIEW_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>리뷰 페이지</title>
    <style>.hidden { display: none; }</style>
    <script>console.log('tracking');</script>
</head>
<body>
    <div class="reviews">
        <article class="review-item">
            <h3 class="review-title">아주 좋아요</h3>
            <p class="review-content">배송이 빠르고 품질도 좋습니다.</p>
            <span class="review-author">홍길동</span>
        </article>
        <article class="review-item">
            <h3 class="review-title">만족합니다</h3>
            <p class="review-content">가격 대비 훌륭합니다.</p>
            <span class="review-author">김철수</span>
        </article>
        <article class="review-item">
            <h3 class="review-title">재구매 의사 있음</h3>
            <p class="review-content">친구에게도 추천했어요.</p>
            <span class="review-author">이영희</span>
        </article>
    </div>
    <svg width="10"><circle r="5"/></svg>
    <iframe src="https://ads.example.com"></iframe>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# _compress_html
# ---------------------------------------------------------------------------


class TestCompressHtml:

    def test_compress_html_removes_script_style(self) -> None:
        """script/style/svg/iframe 태그가 모두 제거되는지 확인."""
        compressed = _compress_html(_REVIEW_HTML)

        assert "<script" not in compressed
        assert "<style" not in compressed
        assert "<svg" not in compressed
        assert "<iframe" not in compressed
        # 본문은 살아있어야 함
        assert "review-item" in compressed
        assert "아주 좋아요" in compressed

    def test_compress_html_max_chars(self) -> None:
        """max_chars 컷오프가 적용되는지 확인."""
        big_html = "<html><body>" + ("<p>x</p>" * 10000) + "</body></html>"
        compressed = _compress_html(big_html, max_chars=500)

        assert len(compressed) <= 500

    def test_compress_html_removes_event_handlers(self) -> None:
        """on* 핸들러와 style 속성이 제거되는지 확인."""
        html = (
            '<html><body>'
            '<div onclick="alert(1)" style="color:red" data-id="x">hello</div>'
            '</body></html>'
        )
        compressed = _compress_html(html)

        assert "onclick" not in compressed
        assert "style=" not in compressed
        assert "data-id" not in compressed
        assert "hello" in compressed


# ---------------------------------------------------------------------------
# _build_messages
# ---------------------------------------------------------------------------


class TestBuildMessages:

    def test_build_messages_includes_url_and_html(self) -> None:
        """messages payload에 URL과 압축 HTML이 모두 포함되는지 확인."""
        messages = _build_messages("<body>compressed</body>", "https://example.com")

        assert isinstance(messages, list)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        content = messages[0]["content"]
        assert "https://example.com" in content
        assert "compressed" in content
        # 스키마 키워드 포함
        assert "container" in content
        assert "fields" in content


# ---------------------------------------------------------------------------
# _extract_text_from_response
# ---------------------------------------------------------------------------


class TestExtractTextFromResponse:

    def test_extract_text_from_text_blocks(self) -> None:
        """SimpleNamespace 블록에서 text 추출."""
        response = _make_anthropic_response('{"container": "div"}')
        assert _extract_text_from_response(response) == '{"container": "div"}'

    def test_extract_text_empty(self) -> None:
        """content가 없으면 빈 문자열."""
        empty = SimpleNamespace(content=None)
        assert _extract_text_from_response(empty) == ""


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:

    def test_parse_response_strips_codeblock(self) -> None:
        """```json ... ``` 블럭이 벗겨지는지 확인."""
        text = '```json\n{"container": "div.item", "fields": {"title": "h3"}}\n```'
        result = _parse_response(text)

        assert result["container"] == "div.item"
        assert result["fields"] == {"title": "h3"}

    def test_parse_response_plain_json(self) -> None:
        """순수 JSON 응답 파싱."""
        text = '{"container": ".x", "fields": {"content": "p"}}'
        result = _parse_response(text)

        assert result["container"] == ".x"
        assert result["fields"]["content"] == "p"

    def test_parse_response_extra_text_around_json(self) -> None:
        """JSON 앞뒤 부가 텍스트가 있어도 추출되는지."""
        text = '여기 결과입니다: {"container": "li", "fields": {"name": "span"}} 끝'
        result = _parse_response(text)

        assert result["container"] == "li"

    def test_parse_response_missing_container_raises(self) -> None:
        """container 키가 없으면 SelectorInferenceError."""
        text = '{"fields": {"title": "h1"}}'
        with pytest.raises(SelectorInferenceError, match="container"):
            _parse_response(text)

    def test_parse_response_missing_fields_raises(self) -> None:
        """fields 키가 없으면 SelectorInferenceError."""
        text = '{"container": "div"}'
        with pytest.raises(SelectorInferenceError, match="fields"):
            _parse_response(text)

    def test_parse_response_empty_fields_raises(self) -> None:
        """fields가 빈 dict이면 SelectorInferenceError."""
        text = '{"container": "div", "fields": {}}'
        with pytest.raises(SelectorInferenceError, match="fields"):
            _parse_response(text)

    def test_parse_response_invalid_json_raises(self) -> None:
        """파싱 불가능한 응답이면 SelectorInferenceError."""
        text = "이건 JSON이 아닙니다"
        with pytest.raises(SelectorInferenceError, match="JSON"):
            _parse_response(text)


# ---------------------------------------------------------------------------
# _validate_with_bs4
# ---------------------------------------------------------------------------


class TestValidateWithBs4:

    def test_validate_with_bs4_pass(self) -> None:
        """정확한 셀렉터로 container >=2 + fields 매칭 확인."""
        selectors = {
            "container": "article.review-item",
            "fields": {
                "title": "h3.review-title",
                "content": "p.review-content",
                "reviewer": "span.review-author",
            },
        }
        ok, count = _validate_with_bs4(_REVIEW_HTML, selectors)

        assert ok is True
        assert count == 3

    def test_validate_with_bs4_fail_too_few(self) -> None:
        """container 매칭이 1개 이하면 실패."""
        html = "<html><body><div class='only'>x</div></body></html>"
        selectors = {
            "container": "div.only",
            "fields": {"text": "div"},
        }
        ok, count = _validate_with_bs4(html, selectors)

        assert ok is False
        assert count == 1

    def test_validate_with_bs4_fail_no_field_match(self) -> None:
        """container는 충분한데 fields가 매칭 안 되면 실패."""
        selectors = {
            "container": "article.review-item",
            "fields": {
                "nonexistent": "div.totally-fake-class",
            },
        }
        ok, count = _validate_with_bs4(_REVIEW_HTML, selectors)

        assert ok is False
        assert count == 3

    def test_validate_with_bs4_invalid_container_selector(self) -> None:
        """container 셀렉터 자체가 잘못되면 실패."""
        selectors = {
            "container": ">>>invalid<<<",
            "fields": {"title": "h3"},
        }
        ok, count = _validate_with_bs4(_REVIEW_HTML, selectors)

        assert ok is False
        assert count == 0


# ---------------------------------------------------------------------------
# _build_preset_dict
# ---------------------------------------------------------------------------


class TestBuildPresetDict:

    def test_build_preset_dict_minimal(self) -> None:
        """필수 키가 모두 들어 있는 dict가 생성되는지."""
        selectors = {
            "container": "article.item",
            "fields": {"content": "p", "title": "h1"},
        }
        preset = _build_preset_dict(
            url="https://example.com/reviews",
            selectors=selectors,
        )

        assert preset["name"].startswith("auto_")
        assert "example_com" in preset["name"]
        assert preset["display_name"].startswith("자동 추론")
        assert preset["selectors"]["container"] == "article.item"
        assert preset["selectors"]["fields"] == {"content": "p", "title": "h1"}
        # text_column은 content 우선 선택
        assert preset["analysis"]["text_column"] == "content"

    def test_build_preset_dict_text_column_fallback(self) -> None:
        """content/review/text가 없으면 첫 번째 키 fallback."""
        selectors = {
            "container": "div",
            "fields": {"username": "span", "score": "em"},
        }
        preset = _build_preset_dict(
            url="https://foo.bar/page",
            selectors=selectors,
        )

        assert preset["analysis"]["text_column"] in ("username", "score")

    def test_build_preset_dict_passes_preset_loader_schema(self) -> None:
        """생성된 dict가 PresetLoader._validate_schema를 통과하는지."""
        from review_analyzer.preset_loader import PresetLoader

        selectors = {
            "container": "div.item",
            "fields": {"content": "p"},
        }
        preset = _build_preset_dict(
            url="https://example.com/x",
            selectors=selectors,
        )
        loader = PresetLoader()
        # 예외 발생하지 않으면 통과
        loader._validate_schema(preset, "auto_test")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# infer_preset_from_url (통합)
# ---------------------------------------------------------------------------


class TestInferPresetFromUrl:

    @pytest.mark.asyncio
    async def test_infer_preset_no_api_key_raises(self) -> None:
        """API 키가 없으면 SelectorInferenceError 발생."""
        settings = _make_settings(api_key=None)

        with pytest.raises(SelectorInferenceError, match="ANTHROPIC_API_KEY"):
            await infer_preset_from_url(
                "https://example.com",
                settings=settings,
            )

    @pytest.mark.asyncio
    async def test_infer_preset_full_mock(self) -> None:
        """HttpxDriver + AsyncAnthropic 둘 다 mock한 정상 흐름."""
        settings = _make_settings(api_key="sk-test")

        # 1) fetch_driver mock
        mock_driver = MagicMock()
        mock_driver.fetch = AsyncMock(
            return_value=PageResult(
                url="https://example.com/reviews",
                html=_REVIEW_HTML,
                status_code=200,
                elapsed_seconds=0.01,
                success=True,
            )
        )
        mock_driver.close = AsyncMock()

        # 2) AsyncAnthropic mock
        llm_response = _make_anthropic_response(
            '{"container": "article.review-item", '
            '"fields": {"title": "h3.review-title", '
            '"content": "p.review-content", '
            '"reviewer": "span.review-author"}}'
        )
        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=llm_response)

        with patch(
            "anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            preset = await infer_preset_from_url(
                "https://example.com/reviews",
                settings=settings,
                fetch_driver=mock_driver,
            )

        assert preset["selectors"]["container"] == "article.review-item"
        assert "title" in preset["selectors"]["fields"]
        assert preset["analysis"]["text_column"] == "content"
        assert preset["name"].startswith("auto_")
        mock_driver.fetch.assert_awaited_once()
        mock_client.messages.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_infer_preset_validation_fail_raises(self) -> None:
        """LLM이 매칭 안 되는 셀렉터를 반환하면 검증 단계에서 실패."""
        settings = _make_settings(api_key="sk-test")

        mock_driver = MagicMock()
        mock_driver.fetch = AsyncMock(
            return_value=PageResult(
                url="https://example.com",
                html=_REVIEW_HTML,
                status_code=200,
                elapsed_seconds=0.01,
                success=True,
            )
        )
        mock_driver.close = AsyncMock()

        # 의도적으로 페이지에 없는 셀렉터 반환
        bad_response = _make_anthropic_response(
            '{"container": "div.does-not-exist", '
            '"fields": {"x": "span.also-fake"}}'
        )
        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=bad_response)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            with pytest.raises(SelectorInferenceError, match="매칭"):
                await infer_preset_from_url(
                    "https://example.com",
                    settings=settings,
                    fetch_driver=mock_driver,
                )

    @pytest.mark.asyncio
    async def test_infer_preset_fetch_failure_raises(self) -> None:
        """페이지 fetch 실패 시 SelectorInferenceError."""
        settings = _make_settings(api_key="sk-test")

        mock_driver = MagicMock()
        mock_driver.fetch = AsyncMock(
            return_value=PageResult(
                url="https://example.com",
                html="",
                status_code=500,
                elapsed_seconds=0.01,
                success=False,
                error="server error",
            )
        )
        mock_driver.close = AsyncMock()

        with pytest.raises(SelectorInferenceError, match="fetch 실패"):
            await infer_preset_from_url(
                "https://example.com",
                settings=settings,
                fetch_driver=mock_driver,
            )
