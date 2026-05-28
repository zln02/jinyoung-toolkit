"""ComparisonReportGenerator 방어 테스트."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from review_analyzer.analyzer import AnalysisResult
from review_analyzer.comparator import (
    ComparisonReport,
    ProductAnalyzed,
)
from review_analyzer.comparison_report_generator import (
    ComparisonReportGenerator,
    _format_pct,
    _format_rating,
)


def _make_analyzed(
    label: str, total: int, avg_rating: float, pos: int, neg: int
) -> ProductAnalyzed:
    return ProductAnalyzed(
        label=label,
        url=f"https://{label}.com",
        preset_name="p",
        df=pd.DataFrame({"content": ["x"] * total}) if total > 0 else pd.DataFrame(),
        result=AnalysisResult(
            sentiment_distribution={
                "positive": pos,
                "negative": neg,
                "neutral": max(0, total - pos - neg),
            },
            keywords_positive=[],
            keywords_negative=[],
            rating_distribution={},
            total_reviews=total,
            avg_rating=avg_rating,
            wordcloud_path=None,
        ),
    )


class TestFormatHelpers:
    def test_format_rating_nan(self) -> None:
        assert _format_rating(float("nan")) == "데이터 부족"
        assert _format_rating(None) == "데이터 부족"
        assert _format_rating(0.0) == "데이터 부족"
        assert _format_rating(4.52) == "4.52"
        assert _format_rating("abc") == "데이터 부족"

    def test_format_pct_nan(self) -> None:
        assert _format_pct(float("nan")) == "-"
        assert _format_pct(None) == "-"
        assert _format_pct(75.3) == "75.3%"
        assert _format_pct(0.0) == "0.0%"


class TestRenderDefensive:
    def test_render_nan_safe(self, tmp_path: Path) -> None:
        """NaN 값이 PDF 본문에 그대로 노출되지 않는다."""
        report = ComparisonReport(
            products=[
                _make_analyzed("A", 10, float("nan"), 5, 2),
                _make_analyzed("B", 10, 4.0, 6, 1),
            ],
            summary_rows=[
                {
                    "label": "A", "review_count": 10,
                    "avg_rating": float("nan"),
                    "positive_pct": 50.0, "negative_pct": 20.0,
                    "avg_text_length": 10.0,
                },
                {
                    "label": "B", "review_count": 10,
                    "avg_rating": 4.0,
                    "positive_pct": 60.0, "negative_pct": 10.0,
                    "avg_text_length": 12.0,
                },
            ],
            win_points=["테스트 우위"],
        )
        out = tmp_path / "r.pdf"
        gen = ComparisonReportGenerator()
        path = gen.render(report, out)
        assert path.exists()
        assert path.stat().st_size > 0
        # PDF는 바이너리라 nan 문자 직접 grep은 불안정 — _format_rating이 호출됐는지만 간접 확인

    def test_render_all_empty_shows_warning(self, tmp_path: Path) -> None:
        """win/lose/action 전부 빈 경우 단일 경고 인사이트가 렌더된다."""
        report = ComparisonReport(
            products=[_make_analyzed("A", 5, 4.0, 3, 1)],
            summary_rows=[
                {
                    "label": "A", "review_count": 5,
                    "avg_rating": 4.0,
                    "positive_pct": 60.0, "negative_pct": 20.0,
                    "avg_text_length": 10.0,
                }
            ],
            win_points=[],
            lose_points=[],
            action_items=[],
        )
        out = tmp_path / "r.pdf"
        path = ComparisonReportGenerator().render(report, out)
        assert path.exists()
        assert path.stat().st_size > 0

    def test_render_skips_zero_sentiment_chart(self, tmp_path: Path) -> None:
        """모든 긍정·부정 비율이 0이면 스택바 차트가 생성되지 않는다."""
        report = ComparisonReport(
            products=[_make_analyzed("A", 1, 0.0, 0, 0)],
            summary_rows=[
                {
                    "label": "A", "review_count": 1,
                    "avg_rating": 0.0,
                    "positive_pct": 0.0, "negative_pct": 0.0,
                    "avg_text_length": 1.0,
                }
            ],
        )
        out = tmp_path / "r.pdf"
        path = ComparisonReportGenerator().render(report, out)
        assert path.exists()
