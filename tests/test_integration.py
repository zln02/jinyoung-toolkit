"""E2E 통합 테스트 — AutoML 파이프라인 전체 흐름."""

from __future__ import annotations

import numpy as np
import pytest
import pandas as pd
from pathlib import Path

import automl_reporter.runner as runner_module
from automl_reporter.runner import AutoMLConfig, AutoMLRunner, AutoMLResult, TaskType
from automl_reporter.report_builder import AutoMLReportBuilder
from shared.delivery import DeliveryPackage

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_tabular.csv"


@pytest.fixture(autouse=True)
def _disable_pycaret(monkeypatch):
    monkeypatch.setattr(runner_module, "_pycaret_available", False)


@pytest.fixture
def sample_df():
    return pd.read_csv(FIXTURE_PATH, encoding="utf-8-sig")


# ---------------------------------------------------------------------------
# Test 1: 분류 E2E 파이프라인
# ---------------------------------------------------------------------------


def test_e2e_classification_pipeline(sample_df, tmp_path):
    """CSV 저장 → AutoMLRunner.run() → PDF 리포트 → pkl 모델 저장까지 전체 흐름 검증."""
    # CSV 저장
    csv_path = tmp_path / "input.csv"
    sample_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    # AutoMLConfig 구성 및 실행
    config = AutoMLConfig(
        input_path=csv_path,
        target_column="target",
        output_dir=tmp_path / "output",
    )
    runner = AutoMLRunner(config)
    result = runner.run()

    # AutoMLResult 필드 검증
    assert isinstance(result, AutoMLResult)
    assert result.task_type in (
        TaskType.BINARY_CLASSIFICATION,
        TaskType.MULTICLASS_CLASSIFICATION,
    )
    assert isinstance(result.model_results, list)
    assert len(result.model_results) > 0
    assert isinstance(result.best_model_name, str)
    assert len(result.best_model_name) > 0
    assert isinstance(result.best_metrics, dict)
    assert isinstance(result.data_summary, dict)
    assert result.data_summary["rows"] == len(sample_df)

    # PDF 리포트 생성
    pdf_path = tmp_path / "report.pdf"
    saved_pdf = AutoMLReportBuilder(result).build(pdf_path)
    assert saved_pdf.exists(), f"PDF 파일이 생성되지 않음: {saved_pdf}"
    assert saved_pdf.suffix == ".pdf"

    # 모델 저장 (.pkl)
    model_path = tmp_path / "best_model.pkl"
    saved_model = runner.save_best_model(model_path)
    assert saved_model.exists(), f"모델 파일이 생성되지 않음: {saved_model}"
    assert saved_model.suffix == ".pkl"


# ---------------------------------------------------------------------------
# Test 2: 클러스터링 E2E 파이프라인
# ---------------------------------------------------------------------------


def test_e2e_clustering_pipeline(sample_df, tmp_path):
    """target 컬럼 제거 후 비지도 클러스터링 자동 감지 검증."""
    # target 컬럼 제거
    df_no_target = sample_df.drop(columns=["target"])
    csv_path = tmp_path / "input_no_target.csv"
    df_no_target.to_csv(csv_path, index=False, encoding="utf-8-sig")

    # target_column 미지정 → CLUSTERING 자동 감지
    config = AutoMLConfig(
        input_path=csv_path,
        target_column=None,
        output_dir=tmp_path / "output_clustering",
    )
    runner = AutoMLRunner(config)
    result = runner.run()

    assert isinstance(result, AutoMLResult)
    assert result.task_type == TaskType.CLUSTERING
    assert len(result.model_results) > 0
    assert result.best_model_name != ""
    # 클러스터링은 feature_importance 없음
    assert result.feature_importance is None


# ---------------------------------------------------------------------------
# Test 3: DeliveryPackage E2E
# ---------------------------------------------------------------------------


