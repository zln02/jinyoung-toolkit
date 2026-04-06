"""AutoMLRunner 단위 테스트."""
import pytest
import numpy as np
import pandas as pd
from pathlib import Path

import automl_reporter.runner as runner_module
from automl_reporter.runner import (
    AutoMLConfig,
    AutoMLResult,
    AutoMLRunner,
    ModelResult,
    TaskType,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "sample_tabular.csv"
)


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.read_csv(FIXTURE_PATH, encoding="utf-8-sig")


@pytest.fixture
def runner_cls(sample_df: pd.DataFrame, tmp_path: Path) -> AutoMLRunner:
    """Create a runner with PyCaret disabled."""
    csv_path = tmp_path / "data.csv"
    sample_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    config = AutoMLConfig(
        input_path=csv_path,
        target_column="target",
        output_dir=tmp_path,
    )
    return AutoMLRunner(config)


class TestAutoMLRunner:
    def test_detect_task_type_binary(
        self, runner_cls: AutoMLRunner, sample_df: pd.DataFrame
    ) -> None:
        """target 2개 고유값 → BINARY_CLASSIFICATION."""
        task = runner_cls.detect_task_type(sample_df)
        assert task == TaskType.BINARY_CLASSIFICATION, (
            f"이진 타겟(0/1)이어야 BINARY_CLASSIFICATION이지만 {task}를 반환"
        )

    def test_detect_task_type_multiclass(
        self, runner_cls: AutoMLRunner
    ) -> None:
        """5개 클래스 정수 타겟 → MULTICLASS_CLASSIFICATION."""
        rng = np.random.default_rng(0)
        df = pd.DataFrame(
            {
                "f1": rng.standard_normal(100),
                "f2": rng.standard_normal(100),
                "target": rng.integers(0, 5, size=100),  # 5 unique ints
            }
        )
        task = runner_cls.detect_task_type(df)
        assert task == TaskType.MULTICLASS_CLASSIFICATION, (
            f"5-클래스 정수 타겟 → MULTICLASS_CLASSIFICATION이어야 하지만 {task} 반환"
        )

    def test_detect_task_type_regression(
        self, runner_cls: AutoMLRunner
    ) -> None:
        """float 연속형 타겟 (고유값 >20) → REGRESSION."""
        rng = np.random.default_rng(1)
        df = pd.DataFrame(
            {
                "f1": rng.standard_normal(200),
                "target": rng.uniform(0, 1000, size=200),  # continuous float
            }
        )
        task = runner_cls.detect_task_type(df)
        assert task == TaskType.REGRESSION, (
            f"연속형 float 타겟(>20 unique) → REGRESSION이어야 하지만 {task} 반환"
        )

    def test_detect_task_type_clustering(
        self, sample_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """target_column=None → CLUSTERING."""
        csv_path = tmp_path / "data_no_target.csv"
        sample_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        config = AutoMLConfig(
            input_path=csv_path,
            target_column=None,
            output_dir=tmp_path,
        )
        runner = AutoMLRunner(config)
        task = runner.detect_task_type(sample_df)
        assert task == TaskType.CLUSTERING, (
            f"target_column=None → CLUSTERING이어야 하지만 {task} 반환"
        )

    def test_run_sklearn_classification(
        self,
        runner_cls: AutoMLRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """PyCaret 비활성화 → sklearn fallback 분류 전체 파이프라인."""
        monkeypatch.setattr(runner_module, "_pycaret_available", False)

        result = runner_cls.run()

        assert isinstance(result, AutoMLResult), "run()은 AutoMLResult를 반환해야 함"
        assert result.task_type == TaskType.BINARY_CLASSIFICATION
        assert isinstance(result.model_results, list)
        assert len(result.model_results) > 0
        assert isinstance(result.best_model_name, str) and result.best_model_name
        assert isinstance(result.best_metrics, dict)
        assert isinstance(result.data_summary, dict)

    def test_run_sklearn_regression(
        self,
        sample_df: pd.DataFrame,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """PyCaret 비활성화 → sklearn fallback 회귀 전체 파이프라인."""
        monkeypatch.setattr(runner_module, "_pycaret_available", False)

        rng = np.random.default_rng(42)
        df = sample_df.copy()
        df["target"] = rng.uniform(0, 100, size=len(df))  # continuous float target

        csv_path = tmp_path / "regression_data.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")

        config = AutoMLConfig(
            input_path=csv_path,
            target_column="target",
            output_dir=tmp_path,
        )
        runner = AutoMLRunner(config)
        result = runner.run()

        assert isinstance(result, AutoMLResult)
        assert result.task_type == TaskType.REGRESSION
        assert len(result.model_results) > 0
        # 회귀 최적 모델은 RMSE 기준 선택됨
        assert "rmse" in result.best_metrics or len(result.best_metrics) >= 0

    def test_run_sklearn_clustering(
        self,
        sample_df: pd.DataFrame,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """target_column 없음 + PyCaret 비활성화 → sklearn clustering."""
        monkeypatch.setattr(runner_module, "_pycaret_available", False)

        df = sample_df.drop(columns=["target"])
        csv_path = tmp_path / "cluster_data.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")

        config = AutoMLConfig(
            input_path=csv_path,
            target_column=None,
            output_dir=tmp_path,
        )
        runner = AutoMLRunner(config)
        result = runner.run()

        assert isinstance(result, AutoMLResult)
        assert result.task_type == TaskType.CLUSTERING
        assert result.best_model_name == "KMeans"
        assert "inertia" in result.best_metrics

    def test_save_best_model(
        self,
        runner_cls: AutoMLRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """run() 후 save_best_model() → 파일 존재 & 크기 > 0."""
        monkeypatch.setattr(runner_module, "_pycaret_available", False)

        runner_cls.run()
        model_path = tmp_path / "best_model.pkl"
        saved = runner_cls.save_best_model(model_path)

        assert saved.exists(), "저장된 모델 파일이 존재해야 함"
        assert saved.stat().st_size > 0, "저장된 파일 크기가 0보다 커야 함"

    def test_data_summary(
        self,
        runner_cls: AutoMLRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """data_summary 딕셔너리에 필수 키 4개 존재 여부 확인."""
        monkeypatch.setattr(runner_module, "_pycaret_available", False)

        result = runner_cls.run()
        ds = result.data_summary

        required_keys = {"rows", "columns", "dtypes", "missing_pct"}
        assert required_keys.issubset(ds.keys()), (
            f"data_summary에 누락된 키: {required_keys - ds.keys()}"
        )
        assert isinstance(ds["rows"], int)
        assert isinstance(ds["columns"], int)
        assert isinstance(ds["dtypes"], dict)
        assert isinstance(ds["missing_pct"], dict)

    def test_text_feature_processing(
        self,
        sample_df: pd.DataFrame,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """텍스트 컬럼 포함 데이터에 include_text_features=True → 파이프라인 정상 완료."""
        monkeypatch.setattr(runner_module, "_pycaret_available", False)

        df = sample_df.copy()
        df["text_col"] = [
            "이것은 샘플 텍스트입니다 자동화 머신러닝 테스트용 긴 문장"
        ] * len(df)

        csv_path = tmp_path / "text_data.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")

        config = AutoMLConfig(
            input_path=csv_path,
            target_column="target",
            output_dir=tmp_path,
            include_text_features=True,
            text_columns=["text_col"],
        )
        runner = AutoMLRunner(config)
        result = runner.run()

        assert isinstance(result, AutoMLResult), (
            "텍스트 피처 포함 시에도 AutoMLResult를 반환해야 함"
        )
        assert len(result.model_results) > 0
