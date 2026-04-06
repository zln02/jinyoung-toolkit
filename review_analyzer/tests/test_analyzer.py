"""ReviewAnalyzer 테스트."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from review_analyzer.analyzer import AnalysisResult, ReviewAnalyzer

_FIXTURE_PATH = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "sample_reviews_50.csv"


class TestReviewAnalyzer:

    @pytest.fixture
    def sample_df(self) -> pd.DataFrame:
        """tests/fixtures/sample_reviews_50.csv 로드."""
        return pd.read_csv(_FIXTURE_PATH)

    @pytest.fixture
    def analyzer(self) -> ReviewAnalyzer:
        return ReviewAnalyzer(text_column="content", rating_column="rating")

    # ------------------------------------------------------------------

    def test_preprocess_removes_duplicates(
        self, analyzer: ReviewAnalyzer, sample_df: pd.DataFrame
    ) -> None:
        """중복 행이 제거되는지 확인."""
        # 의도적으로 첫 행을 복제해 중복 추가
        df_with_dup = pd.concat([sample_df, sample_df.iloc[[0]]], ignore_index=True)
        original_len = len(df_with_dup)

        result = analyzer.preprocess(df_with_dup)

        assert len(result) < original_len
        assert result.duplicated().sum() == 0

    def test_sentiment_by_rating(
        self, analyzer: ReviewAnalyzer, sample_df: pd.DataFrame
    ) -> None:
        """평점 기반 감성 분석: 4-5=positive, 3=neutral, 1-2=negative."""
        df = analyzer.preprocess(sample_df)
        df = analyzer.analyze_sentiment(df)

        assert "sentiment" in df.columns

        positive_rows = df[df["rating"].isin([4, 5])]
        assert (positive_rows["sentiment"] == "positive").all()

        neutral_rows = df[df["rating"] == 3]
        assert (neutral_rows["sentiment"] == "neutral").all()

        negative_rows = df[df["rating"].isin([1, 2])]
        assert (negative_rows["sentiment"] == "negative").all()

    def test_sentiment_by_keywords(self, analyzer: ReviewAnalyzer) -> None:
        """평점 없는 경우 키워드 기반 감성 분석."""
        df = pd.DataFrame(
            {
                "content": [
                    "정말 최고예요! 가성비도 훌륭하고 배송도 빠르고 만족해요.",
                    "환불하고 싶어요. 불량품이고 최악이에요.",
                    "그냥 그래요. 특별한 점이 없어요.",
                ]
            }
        )
        kw_analyzer = ReviewAnalyzer(text_column="content", rating_column=None)
        result = kw_analyzer.analyze_sentiment(df)

        assert result["sentiment"].iloc[0] == "positive"
        assert result["sentiment"].iloc[1] == "negative"

    def test_keyword_extraction_top_k(
        self, analyzer: ReviewAnalyzer, sample_df: pd.DataFrame
    ) -> None:
        """추출된 키워드 수가 top_k 이하인지 확인."""
        df = analyzer.preprocess(sample_df)
        df = analyzer.analyze_sentiment(df)
        top_k = 10

        keywords = analyzer.extract_keywords(df, top_k=top_k)

        assert "positive" in keywords
        assert "negative" in keywords
        assert len(keywords["positive"]) <= top_k
        assert len(keywords["negative"]) <= top_k
        # 각 항목이 (str, float) 튜플인지 확인
        for kw, score in keywords.get("positive", []):
            assert isinstance(kw, str)
            assert isinstance(score, float)

    def test_wordcloud_generates_png(
        self, analyzer: ReviewAnalyzer, sample_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """워드클라우드 PNG 파일이 생성되는지 확인."""
        df = analyzer.preprocess(sample_df)
        df = analyzer.analyze_sentiment(df)

        paths = analyzer.generate_wordcloud(df, output_dir=tmp_path)

        # "all" 그룹 워드클라우드는 반드시 생성되어야 함
        assert "all" in paths
        assert paths["all"].exists()
        assert paths["all"].suffix == ".png"

    def test_insights_generates_3_lines(
        self, analyzer: ReviewAnalyzer, sample_df: pd.DataFrame
    ) -> None:
        """인사이트가 정확히 3줄 생성되는지 확인."""
        result = analyzer.run(sample_df)

        assert len(result.insights) == 3
        for insight in result.insights:
            assert isinstance(insight, str)
            assert len(insight) > 0

    def test_pdf_report_generated(
        self, analyzer: ReviewAnalyzer, sample_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """PDF 리포트 파일이 생성되는지 확인."""
        result = analyzer.run(sample_df)
        output_path = tmp_path / "report.pdf"

        saved_path = analyzer.generate_report(result, output_path)

        assert saved_path.exists()
        assert saved_path.suffix == ".pdf"
        assert saved_path.stat().st_size > 0

    def test_delivery_package_structure(
        self, analyzer: ReviewAnalyzer, sample_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """납품 패키지가 올바른 구조로 생성되는지 확인."""
        result = analyzer.run(sample_df)

        built_path = analyzer.save_delivery_package(
            raw_df=sample_df,
            result=result,
            output_dir=tmp_path,
            project_name="test_project",
        )

        assert built_path.exists()
        # zip 또는 디렉토리 형태로 반환됨
        assert built_path.is_file() or built_path.is_dir()

    def test_handles_empty_reviews(self, analyzer: ReviewAnalyzer) -> None:
        """빈 DataFrame 입력 시 예외 없이 처리되는지 확인."""
        df = pd.DataFrame(columns=["content", "rating"])

        result = analyzer.run(df)

        assert isinstance(result, AnalysisResult)
        assert result.total_reviews == 0
        assert result.avg_rating == 0.0

    def test_handles_no_rating_column(self) -> None:
        """rating_column=None인 경우 키워드 기반으로 감성 분석."""
        df = pd.DataFrame(
            {
                "content": [
                    "정말 만족스러워요. 추천합니다.",
                    "실망이에요. 불량이고 환불하고 싶어요.",
                    "그냥 평범해요.",
                ]
            }
        )
        analyzer = ReviewAnalyzer(text_column="content", rating_column=None)

        df_result = analyzer.analyze_sentiment(df)

        assert "sentiment" in df_result.columns
        assert set(df_result["sentiment"]).issubset({"positive", "negative", "neutral"})
        # rating 컬럼이 없어도 오류 없이 동작해야 함
        assert "rating" not in df_result.columns
