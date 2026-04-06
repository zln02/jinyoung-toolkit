"""AutoMLReportBuilder 단위 테스트."""
import pytest
from pathlib import Path

from automl_reporter.runner import AutoMLResult, ModelResult, TaskType
from automl_reporter.report_builder import AutoMLReportBuilder


@pytest.fixture
def sample_result() -> AutoMLResult:
    return AutoMLResult(
        task_type=TaskType.BINARY_CLASSIFICATION,
        model_results=[
            ModelResult(
                name="RandomForest",
                metrics={"accuracy": 0.85, "f1": 0.83},
                is_tuned=False,
                training_time_seconds=1.2,
            ),
            ModelResult(
                name="LogisticRegression",
                metrics={"accuracy": 0.82, "f1": 0.80},
                is_tuned=False,
                training_time_seconds=0.5,
            ),
        ],
        best_model_name="RandomForest",
        best_metrics={"accuracy": 0.85, "f1": 0.83},
        feature_importance={
            "feature_1": 0.3,
            "feature_2": 0.25,
            "feature_3": 0.15,
        },
        data_summary={
            "rows": 100,
            "columns": 10,
            "dtypes": {
                "feature_1": "float64",
                "feature_2": "float64",
                "target": "int64",
            },
            "missing_pct": {
                "feature_1": 0.0,
                "feature_2": 0.0,
                "target": 0.0,
            },
            "target_distribution": {"0": 0.5, "1": 0.5},
        },
    )


class TestReportBuilder:
    def test_build_pdf_creates_file(
        self, sample_result: AutoMLResult, tmp_path: Path
    ) -> None:
        """build() 호출 후 PDF 파일이 생성되어야 한다."""
        output = tmp_path / "report.pdf"
        builder = AutoMLReportBuilder(sample_result)
        saved = builder.build(output)

        assert saved.exists(), "PDF 파일이 생성되어야 함"

    def test_build_pdf_contains_sections(
        self, sample_result: AutoMLResult, tmp_path: Path
    ) -> None:
        """생성된 PDF가 유효한 파일이어야 한다 (크기 > 0, PDF 헤더 확인)."""
        output = tmp_path / "report_valid.pdf"
        builder = AutoMLReportBuilder(sample_result)
        saved = builder.build(output)

        assert saved.stat().st_size > 0, "PDF 파일 크기가 0보다 커야 함"

        # PDF 파일 매직 바이트 확인
        with open(saved, "rb") as f:
            header = f.read(4)
        assert header == b"%PDF", (
            f"PDF 파일은 '%PDF' 헤더로 시작해야 하지만 {header!r} 확인됨"
        )

    def test_recommendations_count(self, sample_result: AutoMLResult) -> None:
        """_generate_recommendations()가 정확히 3개 항목을 반환해야 한다."""
        builder = AutoMLReportBuilder(sample_result)
        recs = builder._generate_recommendations()

        assert isinstance(recs, list), "_generate_recommendations()는 list를 반환해야 함"
        assert len(recs) == 3, (
            f"추천 항목은 정확히 3개여야 하지만 {len(recs)}개 반환됨"
        )
        for rec in recs:
            assert isinstance(rec, str) and rec, "각 추천 항목은 비어 있지 않은 문자열이어야 함"
