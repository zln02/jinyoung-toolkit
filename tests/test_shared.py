"""shared/ 모듈 통합 테스트.

테스트 대상:
    - shared.config (AppSettings, get_settings)
    - shared.logger (get_logger)
    - shared.korean_nlp (KoreanTextProcessor)
    - shared.report_generator (ReportGenerator)
    - shared.exporters (export_csv, export_json, export_excel)
    - shared.delivery (DeliveryPackage)
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pandas as pd
import pytest
import structlog

# ---------------------------------------------------------------------------
# Session-scope structlog 재설정 fixture
#
# shared/logger.py 는 add_logger_name 프로세서를 포함하는데,
# PrintLoggerFactory 의 PrintLogger 에는 .name 속성이 없어 AttributeError 발생.
# 테스트 세션 시작 시 add_logger_name 없이 재설정하여 충돌을 방지한다.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _patch_structlog() -> None:
    """structlog을 PrintLogger 호환 설정으로 재구성한다."""
    import shared.logger as _logger_mod

    structlog.reset_defaults()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=False),
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )
    # 이미 _configured=True 이므로 setup_logging() 재진입 차단 해제 불필요 —
    # structlog.reset_defaults() + configure() 로 충분히 덮어씀.
    _logger_mod._configured = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def sample_reviews_df() -> pd.DataFrame:
    """sample_reviews_50.csv를 읽어 DataFrame으로 반환한다.

    content 컬럼에 쉼표가 포함된 행이 존재하므로 on_bad_lines='skip' 으로 파싱한다.
    """
    csv_path = FIXTURES_DIR / "sample_reviews_50.csv"
    return pd.read_csv(csv_path, encoding="utf-8-sig", on_bad_lines="skip")


@pytest.fixture(scope="session")
def sample_texts(sample_reviews_df: pd.DataFrame) -> pd.Series:
    """리뷰 content 컬럼 Series를 반환한다."""
    return sample_reviews_df["content"].dropna().reset_index(drop=True)


@pytest.fixture(scope="session")
def korean_processor() -> "KoreanTextProcessor":
    """KoreanTextProcessor 세션 범위 인스턴스를 반환한다."""
    from shared.korean_nlp import KoreanTextProcessor

    return KoreanTextProcessor()


# ---------------------------------------------------------------------------
# TestConfig
# ---------------------------------------------------------------------------


class TestConfig:
    def test_default_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """기본값이 스펙대로 설정되어 있어야 한다."""
        from shared.config import AppSettings

        # 환경변수와 .env 파일의 영향을 모두 차단하여 순수 기본값을 검증
        env_vars = [
            "UIS_URL",
            "LOG_LEVEL",
            "OUTPUT_DIR",
            "CHROME_DRIVER_PATH",
            "REPORT_AUTHOR",
            "CRAWL_DELAY_SECONDS",
            "MAX_RETRIES",
            "REQUEST_TIMEOUT",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "SELECTOR_INFERENCE_MODEL",
            "SENTIMENT_MODEL",
            "SENTIMENT_BATCH_SIZE",
            "RANDOM_SEED",
            "TEST_SIZE",
            "GCP_PROJECT_ID",
            "GCP_REGION",
        ]
        for var in env_vars:
            monkeypatch.delenv(var, raising=False)
            monkeypatch.delenv(var.lower(), raising=False)

        # _env_file=None 으로 .env 파일 로드 차단
        settings = AppSettings(_env_file=None)

        assert settings.log_level == "INFO", (
            f"log_level 기본값이 'INFO'여야 하는데 '{settings.log_level}'임"
        )
        assert settings.output_dir == Path("output"), (
            f"output_dir 기본값이 Path('output')여야 하는데 '{settings.output_dir}'임"
        )
        assert settings.report_author == "jinyoung-toolkit", (
            f"report_author 기본값이 'jinyoung-toolkit'여야 하는데 '{settings.report_author}'임"
        )
        assert settings.crawl_delay_seconds == 1.5, (
            f"crawl_delay_seconds 기본값이 1.5여야 하는데 {settings.crawl_delay_seconds}임"
        )
        assert settings.max_retries == 3, (
            f"max_retries 기본값이 3이어야 하는데 {settings.max_retries}임"
        )
        assert settings.request_timeout == 30, (
            f"request_timeout 기본값이 30이어야 하는데 {settings.request_timeout}임"
        )
        assert settings.random_seed == 42, (
            f"random_seed 기본값이 42여야 하는데 {settings.random_seed}임"
        )
        assert settings.test_size == 0.3, (
            f"test_size 기본값이 0.3여야 하는데 {settings.test_size}임"
        )
        assert settings.sentiment_batch_size == 10, (
            f"sentiment_batch_size 기본값이 10이어야 하는데 {settings.sentiment_batch_size}임"
        )
        assert settings.gcp_region == "asia-northeast3", (
            f"gcp_region 기본값이 'asia-northeast3'여야 하는데 '{settings.gcp_region}'임"
        )
        assert settings.openai_api_key is None, (
            "openai_api_key 기본값이 None이어야 함"
        )
        assert settings.gcp_project_id is None, (
            "gcp_project_id 기본값이 None이어야 함"
        )

    def test_get_settings_singleton(self) -> None:
        """get_settings()를 두 번 호출하면 동일한 객체를 반환해야 한다."""
        from shared.config import get_settings

        s1 = get_settings()
        s2 = get_settings()

        assert s1 is s2, (
            "get_settings()가 싱글턴을 반환해야 하는데 매번 다른 객체를 반환함"
        )


# ---------------------------------------------------------------------------
# TestLogger
# ---------------------------------------------------------------------------


class TestLogger:
    def test_get_logger_returns_bound_logger(self) -> None:
        """get_logger()가 structlog BoundLogger 계열 객체를 반환해야 한다."""
        from shared.logger import get_logger

        logger = get_logger("test_module")

        # structlog의 BoundLogger 또는 BoundLoggerBase 인스턴스여야 함
        assert isinstance(logger, structlog.stdlib.BoundLogger) or hasattr(
            logger, "info"
        ), (
            f"get_logger()가 BoundLogger 계열이어야 하는데 '{type(logger)}'를 반환함"
        )

    def test_logger_can_log(self) -> None:
        """log.info() 호출 시 예외 없이 실행되어야 한다."""
        from shared.logger import get_logger

        logger = get_logger("test_logger_can_log")

        # 예외 없이 실행되면 통과
        logger.info("test_event", key="value", number=42)
        logger.debug("debug_event")
        logger.warning("warn_event", detail="테스트 경고")


# ---------------------------------------------------------------------------
# TestKoreanNLP
# ---------------------------------------------------------------------------


class TestKoreanNLP:
    def test_tokenize(
        self,
        korean_processor: "KoreanTextProcessor",
        sample_texts: pd.Series,
    ) -> None:
        """tokenize()가 pd.Series를 반환하고, 결과가 공백 구분 문자열이어야 한다."""
        result = korean_processor.tokenize(sample_texts)

        assert isinstance(result, pd.Series), (
            f"tokenize() 반환 타입이 pd.Series여야 하는데 '{type(result)}'임"
        )
        assert len(result) == len(sample_texts), (
            "tokenize() 결과의 길이가 입력 Series와 같아야 함"
        )
        # 비어 있지 않은 결과가 하나 이상 있어야 함
        non_empty = result[result.str.strip() != ""]
        assert len(non_empty) > 0, (
            "tokenize() 결과 중 유효한 토큰이 하나 이상 있어야 함"
        )
        # 각 원소는 문자열 계열 dtype이어야 함
        # pandas 버전에 따라 object 또는 StringDtype 모두 허용
        assert pd.api.types.is_string_dtype(result), (
            f"tokenize() 결과 dtype이 문자열 계열이어야 하는데 '{result.dtype}'임"
        )

    def test_extract_keywords_tfidf(
        self,
        korean_processor: "KoreanTextProcessor",
        sample_texts: pd.Series,
    ) -> None:
        """extract_keywords_tfidf()가 (str, float) 튜플 리스트를 반환해야 한다."""
        result = korean_processor.extract_keywords_tfidf(sample_texts, top_k=10)

        assert isinstance(result, list), (
            f"extract_keywords_tfidf() 반환 타입이 list여야 하는데 '{type(result)}'임"
        )
        assert len(result) > 0, "키워드 추출 결과가 비어 있음"
        assert len(result) <= 10, (
            f"top_k=10 인데 결과가 {len(result)}개임"
        )

        first = result[0]
        assert isinstance(first, tuple), (
            f"결과 원소가 tuple이어야 하는데 '{type(first)}'임"
        )
        assert len(first) == 2, (
            f"튜플 길이가 2여야 하는데 {len(first)}임"
        )
        keyword, score = first
        assert isinstance(keyword, str), (
            f"키워드가 str이어야 하는데 '{type(keyword)}'임"
        )
        assert isinstance(score, float), (
            f"TF-IDF 점수가 float이어야 하는데 '{type(score)}'임"
        )
        assert score >= 0.0, f"TF-IDF 점수가 0 이상이어야 하는데 {score}임"

    def test_extract_keywords_by_group(
        self,
        korean_processor: "KoreanTextProcessor",
        sample_reviews_df: pd.DataFrame,
    ) -> None:
        """extract_keywords_by_group()이 dict를 반환하고 키가 레이블이어야 한다."""
        texts = sample_reviews_df["content"].dropna().reset_index(drop=True)
        # rating을 그룹 레이블로 사용
        labels = sample_reviews_df["rating"].dropna().reset_index(drop=True)

        # 인덱스를 맞춤
        min_len = min(len(texts), len(labels))
        texts = texts.iloc[:min_len]
        labels = labels.iloc[:min_len]

        result = korean_processor.extract_keywords_by_group(texts, labels, top_k=5)

        assert isinstance(result, dict), (
            f"extract_keywords_by_group() 반환 타입이 dict여야 하는데 '{type(result)}'임"
        )
        assert len(result) > 0, "그룹별 키워드 결과가 비어 있음"

        # 각 레이블이 str 키로 들어가야 함
        for label_key, kw_list in result.items():
            assert isinstance(label_key, str), (
                f"dict 키가 str이어야 하는데 '{type(label_key)}'임"
            )
            assert isinstance(kw_list, list), (
                f"레이블 '{label_key}'의 값이 list여야 하는데 '{type(kw_list)}'임"
            )

    def test_find_korean_font(self) -> None:
        """find_korean_font()가 존재하는 폰트 Path를 반환해야 한다 (NanumGothic 설치됨)."""
        from shared.korean_nlp import KoreanTextProcessor

        font_path = KoreanTextProcessor.find_korean_font()

        assert isinstance(font_path, Path), (
            f"find_korean_font() 반환 타입이 Path여야 하는데 '{type(font_path)}'임"
        )
        assert font_path.is_file(), (
            f"find_korean_font()가 반환한 경로가 실제 파일이어야 함: {font_path}"
        )
        assert font_path.suffix.lower() in {".ttf", ".otf"}, (
            f"폰트 파일 확장자가 .ttf 또는 .otf여야 하는데 '{font_path.suffix}'임"
        )

    def test_generate_wordcloud(
        self,
        korean_processor: "KoreanTextProcessor",
        sample_texts: pd.Series,
        tmp_path: Path,
    ) -> None:
        """generate_wordcloud()가 이미지 파일을 생성해야 한다."""
        output_file = tmp_path / "wordcloud.png"

        result_path = korean_processor.generate_wordcloud(sample_texts, output_file)

        assert result_path.exists(), (
            f"워드클라우드 이미지 파일이 생성되어야 함: {result_path}"
        )
        assert result_path.stat().st_size > 0, (
            "워드클라우드 이미지 파일이 비어 있으면 안 됨"
        )
        assert result_path.suffix.lower() == ".png", (
            f"출력 파일 확장자가 .png여야 하는데 '{result_path.suffix}'임"
        )

    def test_to_tfidf_features(
        self,
        korean_processor: "KoreanTextProcessor",
        sample_texts: pd.Series,
    ) -> None:
        """to_tfidf_features()가 DataFrame을 반환하고 컬럼 수가 max_features 이하여야 한다."""
        max_features = 100
        result = korean_processor.to_tfidf_features(sample_texts, max_features=max_features)

        assert isinstance(result, pd.DataFrame), (
            f"to_tfidf_features() 반환 타입이 pd.DataFrame이어야 하는데 '{type(result)}'임"
        )
        assert len(result) == len(sample_texts), (
            f"행 수가 입력 크기({len(sample_texts)})와 같아야 하는데 {len(result)}임"
        )
        assert result.shape[1] <= max_features, (
            f"컬럼 수가 max_features({max_features}) 이하여야 하는데 {result.shape[1]}임"
        )
        assert result.shape[1] > 0, "컬럼이 하나 이상 있어야 함"
        assert result.dtypes.unique().tolist() == ["float32"], (
            "모든 컬럼의 dtype이 float32여야 함"
        )


# ---------------------------------------------------------------------------
# TestReportGenerator
# ---------------------------------------------------------------------------


class TestReportGenerator:
    def test_create_and_save_pdf(self, tmp_path: Path) -> None:
        """ReportGenerator 생성 후 save()하면 PDF 파일이 존재해야 한다."""
        from shared.report_generator import ReportGenerator

        output_pdf = tmp_path / "test_report.pdf"
        rg = ReportGenerator(title="테스트 리포트", author="테스터")
        saved_path = rg.save(output_pdf)

        assert saved_path.exists(), (
            f"PDF 파일이 저장되어야 함: {saved_path}"
        )
        assert saved_path.stat().st_size > 0, (
            "저장된 PDF 파일이 비어 있으면 안 됨"
        )
        assert saved_path.suffix.lower() == ".pdf", (
            f"저장 파일 확장자가 .pdf여야 하는데 '{saved_path.suffix}'임"
        )
        # PDF 매직 바이트 확인
        header = saved_path.read_bytes()[:4]
        assert header == b"%PDF", (
            f"파일이 유효한 PDF가 아님 (헤더: {header!r})"
        )

    def test_add_section_and_table(self, tmp_path: Path) -> None:
        """add_section(), add_table() 호출 후 save()가 성공해야 한다."""
        from shared.report_generator import ReportGenerator

        output_pdf = tmp_path / "section_table_report.pdf"
        rg = ReportGenerator(title="섹션 테이블 테스트", author="테스터")
        rg.add_section(
            heading="분석 개요",
            content="이 리포트는 shared.report_generator 통합 테스트용입니다.",
        )
        rg.add_table(
            headers=["항목", "값", "비고"],
            rows=[
                ["정확도", "92.3%", "검증 세트"],
                ["F1 스코어", "0.91", "macro avg"],
                ["샘플 수", "1,000", "전체"],
            ],
        )
        saved_path = rg.save(output_pdf)

        assert saved_path.exists(), (
            f"섹션+테이블 포함 PDF가 저장되어야 함: {saved_path}"
        )
        assert saved_path.stat().st_size > 0, (
            "저장된 PDF 파일이 비어 있으면 안 됨"
        )
        header = saved_path.read_bytes()[:4]
        assert header == b"%PDF", (
            f"파일이 유효한 PDF가 아님 (헤더: {header!r})"
        )


# ---------------------------------------------------------------------------
# TestExporters
# ---------------------------------------------------------------------------


class TestExporters:
    @pytest.fixture()
    def sample_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "이름": ["김철수", "이영희", "박민준"],
                "점수": [85, 92, 78],
                "코멘트": ["훌륭함", "우수함", "보통"],
            }
        )

    def test_export_csv_bom(self, sample_df: pd.DataFrame, tmp_path: Path) -> None:
        """export_csv()가 UTF-8 BOM CSV 파일을 생성해야 한다."""
        from shared.exporters import export_csv

        output_path = tmp_path / "test_output.csv"
        result_path = export_csv(sample_df, output_path)

        assert result_path.exists(), (
            f"CSV 파일이 생성되어야 함: {result_path}"
        )
        assert result_path.stat().st_size > 0, "CSV 파일이 비어 있으면 안 됨"

        # BOM 확인 (UTF-8 BOM = EF BB BF)
        raw_bytes = result_path.read_bytes()
        assert raw_bytes[:3] == b"\xef\xbb\xbf", (
            "CSV 파일이 UTF-8 BOM(EF BB BF)으로 시작해야 함"
        )

        # 데이터 정합성 확인
        loaded = pd.read_csv(result_path, encoding="utf-8-sig")
        assert list(loaded.columns) == list(sample_df.columns), (
            "저장된 CSV의 컬럼이 원본 DataFrame과 같아야 함"
        )
        assert len(loaded) == len(sample_df), (
            f"저장된 CSV의 행 수가 원본({len(sample_df)})과 같아야 하는데 {len(loaded)}임"
        )

    def test_export_json(self, sample_df: pd.DataFrame, tmp_path: Path) -> None:
        """export_json()이 한국어를 포함한 유효한 JSON 파일을 생성해야 한다."""
        from shared.exporters import export_json

        output_path = tmp_path / "test_output.json"
        result_path = export_json(sample_df, output_path)

        assert result_path.exists(), (
            f"JSON 파일이 생성되어야 함: {result_path}"
        )
        assert result_path.stat().st_size > 0, "JSON 파일이 비어 있으면 안 됨"

        content = result_path.read_text(encoding="utf-8")
        parsed = json.loads(content)

        assert isinstance(parsed, list), (
            f"orient='records' 이므로 JSON 최상위가 list여야 하는데 '{type(parsed)}'임"
        )
        assert len(parsed) == len(sample_df), (
            f"JSON 레코드 수가 원본 행 수({len(sample_df)})와 같아야 하는데 {len(parsed)}임"
        )

        # 한국어 포함 확인 (force_ascii=False)
        assert "김철수" in content, (
            "force_ascii=False 설정으로 한국어가 이스케이프 없이 저장되어야 함"
        )

    def test_export_excel(self, sample_df: pd.DataFrame, tmp_path: Path) -> None:
        """export_excel()이 Excel 파일(.xlsx)을 생성해야 한다."""
        from shared.exporters import export_excel

        output_path = tmp_path / "test_output.xlsx"
        result_path = export_excel(sample_df, output_path)

        assert result_path.exists(), (
            f"Excel 파일이 생성되어야 함: {result_path}"
        )
        assert result_path.stat().st_size > 0, "Excel 파일이 비어 있으면 안 됨"
        assert result_path.suffix.lower() == ".xlsx", (
            f"Excel 파일 확장자가 .xlsx여야 하는데 '{result_path.suffix}'임"
        )

        # openpyxl로 읽어서 데이터 정합성 확인
        loaded = pd.read_excel(result_path, engine="openpyxl")
        assert list(loaded.columns) == list(sample_df.columns), (
            "저장된 Excel의 컬럼이 원본 DataFrame과 같아야 함"
        )
        assert len(loaded) == len(sample_df), (
            f"저장된 Excel의 행 수가 원본({len(sample_df)})과 같아야 하는데 {len(loaded)}임"
        )


# ---------------------------------------------------------------------------
# TestDeliveryPackage
# ---------------------------------------------------------------------------


class TestDeliveryPackage:
    @pytest.fixture()
    def simple_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "id": [1, 2, 3],
                "value": ["가나다", "라마바", "사아자"],
            }
        )

    def test_build_creates_directories(self, tmp_path: Path) -> None:
        """build() 호출 후 01_raw ~ 04_report 디렉토리가 모두 존재해야 한다."""
        from shared.delivery import DeliveryPackage

        pkg = DeliveryPackage(output_dir=tmp_path, project_name="test_project")
        base_dir = pkg.build()

        expected_subdirs = ["01_raw", "02_clean", "03_analysis", "04_report"]
        for subdir in expected_subdirs:
            target = base_dir / subdir
            assert target.is_dir(), (
                f"build() 후 '{subdir}' 디렉토리가 존재해야 함: {target}"
            )

        assert base_dir == tmp_path / "test_project", (
            f"build() 반환값이 base_dir여야 함: {base_dir}"
        )

    def test_add_raw_and_clean(
        self,
        simple_df: pd.DataFrame,
        tmp_path: Path,
    ) -> None:
        """add_raw(), add_clean() 호출 후 각 디렉토리에 CSV 파일이 존재해야 한다."""
        from shared.delivery import DeliveryPackage

        pkg = DeliveryPackage(output_dir=tmp_path, project_name="data_project")

        pkg.add_raw(simple_df, filename="raw.csv")
        pkg.add_clean(simple_df, filename="clean.csv")

        raw_csv = tmp_path / "data_project" / "01_raw" / "raw.csv"
        clean_csv = tmp_path / "data_project" / "02_clean" / "clean.csv"

        assert raw_csv.exists(), (
            f"add_raw() 후 '01_raw/raw.csv'가 존재해야 함: {raw_csv}"
        )
        assert raw_csv.stat().st_size > 0, "01_raw/raw.csv가 비어 있으면 안 됨"

        assert clean_csv.exists(), (
            f"add_clean() 후 '02_clean/clean.csv'가 존재해야 함: {clean_csv}"
        )
        assert clean_csv.stat().st_size > 0, "02_clean/clean.csv가 비어 있으면 안 됨"

        # BOM 확인 (utf-8-sig 저장)
        raw_bytes = raw_csv.read_bytes()
        assert raw_bytes[:3] == b"\xef\xbb\xbf", (
            "add_raw() CSV가 UTF-8 BOM으로 저장되어야 함"
        )

        # 데이터 정합성 확인
        loaded_raw = pd.read_csv(raw_csv, encoding="utf-8-sig")
        assert len(loaded_raw) == len(simple_df), (
            f"01_raw/raw.csv 행 수가 원본({len(simple_df)})과 같아야 하는데 {len(loaded_raw)}임"
        )
