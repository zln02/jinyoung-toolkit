"""
automl_reporter/visualizer.py — AutoML 결과 시각화 모듈.

confusion matrix, feature importance, model comparison, residual plot,
target distribution 차트를 생성하여 파일로 저장한다.

사용법:
    from automl_reporter.visualizer import Visualizer

    viz = Visualizer()
    path = viz.confusion_matrix(y_true, y_pred, labels=["cat", "dog"])
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
from sklearn.metrics import confusion_matrix as sk_confusion_matrix

from shared.korean_nlp import KoreanTextProcessor
from shared.logger import get_logger

log = get_logger(__name__)

_FIGSIZE_DEFAULT = (10, 6)
_DPI = 150


class Visualizer:
    """AutoML 결과 시각화 클래스.

    matplotlib 백엔드 Agg (서버용).
    한글 폰트 자동 설정.
    """

    def __init__(self) -> None:
        """한글 폰트를 matplotlib에 등록."""
        try:
            font_path: Path = KoreanTextProcessor.find_korean_font()
            font_prop = fm.FontProperties(fname=str(font_path))
            fm.fontManager.addfont(str(font_path))
            plt.rcParams["font.family"] = font_prop.get_name()
            plt.rcParams["axes.unicode_minus"] = False
            log.info("한글_폰트_등록_완료", font=str(font_path))
        except RuntimeError as exc:
            log.warning("한글_폰트_등록_실패", error=str(exc))

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_output_path(
        output_path: Path | None, suffix: str = ".png"
    ) -> Path:
        """output_path가 None이면 임시 디렉토리에 파일 경로를 생성한다.

        Args:
            output_path: 사용자 지정 저장 경로. None이면 자동 생성.
            suffix: 파일 확장자. 기본값 ``".png"``.

        Returns:
            확정된 저장 경로 (부모 디렉토리까지 생성됨).
        """
        if output_path is None:
            tmp_dir = Path(tempfile.mkdtemp())
            return tmp_dir / f"chart{suffix}"
        resolved = Path(output_path).resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def confusion_matrix(
        self,
        y_true: Any,
        y_pred: Any,
        labels: list[str] | None = None,
        output_path: Path | None = None,
        title: str = "혼동 행렬",
    ) -> Path:
        """혼동 행렬 히트맵을 생성하여 저장한다.

        sklearn.metrics.confusion_matrix로 행렬을 계산하고
        seaborn.heatmap으로 시각화한다.

        Args:
            y_true: 실제 레이블 배열.
            y_pred: 예측 레이블 배열.
            labels: 클래스 레이블 이름 리스트. None이면 자동 추출.
            output_path: 저장 경로. None이면 임시 디렉토리에 저장.
            title: 차트 제목.

        Returns:
            저장된 이미지 파일의 절대 Path.
        """
        save_path = self._resolve_output_path(output_path)

        cm = sk_confusion_matrix(y_true, y_pred, labels=labels)
        display_labels = labels if labels is not None else sorted(
            set(np.concatenate([np.unique(y_true), np.unique(y_pred)]))
        )

        fig, ax = plt.subplots(figsize=_FIGSIZE_DEFAULT)
        sns.heatmap(
            cm,
            annot=True,
            fmt="d",
            cmap="Blues",
            xticklabels=display_labels,
            yticklabels=display_labels,
            ax=ax,
        )
        ax.set_title(title)
        ax.set_xlabel("예측 레이블")
        ax.set_ylabel("실제 레이블")
        plt.tight_layout()
        plt.savefig(save_path, dpi=_DPI)
        plt.close(fig)

        log.info("혼동_행렬_저장", path=str(save_path))
        return save_path

    def feature_importance(
        self,
        importances: dict[str, float],
        top_k: int = 10,
        output_path: Path | None = None,
        title: str = "피처 중요도 Top 10",
    ) -> Path:
        """수평 막대 그래프(피처 중요도)를 생성하여 저장한다.

        importances를 내림차순 정렬 후 상위 top_k개만 표시한다.

        Args:
            importances: {피처명: 중요도} 딕셔너리.
            top_k: 표시할 상위 피처 수. 기본값 10.
            output_path: 저장 경로. None이면 임시 디렉토리에 저장.
            title: 차트 제목.

        Returns:
            저장된 이미지 파일의 절대 Path.
        """
        save_path = self._resolve_output_path(output_path)

        sorted_items = sorted(importances.items(), key=lambda x: x[1], reverse=True)
        top_items = sorted_items[:top_k]
        features = [item[0] for item in reversed(top_items)]
        values = [item[1] for item in reversed(top_items)]

        colors = plt.get_cmap("tab10").colors  # type: ignore[attr-defined]

        fig, ax = plt.subplots(figsize=_FIGSIZE_DEFAULT)
        bars = ax.barh(features, values, color=colors[0])
        ax.set_title(title)
        ax.set_xlabel("중요도")
        ax.set_ylabel("피처")
        for bar, val in zip(bars, values):
            ax.text(
                bar.get_width() + max(values) * 0.01,
                bar.get_y() + bar.get_height() / 2,
                f"{val:.4f}",
                va="center",
                fontsize=9,
            )
        plt.tight_layout()
        plt.savefig(save_path, dpi=_DPI)
        plt.close(fig)

        log.info("피처_중요도_저장", path=str(save_path), top_k=top_k)
        return save_path

    def model_comparison_bar(
        self,
        model_names: list[str],
        scores: list[float],
        metric_name: str = "Accuracy",
        output_path: Path | None = None,
        title: str = "모델 비교",
    ) -> Path:
        """수직 막대 그래프(모델 비교)를 생성하여 저장한다.

        최고 성능 모델은 색상으로 강조된다.

        Args:
            model_names: 모델 이름 리스트.
            scores: 각 모델의 성능 점수 리스트 (model_names와 순서 일치).
            metric_name: 성능 지표 이름. 기본값 ``"Accuracy"``.
            output_path: 저장 경로. None이면 임시 디렉토리에 저장.
            title: 차트 제목.

        Returns:
            저장된 이미지 파일의 절대 Path.
        """
        save_path = self._resolve_output_path(output_path)

        cmap = plt.get_cmap("tab10").colors  # type: ignore[attr-defined]
        best_idx = int(np.argmax(scores))
        bar_colors = [
            cmap[1] if i == best_idx else cmap[0]
            for i in range(len(model_names))
        ]

        fig, ax = plt.subplots(figsize=_FIGSIZE_DEFAULT)
        bars = ax.bar(model_names, scores, color=bar_colors)
        ax.set_title(title)
        ax.set_xlabel("모델")
        ax.set_ylabel(metric_name)
        score_range = max(scores) - min(scores) if len(scores) > 1 else max(scores)
        y_min = max(0.0, min(scores) - score_range * 0.1)
        ax.set_ylim(bottom=y_min)
        for bar, score in zip(bars, scores):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + score_range * 0.01,
                f"{score:.4f}",
                ha="center",
                va="bottom",
                fontsize=9,
            )
        plt.tight_layout()
        plt.savefig(save_path, dpi=_DPI)
        plt.close(fig)

        log.info(
            "모델_비교_차트_저장",
            path=str(save_path),
            best_model=model_names[best_idx],
            best_score=scores[best_idx],
        )
        return save_path

    def residual_plot(
        self,
        y_true: Any,
        y_pred: Any,
        output_path: Path | None = None,
        title: str = "잔차 분포",
    ) -> Path:
        """잔차 산점도(회귀용)를 생성하여 저장한다.

        x축은 예측값, y축은 잔차(y_true - y_pred)이며
        잔차 0 기준선을 함께 표시한다.

        Args:
            y_true: 실제 값 배열.
            y_pred: 예측 값 배열.
            output_path: 저장 경로. None이면 임시 디렉토리에 저장.
            title: 차트 제목.

        Returns:
            저장된 이미지 파일의 절대 Path.
        """
        save_path = self._resolve_output_path(output_path)

        y_true_arr = np.asarray(y_true, dtype=float)
        y_pred_arr = np.asarray(y_pred, dtype=float)
        residuals = y_true_arr - y_pred_arr

        cmap = plt.get_cmap("tab10").colors  # type: ignore[attr-defined]

        fig, ax = plt.subplots(figsize=_FIGSIZE_DEFAULT)
        ax.scatter(y_pred_arr, residuals, color=cmap[0], alpha=0.6, s=30)
        ax.axhline(y=0, color="red", linestyle="--", linewidth=1.5, label="잔차=0")
        ax.set_title(title)
        ax.set_xlabel("예측값")
        ax.set_ylabel("잔차 (실제 - 예측)")
        ax.legend()
        plt.tight_layout()
        plt.savefig(save_path, dpi=_DPI)
        plt.close(fig)

        log.info("잔차_분포_저장", path=str(save_path))
        return save_path

    def target_distribution(
        self,
        series: Any,
        output_path: Path | None = None,
        title: str = "타겟 분포",
    ) -> Path:
        """타겟 변수 분포 차트를 생성하여 저장한다.

        범주형(object/category/bool 또는 유니크 값 20개 이하)이면 막대 그래프,
        연속형이면 히스토그램을 그린다.

        Args:
            series: 타겟 변수 배열 또는 pd.Series.
            output_path: 저장 경로. None이면 임시 디렉토리에 저장.
            title: 차트 제목.

        Returns:
            저장된 이미지 파일의 절대 Path.
        """
        import pandas as pd  # 로컬 import (선택적 의존성 최소화)

        save_path = self._resolve_output_path(output_path)

        s = pd.Series(series) if not isinstance(series, pd.Series) else series
        cmap = plt.get_cmap("tab10").colors  # type: ignore[attr-defined]

        is_categorical = (
            s.dtype == "object"
            or s.dtype.name == "category"
            or s.dtype == bool
            or s.nunique() <= 20
        )

        fig, ax = plt.subplots(figsize=_FIGSIZE_DEFAULT)

        if is_categorical:
            value_counts = s.value_counts().sort_index()
            ax.bar(
                [str(v) for v in value_counts.index],
                value_counts.values,
                color=cmap[: len(value_counts)] if len(value_counts) <= 10 else cmap,
            )
            ax.set_xlabel("클래스")
            ax.set_ylabel("빈도")
        else:
            ax.hist(s.dropna(), bins=30, color=cmap[0], edgecolor="white", alpha=0.85)
            ax.set_xlabel("값")
            ax.set_ylabel("빈도")

        ax.set_title(title)
        plt.tight_layout()
        plt.savefig(save_path, dpi=_DPI)
        plt.close(fig)

        log.info(
            "타겟_분포_저장",
            path=str(save_path),
            dtype=str(s.dtype),
            is_categorical=is_categorical,
        )
        return save_path
