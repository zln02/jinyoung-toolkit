"""ReviewAnalyzer 테스트."""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from review_analyzer.analyzer import AnalysisResult, ReviewAnalyzer
from review_analyzer.app import _build_zip

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


class TestRatingParsing:
    """평점 파싱 (regex 기반) 테스트."""

    def test_parse_rating_text_100pct(self) -> None:
        """11번가 '만족도 : 100%' → 5.0 (100점 → 5점 자동 변환)."""
        analyzer = ReviewAnalyzer(rating_parse_pattern=r"(\d+)")
        assert analyzer._parse_rating_value("만족도 : 100%") == 5.0
        assert analyzer._parse_rating_value("만족도 : 80%") == 4.0
        assert analyzer._parse_rating_value("만족도 : 40%") == 2.0

    def test_parse_rating_text_amazon(self) -> None:
        """Amazon '4.0 out of 5 stars' → 4.0."""
        analyzer = ReviewAnalyzer(rating_parse_pattern=r"([0-9.]+)")
        assert analyzer._parse_rating_value("4.0 out of 5 stars") == 4.0
        assert analyzer._parse_rating_value("3.5 out of 5 stars") == 3.5

    def test_parse_rating_missing_pattern(self) -> None:
        """패턴 없을 때 기존 동작 유지 — 숫자 그대로, 텍스트는 None."""
        analyzer = ReviewAnalyzer(rating_parse_pattern=None)
        assert analyzer._parse_rating_value(4) == 4.0
        assert analyzer._parse_rating_value(3.5) == 3.5
        assert analyzer._parse_rating_value("4") == 4.0
        assert analyzer._parse_rating_value("abc") is None
        assert analyzer._parse_rating_value(None) is None

    def test_sentiment_with_text_rating(self) -> None:
        """텍스트 평점으로 positive/negative/neutral 분류."""
        analyzer = ReviewAnalyzer(rating_parse_pattern=r"(\d+)")
        # 100% → 5.0 (positive)
        assert analyzer._sentiment_by_rating("만족도 : 100%") == "positive"
        # 40% → 2.0 (negative)
        assert analyzer._sentiment_by_rating("만족도 : 40%") == "negative"
        # 60% → 3.0 (neutral)
        assert analyzer._sentiment_by_rating("만족도 : 60%") == "neutral"
        # None → neutral
        assert analyzer._sentiment_by_rating(None) == "neutral"


class TestBuildZip:
    """_build_zip 단위 테스트."""

    @pytest.fixture
    def sample_df(self) -> pd.DataFrame:
        return pd.read_csv(_FIXTURE_PATH)

    @pytest.fixture
    def analysis_result(self, sample_df: pd.DataFrame) -> AnalysisResult:
        analyzer = ReviewAnalyzer(text_column="content", rating_column="rating")
        return analyzer.run(sample_df)

    def test_build_zip_returns_valid_zip(
        self, sample_df: pd.DataFrame, analysis_result: AnalysisResult
    ) -> None:
        """정상 경로에서 유효한 ZIP 반환 확인."""
        zip_bytes, is_fallback = _build_zip(sample_df, analysis_result, "test_pkg")

        assert isinstance(zip_bytes, bytes)
        assert len(zip_bytes) > 0
        assert not is_fallback

        import io

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            assert zf.testzip() is None  # 손상 없음

    def test_build_zip_fallback_on_package_failure(
        self, sample_df: pd.DataFrame, analysis_result: AnalysisResult
    ) -> None:
        """save_delivery_package 실패 시 폴백 ZIP에 raw.csv 포함 확인."""
        with patch.object(
            ReviewAnalyzer,
            "save_delivery_package",
            side_effect=RuntimeError("패키지 생성 실패"),
        ):
            zip_bytes, is_fallback = _build_zip(
                sample_df, analysis_result, "test_fallback"
            )

        assert is_fallback is True
        assert len(zip_bytes) > 0

        import io

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            assert "raw.csv" in zf.namelist()

    def test_build_zip_korean_csv_encoding(
        self, analysis_result: AnalysisResult
    ) -> None:
        """한글 데이터 포함 시 UTF-8 BOM 인코딩 확인."""
        korean_df = pd.DataFrame(
            {"content": ["좋아요", "별로예요", "그냥 그래요"], "rating": [5, 1, 3]}
        )

        with patch.object(
            ReviewAnalyzer,
            "save_delivery_package",
            side_effect=RuntimeError("강제 폴백"),
        ):
            zip_bytes, is_fallback = _build_zip(
                korean_df, analysis_result, "korean_test"
            )

        assert is_fallback is True

        import io

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            csv_bytes = zf.read("raw.csv")

        # UTF-8 BOM 확인
        assert csv_bytes.startswith(b"\xef\xbb\xbf")
        # 한글 정상 디코딩 확인
        decoded = csv_bytes.decode("utf-8-sig")
        assert "좋아요" in decoded
        assert "별로예요" in decoded
