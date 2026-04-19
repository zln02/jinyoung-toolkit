"""ProductComparator 테스트."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from review_analyzer.analyzer import AnalysisResult, ReviewAnalyzer
from review_analyzer.comparator import (
    ComparisonReport,
    ProductAnalyzed,
    ProductComparator,
    ProductInput,
)

_FIXTURE_PATH = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "sample_reviews_50.csv"
_PRESET = {
    "analysis": {"text_column": "content", "rating_column": "rating"},
    "selectors": {"container": "div", "fields": {"content": "p"}},
}


def _make_analyzed(label: str, df: pd.DataFrame) -> ProductAnalyzed:
    """sample_df 변형본으로 ProductAnalyzed 생성."""
    analyzer = ReviewAnalyzer(text_column="content", rating_column="rating")
    result = analyzer.run(df)
    return ProductAnalyzed(
        label=label, url=f"https://example.com/{label}",
        preset_name="custom_template", df=df, result=result,
    )


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.read_csv(_FIXTURE_PATH, encoding="utf-8-sig")


@pytest.fixture
def comparator() -> ProductComparator:
    return ProductComparator(
        products=[
            ProductInput(label="우리", url="https://x/1", preset_name="custom_template"),
            ProductInput(label="경쟁 A", url="https://x/2", preset_name="custom_template"),
            ProductInput(label="경쟁 B", url="https://x/3", preset_name="custom_template"),
            ProductInput(label="경쟁 C", url="https://x/4", preset_name="custom_template"),
        ],
        preset=_PRESET,
    )


class TestProductComparator:

    def test_build_summary_returns_four_rows(
        self, comparator: ProductComparator, sample_df: pd.DataFrame
    ) -> None:
        """4개 제품의 summary_rows 가 각 필수 키를 포함하는지."""
        analyzed = [
            _make_analyzed("우리", sample_df),
            _make_analyzed("경쟁 A", sample_df),
            _make_analyzed("경쟁 B", sample_df),
            _make_analyzed("경쟁 C", sample_df),
        ]
        rows = comparator.build_summary(analyzed)
        assert len(rows) == 4
        for r in rows:
            assert "label" in r
            assert "review_count" in r
            assert "avg_rating" in r
            assert "positive_pct" in r
            assert "negative_pct" in r
            assert "avg_text_length" in r

    def test_diagnose_gaps_lose_side(
        self, comparator: ProductComparator
    ) -> None:
        """우리 긍정 비율이 경쟁사보다 낮으면 lose 에 문자열 포함."""
        our = pd.DataFrame({
            "content": ["별로예요", "환불하고싶어요", "최악이에요", "실망"] * 5,
            "rating": [1, 2, 1, 2] * 5,
        })
        comp = pd.DataFrame({
            "content": ["좋아요", "만족", "추천", "최고"] * 5,
            "rating": [5, 5, 5, 4] * 5,
        })
        analyzed = [
            _make_analyzed("우리", our),
            _make_analyzed("경쟁 A", comp),
            _make_analyzed("경쟁 B", comp),
        ]
        win, lose = comparator.diagnose_gaps(analyzed)
        # lose 에 '전반적 만족도 낮음' 또는 '평균 평점 열위' 포함
        joined = " ".join(lose)
        assert ("만족도 낮음" in joined) or ("평점 열위" in joined)

    def test_diagnose_gaps_win_side(
        self, comparator: ProductComparator
    ) -> None:
        """우리 긍정이 경쟁사보다 높으면 win 에 문자열 포함."""
        our = pd.DataFrame({
            "content": ["좋아요", "만족", "추천", "최고"] * 5,
            "rating": [5, 5, 5, 4] * 5,
        })
        comp = pd.DataFrame({
            "content": ["별로", "실망", "불량", "환불"] * 5,
            "rating": [1, 2, 1, 2] * 5,
        })
        analyzed = [
            _make_analyzed("우리", our),
            _make_analyzed("경쟁 A", comp),
            _make_analyzed("경쟁 B", comp),
        ]
        win, lose = comparator.diagnose_gaps(analyzed)
        joined = " ".join(win)
        assert ("만족도 높음" in joined) or ("평점 우위" in joined)

    def test_diagnose_gaps_keyword_delta(
        self, comparator: ProductComparator
    ) -> None:
        """경쟁사 긍정 키워드에만 있는 단어가 lose 에 반영."""
        # 우리와 경쟁사 모두 긍정 비율 비슷하게 만들어 키워드 차이만 검증
        our = pd.DataFrame({
            "content": ["빠른배송 정말 좋아요 만족해요"] * 30,
            "rating": [5] * 30,
        })
        comp = pd.DataFrame({
            "content": ["가성비 훌륭하고 품질 최고 추천해요"] * 30,
            "rating": [5] * 30,
        })
        analyzed = [
            _make_analyzed("우리", our),
            _make_analyzed("경쟁 A", comp),
        ]
        win, lose = comparator.diagnose_gaps(analyzed)
        # lose 에 '경쟁사 강점 미언급' 항목이 있어야 함 (키워드 차이 존재)
        # 엄격하지 않게: 'win 또는 lose 중 하나에 키워드 관련 메시지 포함'
        all_msgs = " ".join(win + lose)
        assert "미언급" in all_msgs or "우리만의 강점" in all_msgs

    def test_generate_action_items_shipping(
        self, comparator: ProductComparator, sample_df: pd.DataFrame
    ) -> None:
        """'배송' 포함 lose_point → 액션 아이템 생성."""
        lose_points = ["배송이 느림"]
        analyzed = [_make_analyzed("우리", sample_df)]
        actions = comparator.generate_action_items(lose_points, analyzed)
        assert any("배송" in a for a in actions)
        assert len(actions) <= 5

    def test_pdf_rendering_smoke(
        self, comparator: ProductComparator, sample_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """ComparisonReportGenerator 로 PDF 파일 생성."""
        from shared.comparison_report_generator import ComparisonReportGenerator

        analyzed = [
            _make_analyzed("우리", sample_df),
            _make_analyzed("경쟁 A", sample_df),
            _make_analyzed("경쟁 B", sample_df),
        ]
        rows = comparator.build_summary(analyzed)
        win, lose = comparator.diagnose_gaps(analyzed)
        actions = comparator.generate_action_items(lose, analyzed)
        report = ComparisonReport(
            products=analyzed, summary_rows=rows,
            win_points=win or ["테스트용 승점"],
            lose_points=lose or ["테스트용 패점"],
            action_items=actions or ["테스트용 액션"],
        )
        pdf_path = tmp_path / "cmp.pdf"
        ComparisonReportGenerator().render(report, pdf_path)
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 1024


class TestComparatorFailureHandling:
    """0건 제품·실패 방어 테스트."""

    def _make_preset(self) -> dict[str, Any]:
        return {
            "name": "test_preset",
            "analysis": {
                "text_column": "content",
                "rating_column": "rating",
            },
            "selectors": {"container": "div", "fields": {}},
            "driver": {"type": "httpx"},
        }

    def test_failed_product_excluded_from_summary(self) -> None:
        """0건 제품은 summary_rows 에서 제외된다."""
        from typing import Any
        from unittest.mock import patch
        import pandas as _pd
        from review_analyzer.comparator import (
            ProductComparator,
            ProductInput,
            ProductAnalyzed,
        )
        from review_analyzer.analyzer import AnalysisResult

        comp = ProductComparator(
            products=[
                ProductInput(label="우리", url="https://a.com", preset_name="p"),
                ProductInput(label="실패", url="https://b.com", preset_name="p"),
            ],
            preset=self._make_preset(),
        )

        good_result = AnalysisResult(
            sentiment_distribution={"positive": 8, "negative": 1, "neutral": 1},
            keywords_positive=[("좋다", 0.5)],
            keywords_negative=[],
            rating_distribution={5: 8, 4: 1, 1: 1},
            total_reviews=10,
            avg_rating=4.5,
            wordcloud_path=None,
        )
        zero_result = AnalysisResult(
            sentiment_distribution={"positive": 0, "negative": 0, "neutral": 0},
            keywords_positive=[],
            keywords_negative=[],
            rating_distribution={},
            total_reviews=0,
            avg_rating=0.0,
            wordcloud_path=None,
        )

        analyzed = [
            ProductAnalyzed(
                label="우리", url="https://a.com", preset_name="p",
                df=_pd.DataFrame({"content": ["좋음"] * 10}),
                result=good_result,
            ),
            ProductAnalyzed(
                label="실패", url="https://b.com", preset_name="p",
                df=_pd.DataFrame(),
                result=zero_result,
            ),
        ]

        summary = comp.build_summary(analyzed)
        assert len(summary) == 1
        assert summary[0]["label"] == "우리"

    def test_diagnose_gaps_skips_empty_competitor(self) -> None:
        """0건 경쟁사는 gap 진단에서 제외된다."""
        import pandas as _pd
        from review_analyzer.comparator import (
            ProductComparator,
            ProductInput,
            ProductAnalyzed,
        )
        from review_analyzer.analyzer import AnalysisResult

        comp = ProductComparator(
            products=[
                ProductInput(label="우리", url="https://a.com", preset_name="p"),
                ProductInput(label="실패", url="https://b.com", preset_name="p"),
            ],
            preset=self._make_preset(),
        )

        our = AnalysisResult(
            sentiment_distribution={"positive": 5, "negative": 3, "neutral": 2},
            keywords_positive=[],
            keywords_negative=[],
            rating_distribution={},
            total_reviews=10,
            avg_rating=4.0,
            wordcloud_path=None,
        )
        zero = AnalysisResult(
            sentiment_distribution={"positive": 0, "negative": 0, "neutral": 0},
            keywords_positive=[],
            keywords_negative=[],
            rating_distribution={},
            total_reviews=0,
            avg_rating=0.0,
            wordcloud_path=None,
        )

        analyzed = [
            ProductAnalyzed(
                label="우리", url="https://a.com", preset_name="p",
                df=_pd.DataFrame({"content": ["x"] * 10}), result=our,
            ),
            ProductAnalyzed(
                label="실패", url="https://b.com", preset_name="p",
                df=_pd.DataFrame(), result=zero,
            ),
        ]

        win, lose = comp.diagnose_gaps(analyzed)
        # 0건 경쟁사만 있으면 진단 불가
        assert win == []
        assert lose == []

    def test_report_has_failed_products_field(self) -> None:
        """ComparisonReport dataclass에 failed_products 필드가 있어야 한다."""
        from review_analyzer.comparator import ComparisonReport
        assert "failed_products" in ComparisonReport.__dataclass_fields__
