"""DeepLearningOption 단위 테스트."""
import numpy as np
import pytest

import automl_reporter.dl_option as dl_option
from automl_reporter.dl_option import DeepLearningOption, is_available
from automl_reporter.runner import TaskType


class TestDLOption:
    def test_is_available_returns_bool(self) -> None:
        """is_available()은 항상 bool 타입을 반환해야 한다."""
        result = is_available()
        assert isinstance(result, bool), (
            f"is_available()은 bool이어야 하지만 {type(result)} 반환됨"
        )

    def test_clustering_raises_valueerror(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLUSTERING 태스크로 run() 호출 시 ValueError (autokeras가 있는 것처럼 패치)."""
        # autokeras 미설치 환경에서도 CLUSTERING 검사가 먼저 동작하도록
        # _autokeras_available을 True로 패치해 ImportError 우선 처리를 건너뜀
        monkeypatch.setattr(dl_option, "_autokeras_available", True)

        dl = DeepLearningOption(task_type=TaskType.CLUSTERING)
        rng = np.random.default_rng(0)
        X = rng.standard_normal((20, 4))
        y = rng.integers(0, 2, size=20)

        with pytest.raises(ValueError, match="CLUSTERING"):
            dl.run(X, y, X, y)

    def test_import_error_when_not_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """autokeras 미설치 상태에서 run() 호출 시 ImportError가 발생해야 한다."""
        monkeypatch.setattr(dl_option, "_autokeras_available", False)

        dl = DeepLearningOption(task_type=TaskType.BINARY_CLASSIFICATION)

        rng = np.random.default_rng(1)
        X = rng.standard_normal((30, 5))
        y = rng.integers(0, 2, size=30)

        with pytest.raises(ImportError, match="autokeras"):
            dl.run(X, y, X, y)