def test_e2e_delivery_package(sample_df, tmp_path):
    """분류 파이프라인 결과물을 DeliveryPackage로 패키징하고 디렉토리 구조 검증."""
    # 분류 파이프라인 실행
    csv_path = tmp_path / "input.csv"
    sample_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    config = AutoMLConfig(
        input_path=csv_path,
        target_column="target",
        output_dir=tmp_path / "output",
    )
    runner = AutoMLRunner(config)
    result = runner.run()

    # PDF 리포트 생성
    pdf_path = tmp_path / "report.pdf"
    saved_pdf = AutoMLReportBuilder(result).build(pdf_path)

    # 모델 저장
    model_path = tmp_path / "best_model.pkl"
    saved_model = runner.save_best_model(model_path)

    # DeliveryPackage 구성
    pkg = DeliveryPackage(output_dir=tmp_path / "delivery_out", project_name="test_project")
    pkg.add_raw(sample_df)
    pkg.add_report(saved_pdf)
    pkg.add_model(saved_model, {"model_name": result.best_model_name})
    base_dir = pkg.build()

    # 디렉토리 구조 검증
    assert base_dir.exists(), f"패키지 루트가 없음: {base_dir}"
    assert (base_dir / "01_raw").exists(), "01_raw 디렉토리 없음"
    assert (base_dir / "04_report").exists(), "04_report 디렉토리 없음"
    assert (base_dir / "model").exists(), "model 디렉토리 없음"

    # 파일 존재 여부
    raw_files = list((base_dir / "01_raw").glob("*.csv"))
    assert len(raw_files) > 0, "01_raw에 CSV 파일이 없음"

    report_files = list((base_dir / "04_report").glob("*.pdf"))
    assert len(report_files) > 0, "04_report에 PDF 파일이 없음"

    model_files = list((base_dir / "model").glob("*.pkl"))
    assert len(model_files) > 0, "model 디렉토리에 pkl 파일이 없음"

    config_json = base_dir / "model" / "config.json"
    assert config_json.exists(), "model/config.json이 없음"


# ---------------------------------------------------------------------------
# Test 4: 회귀 E2E 파이프라인
# ---------------------------------------------------------------------------


def test_e2e_regression_pipeline(sample_df, tmp_path):
    """target을 연속형 float으로 교체하여 회귀 태스크 자동 감지 검증."""
    rng = np.random.default_rng(seed=42)
    df_reg = sample_df.copy()
    df_reg["target"] = rng.uniform(0.0, 100.0, size=len(df_reg))

    csv_path = tmp_path / "input_regression.csv"
    df_reg.to_csv(csv_path, index=False, encoding="utf-8-sig")

    config = AutoMLConfig(
        input_path=csv_path,
        target_column="target",
        output_dir=tmp_path / "output_regression",
    )
    runner = AutoMLRunner(config)
    result = runner.run()

    assert isinstance(result, AutoMLResult)
    assert result.task_type == TaskType.REGRESSION
    assert len(result.model_results) > 0
    # 회귀 메트릭 키 존재 확인
    assert "rmse" in result.best_metrics or "r2" in result.best_metrics or "mae" in result.best_metrics


# ---------------------------------------------------------------------------
# Test 5: PDF 유효성 (매직 바이트 확인)
# ---------------------------------------------------------------------------


def test_report_pdf_valid(sample_df, tmp_path):
    """생성된 PDF 파일의 첫 4바이트가 PDF 매직 넘버(b'%PDF')인지 검증."""
    csv_path = tmp_path / "input.csv"
    sample_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    config = AutoMLConfig(
        input_path=csv_path,
        target_column="target",
        output_dir=tmp_path / "output",
    )
    runner = AutoMLRunner(config)
    result = runner.run()

    pdf_path = tmp_path / "report_valid.pdf"
    saved_pdf = AutoMLReportBuilder(result).build(pdf_path)

    assert saved_pdf.exists(), f"PDF 파일이 없음: {saved_pdf}"

    with open(saved_pdf, "rb") as f:
        magic = f.read(4)

    assert magic == b"%PDF", f"PDF 매직 바이트 불일치: {magic!r}"
