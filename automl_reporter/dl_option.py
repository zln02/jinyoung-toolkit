"""automl_reporter/dl_option.py — AutoKeras 딥러닝 옵션 래퍼.

autokeras 미설치 시 ImportError를 명확한 메시지와 함께 발생시키고,
설치된 경우 StructuredDataClassifier / StructuredDataRegressor를 실행해
ModelResult를 반환한다.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import numpy as np

from automl_reporter.runner import ModelResult, TaskType
from shared.logger import get_logger

if TYPE_CHECKING:
    pass

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# autokeras 가용성 체크
# ---------------------------------------------------------------------------
try:
    import autokeras  # noqa: F401

    _autokeras_available = True
except ImportError:
    _autokeras_available = False


# ---------------------------------------------------------------------------
# 공개 헬퍼
# ---------------------------------------------------------------------------


def is_available() -> bool:
    """autokeras 설치 여부를 반환한다.

    Returns:
        bool: autokeras가 설치되어 있으면 True, 아니면 False.

    Example:
        if is_available():
            dl = DeepLearningOption(task_type=TaskType.BINARY_CLASSIFICATION)
    """
    return _autokeras_available


# ---------------------------------------------------------------------------
# DeepLearningOption
# ---------------------------------------------------------------------------


class DeepLearningOption:
    """AutoKeras 기반 딥러닝 옵션.

    AutoKeras StructuredDataClassifier / StructuredDataRegressor를 래핑하여
    AutoML 파이프라인과 동일한 ModelResult 인터페이스로 결과를 반환한다.

    autokeras가 설치되어 있지 않으면 run() 호출 시 ImportError를 발생시킨다.

    Args:
        task_type: 수행할 태스크 유형 (TaskType 열거값).
            BINARY_CLASSIFICATION, MULTICLASS_CLASSIFICATION → StructuredDataClassifier
            REGRESSION → StructuredDataRegressor
            CLUSTERING → 미지원, run() 호출 시 ValueError 발생.
        max_trials: AutoKeras 하이퍼파라미터 탐색 횟수. 기본값 10.
        epochs: 각 trial 당 학습 에포크 수. 기본값 50.
    """

    def __init__(
        self,
        task_type: TaskType,
        max_trials: int = 10,
        epochs: int = 50,
    ) -> None:
        self.task_type = task_type
        self.max_trials = max_trials
        self.epochs = epochs
        log.info(
            "DeepLearningOption_초기화",
            task_type=task_type.value,
            max_trials=max_trials,
            epochs=epochs,
            autokeras_available=_autokeras_available,
        )

    def run(
        self,
        X_train: Any,
        y_train: Any,
        X_test: Any,
        y_test: Any,
    ) -> ModelResult:
        """AutoKeras로 구조화 데이터 모델을 학습하고 평가한다.

        autokeras가 설치되지 않은 경우 즉시 ImportError를 발생시킨다.
        CLUSTERING 태스크는 지원하지 않으며 ValueError를 발생시킨다.

        Args:
            X_train: 학습 피처 (numpy array 또는 pandas DataFrame).
            y_train: 학습 레이블 (numpy array 또는 pandas Series).
            X_test: 평가 피처 (numpy array 또는 pandas DataFrame).
            y_test: 평가 레이블 (numpy array 또는 pandas Series).

        Returns:
            ModelResult: 모델명, 메트릭(분류: accuracy / 회귀: mse, mae),
                학습 소요 시간이 담긴 결과 객체.

        Raises:
            ImportError: autokeras가 설치되어 있지 않을 때.
            ValueError: task_type이 CLUSTERING일 때.
        """
        if not _autokeras_available:
            raise ImportError(
                "autokeras가 설치되어 있지 않습니다. "
                "딥러닝 옵션을 사용하려면 `pip install autokeras`를 실행하세요."
            )

        if self.task_type == TaskType.CLUSTERING:
            raise ValueError(
                "DeepLearningOption은 CLUSTERING 태스크를 지원하지 않습니다. "
                "BINARY_CLASSIFICATION, MULTICLASS_CLASSIFICATION, REGRESSION만 사용 가능합니다."
            )

        # numpy 배열로 변환
        X_train_arr = np.array(X_train)
        y_train_arr = np.array(y_train)
        X_test_arr = np.array(X_test)
        y_test_arr = np.array(y_test)

        is_classification = self.task_type in (
            TaskType.BINARY_CLASSIFICATION,
            TaskType.MULTICLASS_CLASSIFICATION,
        )

        if is_classification:
            return self._run_classifier(
                X_train_arr, y_train_arr, X_test_arr, y_test_arr
            )
        return self._run_regressor(
            X_train_arr, y_train_arr, X_test_arr, y_test_arr
        )

    # ------------------------------------------------------------------
    # 내부 메서드
    # ------------------------------------------------------------------

    def _run_classifier(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_test: np.ndarray,
        y_test: np.ndarray,
    ) -> ModelResult:
        """StructuredDataClassifier 실행 후 ModelResult 반환."""
        import autokeras as ak  # 런타임 import (가용성 이미 확인됨)

        log.info(
            "AutoKeras_분류_시작",
            max_trials=self.max_trials,
            epochs=self.epochs,
        )

        t_start = time.perf_counter()
        try:
            clf = ak.StructuredDataClassifier(
                max_trials=self.max_trials,
                overwrite=True,
            )
            clf.fit(X_train, y_train, epochs=self.epochs, verbose=0)
        except Exception as exc:
            log.error("AutoKeras_분류_학습_실패", error=str(exc))
            raise

        elapsed = time.perf_counter() - t_start

        try:
            metrics: dict[str, float] = {}
            loss, accuracy = clf.evaluate(X_test, y_test, verbose=0)
            metrics["accuracy"] = float(accuracy)
            metrics["loss"] = float(loss)
        except Exception as exc:
            log.warning("AutoKeras_분류_평가_실패", error=str(exc))
            metrics = {}

        log.info(
            "AutoKeras_분류_완료",
            elapsed_seconds=round(elapsed, 2),
            metrics=metrics,
        )
        return ModelResult(
            name="AutoKeras_StructuredDataClassifier",
            metrics=metrics,
            is_tuned=True,
            training_time_seconds=elapsed,
        )

    def _run_regressor(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_test: np.ndarray,
        y_test: np.ndarray,
    ) -> ModelResult:
        """StructuredDataRegressor 실행 후 ModelResult 반환."""
        import autokeras as ak  # 런타임 import (가용성 이미 확인됨)

        log.info(
            "AutoKeras_회귀_시작",
            max_trials=self.max_trials,
            epochs=self.epochs,
        )

        t_start = time.perf_counter()
        try:
            reg = ak.StructuredDataRegressor(
                max_trials=self.max_trials,
                overwrite=True,
            )
            reg.fit(X_train, y_train, epochs=self.epochs, verbose=0)
        except Exception as exc:
            log.error("AutoKeras_회귀_학습_실패", error=str(exc))
            raise

        elapsed = time.perf_counter() - t_start

        try:
            metrics: dict[str, float] = {}
            loss, mse = reg.evaluate(X_test, y_test, verbose=0)
            metrics["mse"] = float(mse)
            metrics["mae"] = float(loss)
        except Exception as exc:
            log.warning("AutoKeras_회귀_평가_실패", error=str(exc))
            metrics = {}

        log.info(
            "AutoKeras_회귀_완료",
            elapsed_seconds=round(elapsed, 2),
            metrics=metrics,
        )
        return ModelResult(
            name="AutoKeras_StructuredDataRegressor",
            metrics=metrics,
            is_tuned=True,
            training_time_seconds=elapsed,
        )
