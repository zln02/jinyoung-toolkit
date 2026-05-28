"""automl_reporter/runner.py — PyCaret 래핑 AutoML 실행기.

PyCaret 미설치 시 scikit-learn fallback으로 자동 전환.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from pydantic import BaseModel

from shared.config import get_settings
from shared.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# PyCaret 가용성 체크
# ---------------------------------------------------------------------------
try:
    import pycaret  # noqa: F401

    _pycaret_available = True
except ImportError:
    _pycaret_available = False


# ---------------------------------------------------------------------------
# 열거형 / 데이터 클래스
# ---------------------------------------------------------------------------


class TaskType(str, Enum):
    BINARY_CLASSIFICATION = "binary_classification"
    MULTICLASS_CLASSIFICATION = "multiclass_classification"
    REGRESSION = "regression"
    CLUSTERING = "clustering"


class AutoMLConfig(BaseModel):
    input_path: Path
    target_column: str | None = None
    task_type: TaskType | None = None
    top_n_models: int = 5
    optimize_metric: str | None = None
    tune_top_n: int = 3
    cv_folds: int = 5
    test_size: float = 0.3
    random_seed: int = 42
    include_text_features: bool = False
    text_columns: list[str] = []
    output_dir: Path = Path("./output")


@dataclass
class ModelResult:
    name: str
    metrics: dict[str, float]
    is_tuned: bool
    training_time_seconds: float


@dataclass
class AutoMLResult:
    task_type: TaskType
    model_results: list[ModelResult]
    best_model_name: str
    best_metrics: dict[str, float]
    feature_importance: dict[str, float] | None
    data_summary: dict[str, Any]


# ---------------------------------------------------------------------------
# AutoMLRunner
# ---------------------------------------------------------------------------


class AutoMLRunner:
    """PyCaret 래핑 AutoML 실행기.

    PyCaret 미설치 시 scikit-learn fallback.
    """

    def __init__(self, config: AutoMLConfig) -> None:
        self.config = config
        settings = get_settings()
        # config 값이 기본값이면 global settings 반영
        if config.random_seed == 42:
            self.config = config.model_copy(
                update={"random_seed": settings.random_seed}
            )
        if config.test_size == 0.3:
            self.config = self.config.model_copy(
                update={"test_size": settings.test_size}
            )
        self._best_model: Any = None
        log.info(
            "AutoMLRunner_초기화",
            pycaret_available=_pycaret_available,
            input_path=str(self.config.input_path),
        )

    def _is_pycaret_available(self) -> bool:
        return _pycaret_available

    def detect_task_type(self, df: pd.DataFrame) -> TaskType:
        """타겟 분석으로 자동 감지.

        - target_column이 None → CLUSTERING
        - nunique <= 2 → BINARY_CLASSIFICATION
        - nunique <= 20 and dtype is object/category/int → MULTICLASS_CLASSIFICATION
        - 나머지 → REGRESSION
        """
        if self.config.target_column is None:
            log.info("태스크_유형_감지", result="CLUSTERING", reason="target_column=None")
            return TaskType.CLUSTERING

        target: pd.Series = df[self.config.target_column]
        n_unique = target.nunique()
        dtype = target.dtype

        if n_unique <= 2:
            task = TaskType.BINARY_CLASSIFICATION
            reason = f"nunique={n_unique}"
        elif n_unique <= 20 and (
            dtype == object
            or hasattr(dtype, "name")
            and dtype.name in ("category", "object")
            or pd.api.types.is_integer_dtype(dtype)
        ):
            task = TaskType.MULTICLASS_CLASSIFICATION
            reason = f"nunique={n_unique}, dtype={dtype}"
        else:
            task = TaskType.REGRESSION
            reason = f"nunique={n_unique}, dtype={dtype}"

        log.info("태스크_유형_감지", result=task.value, reason=reason)
        return task

    def _get_data_summary(self, df: pd.DataFrame) -> dict[str, Any]:
        """데이터 요약: rows, columns, dtypes, missing_pct, target_distribution"""
        missing_pct: dict[str, float] = {
            col: float(df[col].isna().mean() * 100) for col in df.columns
        }
        dtypes: dict[str, str] = {col: str(df[col].dtype) for col in df.columns}

        target_distribution: dict[str, Any] | None = None
        if self.config.target_column and self.config.target_column in df.columns:
            target_series = df[self.config.target_column]
            if pd.api.types.is_numeric_dtype(target_series) and target_series.nunique() > 20:
                target_distribution = {
                    "mean": float(target_series.mean()),
                    "std": float(target_series.std()),
                    "min": float(target_series.min()),
                    "max": float(target_series.max()),
                }
            else:
                vc = target_series.value_counts(normalize=True)
                target_distribution = {str(k): float(v) for k, v in vc.items()}

        return {
            "rows": int(len(df)),
            "columns": int(len(df.columns)),
            "dtypes": dtypes,
            "missing_pct": missing_pct,
            "target_distribution": target_distribution,
        }

    # ------------------------------------------------------------------
    # PyCaret 실행
    # ------------------------------------------------------------------

    def _run_with_pycaret(self, df: pd.DataFrame) -> AutoMLResult:
        """PyCaret 사용 실행."""
        cfg = self.config
        task_type = cfg.task_type or self.detect_task_type(df)
        data_summary = self._get_data_summary(df)

        log.info("PyCaret_실행_시작", task_type=task_type.value)

        if task_type == TaskType.CLUSTERING:
            return self._run_pycaret_clustering(df, task_type, data_summary)

        if task_type in (
            TaskType.BINARY_CLASSIFICATION,
            TaskType.MULTICLASS_CLASSIFICATION,
        ):
            return self._run_pycaret_classification(df, task_type, data_summary)

        return self._run_pycaret_regression(df, task_type, data_summary)

    def _run_pycaret_classification(
        self,
        df: pd.DataFrame,
        task_type: TaskType,
        data_summary: dict[str, Any],
    ) -> AutoMLResult:
        from pycaret.classification import (
            compare_models,
            pull,
            setup,
            tune_model,
        )

        cfg = self.config
        metric = cfg.optimize_metric or "Accuracy"

        setup(
            data=df,
            target=cfg.target_column,
            train_size=1.0 - cfg.test_size,
            fold=cfg.cv_folds,
            session_id=cfg.random_seed,
            verbose=False,
        )

        top_models = compare_models(
            n_select=cfg.top_n_models,
            sort=metric,
            verbose=False,
        )
        if not isinstance(top_models, list):
            top_models = [top_models]

        compare_df: pd.DataFrame = pull()
        model_results: list[ModelResult] = []

        for model in top_models:
            model_name = type(model).__name__
            row = compare_df[compare_df.index == model_name]
            metrics: dict[str, float] = {}
            for col in ("Accuracy", "F1", "Prec.", "Recall", "AUC"):
                if col in compare_df.columns and not row.empty:
                    val = row[col].values[0]
                    metrics[col.lower().rstrip(".")] = float(val) if pd.notna(val) else 0.0
            model_results.append(
                ModelResult(
                    name=model_name,
                    metrics=metrics,
                    is_tuned=False,
                    training_time_seconds=float(
                        row["TT (Sec)"].values[0]
                        if not row.empty and "TT (Sec)" in compare_df.columns
                        else 0.0
                    ),
                )
            )

        # tune top_n
        tuned_models = []
        for i, model in enumerate(top_models[: cfg.tune_top_n]):
            try:
                t_start = time.perf_counter()
                tuned = tune_model(model, optimize=metric, verbose=False)
                elapsed = time.perf_counter() - t_start
                tuned_df: pd.DataFrame = pull()
                tuned_metrics: dict[str, float] = {}
                for col in ("Accuracy", "F1", "Prec.", "Recall", "AUC"):
                    if col in tuned_df.columns:
                        val = tuned_df[col].values[-1]
                        tuned_metrics[col.lower().rstrip(".")] = float(val) if pd.notna(val) else 0.0
                model_results.append(
                    ModelResult(
                        name=f"{type(tuned).__name__}_tuned",
                        metrics=tuned_metrics,
                        is_tuned=True,
                        training_time_seconds=elapsed,
                    )
                )
                tuned_models.append(tuned)
            except Exception as exc:
                log.warning("PyCaret_튜닝_실패", index=i, error=str(exc))

        best_model = tuned_models[0] if tuned_models else top_models[0]
        self._best_model = best_model
        best_result = model_results[-len(tuned_models)] if tuned_models else model_results[0]

        feature_importance = _extract_feature_importance_pycaret(best_model, df, cfg.target_column)

        log.info("PyCaret_분류_완료", best=best_result.name)
        return AutoMLResult(
            task_type=task_type,
            model_results=model_results,
            best_model_name=best_result.name,
            best_metrics=best_result.metrics,
            feature_importance=feature_importance,
            data_summary=data_summary,
        )

    def _run_pycaret_regression(
        self,
        df: pd.DataFrame,
        task_type: TaskType,
        data_summary: dict[str, Any],
    ) -> AutoMLResult:
        from pycaret.regression import (
            compare_models,
            pull,
            setup,
            tune_model,
        )

        cfg = self.config
        metric = cfg.optimize_metric or "RMSE"

        setup(
            data=df,
            target=cfg.target_column,
            train_size=1.0 - cfg.test_size,
            fold=cfg.cv_folds,
            session_id=cfg.random_seed,
            verbose=False,
        )

        top_models = compare_models(
            n_select=cfg.top_n_models,
            sort=metric,
            verbose=False,
        )
        if not isinstance(top_models, list):
            top_models = [top_models]

        compare_df: pd.DataFrame = pull()
        model_results: list[ModelResult] = []

        for model in top_models:
            model_name = type(model).__name__
            row = compare_df[compare_df.index == model_name]
            metrics: dict[str, float] = {}
            for col in ("RMSE", "MAE", "R2"):
                if col in compare_df.columns and not row.empty:
                    val = row[col].values[0]
                    metrics[col.lower()] = float(val) if pd.notna(val) else 0.0
            model_results.append(
                ModelResult(
                    name=model_name,
                    metrics=metrics,
                    is_tuned=False,
                    training_time_seconds=float(
                        row["TT (Sec)"].values[0]
                        if not row.empty and "TT (Sec)" in compare_df.columns
                        else 0.0
                    ),
                )
            )

        tuned_models = []
        for i, model in enumerate(top_models[: cfg.tune_top_n]):
            try:
                t_start = time.perf_counter()
                tuned = tune_model(model, optimize=metric, verbose=False)
                elapsed = time.perf_counter() - t_start
                tuned_df: pd.DataFrame = pull()
                tuned_metrics: dict[str, float] = {}
                for col in ("RMSE", "MAE", "R2"):
                    if col in tuned_df.columns:
                        val = tuned_df[col].values[-1]
                        tuned_metrics[col.lower()] = float(val) if pd.notna(val) else 0.0
                model_results.append(
                    ModelResult(
                        name=f"{type(tuned).__name__}_tuned",
                        metrics=tuned_metrics,
                        is_tuned=True,
                        training_time_seconds=elapsed,
                    )
                )
                tuned_models.append(tuned)
            except Exception as exc:
                log.warning("PyCaret_튜닝_실패", index=i, error=str(exc))

        best_model = tuned_models[0] if tuned_models else top_models[0]
        self._best_model = best_model
        best_result = model_results[-len(tuned_models)] if tuned_models else model_results[0]

        feature_importance = _extract_feature_importance_pycaret(best_model, df, cfg.target_column)

        log.info("PyCaret_회귀_완료", best=best_result.name)
        return AutoMLResult(
            task_type=task_type,
            model_results=model_results,
            best_model_name=best_result.name,
            best_metrics=best_result.metrics,
            feature_importance=feature_importance,
            data_summary=data_summary,
        )

    def _run_pycaret_clustering(
        self,
        df: pd.DataFrame,
        task_type: TaskType,
        data_summary: dict[str, Any],
    ) -> AutoMLResult:
        from pycaret.clustering import (
            assign_model,
            compare_models,
            create_model,
            pull,
            setup,
        )

        cfg = self.config

        setup(
            data=df,
            session_id=cfg.random_seed,
            verbose=False,
        )

        t_start = time.perf_counter()
        best_model = create_model("kmeans", verbose=False)
        elapsed = time.perf_counter() - t_start

        self._best_model = best_model
        model_name = type(best_model).__name__

        model_results = [
            ModelResult(
                name=model_name,
                metrics={},
                is_tuned=False,
                training_time_seconds=elapsed,
            )
        ]

        log.info("PyCaret_클러스터링_완료", model=model_name)
        return AutoMLResult(
            task_type=task_type,
            model_results=model_results,
            best_model_name=model_name,
            best_metrics={},
            feature_importance=None,
            data_summary=data_summary,
        )

    # ------------------------------------------------------------------
    # sklearn fallback
    # ------------------------------------------------------------------

    def _run_with_sklearn(self, df: pd.DataFrame) -> AutoMLResult:
        """scikit-learn fallback."""
        from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor
        from sklearn.linear_model import LinearRegression, LogisticRegression
        from sklearn.model_selection import cross_val_score, train_test_split
        from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor
        from sklearn.preprocessing import LabelEncoder
        from sklearn.svm import SVC, SVR

        cfg = self.config
        task_type = cfg.task_type or self.detect_task_type(df)
        data_summary = self._get_data_summary(df)

        log.info("sklearn_fallback_실행", task_type=task_type.value)

        if task_type == TaskType.CLUSTERING:
            return self._run_sklearn_clustering(df, task_type, data_summary)

        # 피처/타겟 분리
        target_col = cfg.target_column
        X = df.drop(columns=[target_col])
        y = df[target_col]

        # 수치형 컬럼만 사용
        X = X.select_dtypes(include=[np.number]).fillna(0)

        # 수치형 피처가 하나도 없으면(범주형/텍스트만) 조용히 실패하지 않고 명확히 안내
        if X.shape[1] == 0:
            raise RuntimeError(
                "수치형 피처가 없습니다. 타깃을 제외한 컬럼이 모두 텍스트/범주형입니다. "
                "텍스트 데이터라면 '텍스트 피처 포함' 옵션을 켜고 텍스트 컬럼을 선택하세요."
            )

        is_classification = task_type in (
            TaskType.BINARY_CLASSIFICATION,
            TaskType.MULTICLASS_CLASSIFICATION,
        )

        # 분류: 레이블 인코딩
        le: LabelEncoder | None = None
        if is_classification and not pd.api.types.is_numeric_dtype(y):
            le = LabelEncoder()
            y = pd.Series(le.fit_transform(y), index=y.index)

        if is_classification:
            candidate_models: list[tuple[str, Any]] = [
                ("LogisticRegression", LogisticRegression(max_iter=1000, random_state=cfg.random_seed)),
                ("RandomForestClassifier", RandomForestClassifier(random_state=cfg.random_seed)),
                ("GradientBoostingClassifier", GradientBoostingClassifier(random_state=cfg.random_seed)),
                ("SVC", SVC(random_state=cfg.random_seed, probability=True)),
                ("KNeighborsClassifier", KNeighborsClassifier()),
            ]
            scoring_metrics = ["accuracy", "f1_weighted", "precision_weighted", "recall_weighted"]
            metric_key_map = {
                "accuracy": "accuracy",
                "f1_weighted": "f1",
                "precision_weighted": "precision",
                "recall_weighted": "recall",
            }
        else:
            candidate_models = [
                ("LinearRegression", LinearRegression()),
                ("RandomForestRegressor", RandomForestRegressor(random_state=cfg.random_seed)),
                ("GradientBoostingRegressor", GradientBoostingRegressor(random_state=cfg.random_seed)),
                ("SVR", SVR()),
                ("KNeighborsRegressor", KNeighborsRegressor()),
            ]
            scoring_metrics = ["neg_root_mean_squared_error", "neg_mean_absolute_error", "r2"]
            metric_key_map = {
                "neg_root_mean_squared_error": "rmse",
                "neg_mean_absolute_error": "mae",
                "r2": "r2",
            }

        model_results: list[ModelResult] = []

        for model_name, model in candidate_models:
            t_start = time.perf_counter()
            try:
                metrics: dict[str, float] = {}
                for scoring in scoring_metrics:
                    try:
                        scores = cross_val_score(
                            model,
                            X,
                            y,
                            cv=cfg.cv_folds,
                            scoring=scoring,
                        )
                        raw_mean = float(scores.mean())
                        key = metric_key_map[scoring]
                        # neg 메트릭은 절댓값으로 변환
                        metrics[key] = abs(raw_mean) if scoring.startswith("neg_") else raw_mean
                    except Exception as exc:
                        log.warning("sklearn_메트릭_계산_실패", model=model_name, scoring=scoring, error=str(exc))
                elapsed = time.perf_counter() - t_start
                model_results.append(
                    ModelResult(
                        name=model_name,
                        metrics=metrics,
                        is_tuned=False,
                        training_time_seconds=elapsed,
                    )
                )
                log.info("sklearn_모델_평가_완료", model=model_name, metrics=metrics)
            except Exception as exc:
                elapsed = time.perf_counter() - t_start
                log.warning("sklearn_모델_실패", model=model_name, error=str(exc))

        if not model_results:
            raise RuntimeError("모든 sklearn 모델 평가가 실패했습니다.")

        # 최적 모델 선택
        if is_classification:
            sort_key = "accuracy"
            best_result = max(model_results, key=lambda r: r.metrics.get(sort_key, 0.0))
        else:
            # RMSE가 낮을수록 좋음
            best_result = min(model_results, key=lambda r: r.metrics.get("rmse", float("inf")))

        # 최적 모델 재학습 (feature_importance 추출용)
        best_model_cls = next(
            (m for name, m in candidate_models if name == best_result.name), None
        )
        feature_importance: dict[str, float] | None = None
        if best_model_cls is not None:
            try:
                best_model_cls.fit(X, y)
                self._best_model = best_model_cls
                feature_importance = _extract_feature_importance_sklearn(best_model_cls, list(X.columns))
            except Exception as exc:
                log.warning("최적_모델_재학습_실패", error=str(exc))

        log.info("sklearn_fallback_완료", best=best_result.name)
        return AutoMLResult(
            task_type=task_type,
            model_results=model_results,
            best_model_name=best_result.name,
            best_metrics=best_result.metrics,
            feature_importance=feature_importance,
            data_summary=data_summary,
        )

    def _run_sklearn_clustering(
        self,
        df: pd.DataFrame,
        task_type: TaskType,
        data_summary: dict[str, Any],
    ) -> AutoMLResult:
        from sklearn.cluster import KMeans
        from sklearn.metrics import silhouette_score
        from sklearn.preprocessing import StandardScaler

        cfg = self.config
        X = df.select_dtypes(include=[np.number]).fillna(0)
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        t_start = time.perf_counter()
        model = KMeans(n_clusters=3, random_state=cfg.random_seed, n_init=10)
        labels = model.fit_predict(X_scaled)
        elapsed = time.perf_counter() - t_start

        self._best_model = model
        metrics: dict[str, float] = {}
        if len(set(labels)) > 1:
            try:
                metrics["silhouette_score"] = float(silhouette_score(X_scaled, labels))
            except Exception as exc:
                log.warning("실루엣_점수_계산_실패", error=str(exc))
        metrics["inertia"] = float(model.inertia_)

        model_name = "KMeans"
        model_results = [
            ModelResult(
                name=model_name,
                metrics=metrics,
                is_tuned=False,
                training_time_seconds=elapsed,
            )
        ]

        log.info("sklearn_클러스터링_완료", model=model_name, metrics=metrics)
        return AutoMLResult(
            task_type=task_type,
            model_results=model_results,
            best_model_name=model_name,
            best_metrics=metrics,
            feature_importance=None,
            data_summary=data_summary,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> AutoMLResult:
        """전체 파이프라인.

        1. CSV 로드
        2. 텍스트 컬럼 처리 (include_text_features면 KoreanTextProcessor.to_tfidf_features)
        3. 문제 유형 감지
        4. PyCaret 또는 sklearn 실행
        5. AutoMLResult 반환
        """
        cfg = self.config
        log.info("AutoML_파이프라인_시작", input_path=str(cfg.input_path))

        # 1. CSV 로드 (utf-8-sig — app이 BOM 포함으로 저장하므로 컬럼명 오염 방지)
        try:
            df = pd.read_csv(cfg.input_path, encoding="utf-8-sig")
        except Exception as exc:
            log.error("CSV_로드_실패", path=str(cfg.input_path), error=str(exc))
            raise

        log.info("CSV_로드_완료", rows=len(df), columns=len(df.columns))

        # 2. 텍스트 피처 처리
        if cfg.include_text_features and cfg.text_columns:
            from shared.korean_nlp import KoreanTextProcessor

            processor = KoreanTextProcessor()
            tfidf_frames: list[pd.DataFrame] = []
            for col in cfg.text_columns:
                if col not in df.columns:
                    log.warning("텍스트_컬럼_없음", column=col)
                    continue
                try:
                    tfidf_df = processor.to_tfidf_features(df[col], max_features=500)
                    # 컬럼명 충돌 방지
                    tfidf_df.columns = [f"{col}_tfidf_{c}" for c in tfidf_df.columns]
                    tfidf_frames.append(tfidf_df)
                    log.info("텍스트_TF-IDF_변환_완료", column=col, features=len(tfidf_df.columns))
                except Exception as exc:
                    log.warning("텍스트_TF-IDF_변환_실패", column=col, error=str(exc))

            if tfidf_frames:
                df = pd.concat([df] + tfidf_frames, axis=1)
                # 원본 텍스트 컬럼 제거
                df = df.drop(
                    columns=[c for c in cfg.text_columns if c in df.columns],
                    errors="ignore",
                )
                log.info("텍스트_피처_병합_완료", new_shape=df.shape)

        # 3. 문제 유형 감지
        if cfg.task_type is not None:
            task_type = cfg.task_type
        else:
            task_type = self.detect_task_type(df)
            self.config = cfg.model_copy(update={"task_type": task_type})

        log.info("최종_태스크_유형", task_type=task_type.value)

        # 4. 실행
        if self._is_pycaret_available():
            log.info("PyCaret_사용")
            result = self._run_with_pycaret(df)
        else:
            log.info("sklearn_fallback_사용")
            result = self._run_with_sklearn(df)

        log.info(
            "AutoML_완료",
            best_model=result.best_model_name,
            best_metrics=result.best_metrics,
        )
        return result

    def save_best_model(self, output_path: Path) -> Path:
        """최적 모델 저장 (pickle via joblib)."""
        if self._best_model is None:
            raise RuntimeError("저장할 모델이 없습니다. run()을 먼저 실행하세요.")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            joblib.dump(self._best_model, output_path)
        except Exception as exc:
            log.error("모델_저장_실패", path=str(output_path), error=str(exc))
            raise

        log.info("모델_저장_완료", path=str(output_path))
        return output_path.resolve()


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _extract_feature_importance_sklearn(
    model: Any,
    feature_names: list[str],
) -> dict[str, float] | None:
    """tree 기반 sklearn 모델에서 feature_importance 추출."""
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        return None
    if len(importances) != len(feature_names):
        return None
    return {name: float(imp) for name, imp in zip(feature_names, importances)}


def _extract_feature_importance_pycaret(
    model: Any,
    df: pd.DataFrame,
    target_column: str | None,
) -> dict[str, float] | None:
    """PyCaret 모델 래퍼에서 feature_importance 추출."""
    # PyCaret 파이프라인 내부 estimator 접근
    inner = getattr(model, "steps", None)
    estimator = model
    if inner is not None:
        # Pipeline 마지막 스텝
        try:
            estimator = inner[-1][1]
        except (IndexError, TypeError):
            pass

    feature_cols = (
        [c for c in df.columns if c != target_column] if target_column else list(df.columns)
    )
    return _extract_feature_importance_sklearn(estimator, feature_cols)
