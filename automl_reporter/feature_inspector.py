"""
automl_reporter/feature_inspector.py — 자동 데이터 프로파일링 모듈.

컬럼 타입 감지, 텍스트 컬럼 감지, 타겟 컬럼 추천,
전처리 제안 기능을 제공한다.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

import pandas as pd

from shared.logger import get_logger

log = get_logger(__name__)

_TARGET_KEYWORDS: list[str] = ["target", "label", "class", "y"]
_HIGH_CARDINALITY_THRESHOLD: int = 50
_TEXT_AVG_LEN_THRESHOLD: float = 30.0
_TEXT_UNIQUE_RATIO_THRESHOLD: float = 0.5
_CORRELATION_THRESHOLD: float = 0.9
_MISSING_RATIO_WARN: float = 0.05


class FeatureInspector:
    """자동 데이터 프로파일링.

    DataFrame을 입력받아 컬럼 타입 감지, 텍스트 컬럼 감지,
    타겟 컬럼 추천, 전처리 제안 등의 프로파일링 결과를 생성한다.

    Args:
        df: 프로파일링할 pandas DataFrame.
    """

    def __init__(self, df: pd.DataFrame) -> None:
        """FeatureInspector를 초기화한다.

        Args:
            df: 프로파일링 대상 DataFrame.
        """
        self._df = df.copy()
        log.info(
            "feature_inspector_init",
            rows=df.shape[0],
            cols=df.shape[1],
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def profile(self) -> dict[str, Any]:
        """전체 데이터 프로파일을 생성한다.

        Returns:
            다음 키를 포함하는 딕셔너리:
            - ``shape``: (행 수, 열 수)
            - ``dtypes``: 컬럼명 → dtype 문자열
            - ``missing``: 컬럼명 → 결측률(0.0~1.0)
            - ``numeric_columns``: 수치형 컬럼 목록
            - ``categorical_columns``: 범주형 컬럼 목록
            - ``text_columns``: 텍스트 컬럼 목록
            - ``constant_columns``: 고유값이 1개뿐인 컬럼 목록
            - ``high_cardinality``: nunique > 50 인 컬럼 목록
            - ``correlations``: "col1_col2" → 상관계수 (|r| > 0.9 인 쌍만)
            - ``summary_stats``: ``df.describe().to_dict()`` 결과
        """
        df = self._df

        dtypes: dict[str, str] = {
            col: str(df[col].dtype) for col in df.columns
        }

        missing: dict[str, float] = {
            col: float(df[col].isna().mean()) for col in df.columns
        }

        numeric_columns: list[str] = df.select_dtypes(
            include="number"
        ).columns.tolist()

        text_columns: list[str] = self.detect_text_columns()

        # object 컬럼 중 텍스트가 아닌 것 → 범주형
        object_cols: list[str] = df.select_dtypes(
            include="object"
        ).columns.tolist()
        categorical_columns: list[str] = [
            c for c in object_cols if c not in text_columns
        ]

        constant_columns: list[str] = [
            col for col in df.columns if df[col].nunique(dropna=False) <= 1
        ]

        high_cardinality: list[str] = [
            col
            for col in df.columns
            if df[col].nunique() > _HIGH_CARDINALITY_THRESHOLD
        ]

        correlations: dict[str, float] = self._compute_high_correlations()

        summary_stats: dict[str, Any] = df.describe().to_dict()

        result: dict[str, Any] = {
            "shape": df.shape,
            "dtypes": dtypes,
            "missing": missing,
            "numeric_columns": numeric_columns,
            "categorical_columns": categorical_columns,
            "text_columns": text_columns,
            "constant_columns": constant_columns,
            "high_cardinality": high_cardinality,
            "correlations": correlations,
            "summary_stats": summary_stats,
        }

        log.info("profile_generated", shape=df.shape)
        return result

    def detect_text_columns(self) -> list[str]:
        """텍스트 컬럼을 감지한다.

        아래 세 조건을 모두 만족하는 object 컬럼을 텍스트 컬럼으로 판단한다:

        1. dtype == object
        2. 비결측 값의 평균 문자열 길이 > 30
        3. 유니크 비율(nunique / 비결측 수) > 0.5

        Returns:
            텍스트 컬럼명 목록.
        """
        df = self._df
        text_cols: list[str] = []

        for col in df.select_dtypes(include="object").columns:
            non_null: pd.Series = df[col].dropna()
            if non_null.empty:
                continue

            avg_len: float = non_null.astype(str).str.len().mean()
            unique_ratio: float = non_null.nunique() / len(non_null)

            if (
                avg_len > _TEXT_AVG_LEN_THRESHOLD
                and unique_ratio > _TEXT_UNIQUE_RATIO_THRESHOLD
            ):
                text_cols.append(col)
                log.debug(
                    "text_column_detected",
                    col=col,
                    avg_len=round(avg_len, 2),
                    unique_ratio=round(unique_ratio, 3),
                )

        return text_cols

    def suggest_target(self) -> str | None:
        """타겟 컬럼을 추천한다.

        우선순위:
        1. 컬럼명이 ``target``, ``label``, ``class``, ``y`` 중 하나와
           대소문자 무관하게 일치하는 컬럼 (순서대로 먼저 매칭되는 것)
        2. 위 조건 없으면 마지막 컬럼 중 분류(nunique <= 20) 또는
           회귀(수치형) 가능한 컬럼

        Returns:
            추천 타겟 컬럼명. 적절한 컬럼이 없으면 ``None``.
        """
        df = self._df
        lower_cols: dict[str, str] = {
            col.lower(): col for col in df.columns
        }

        for keyword in _TARGET_KEYWORDS:
            if keyword in lower_cols:
                candidate = lower_cols[keyword]
                log.info("target_suggested_by_name", col=candidate, keyword=keyword)
                return candidate

        # 마지막 컬럼 평가
        if df.columns.empty:
            return None

        last_col: str = df.columns[-1]
        last_series: pd.Series = df[last_col]

        is_numeric: bool = pd.api.types.is_numeric_dtype(last_series)
        nunique: int = last_series.nunique()
        is_classifiable: bool = nunique <= 20

        if is_numeric or is_classifiable:
            log.info(
                "target_suggested_by_last_col",
                col=last_col,
                is_numeric=is_numeric,
                nunique=nunique,
            )
            return last_col

        log.info("target_not_found")
        return None

    def get_preprocessing_suggestions(self) -> list[str]:
        """전처리 제안 목록을 반환한다.

        분석 항목:
        - 결측률 5% 초과 컬럼: 수치형이면 중앙값, 범주형이면 최빈값 대체 추천
        - 텍스트 컬럼: NLP 전처리 추천
        - 상관계수 0.9 초과 쌍: 하나 제거 추천
        - 고유값 1개인 상수 컬럼: 제거 추천
        - 높은 카디널리티 컬럼: 인코딩 전략 추천

        Returns:
            전처리 제안 문자열 목록.
        """
        df = self._df
        suggestions: list[str] = []

        numeric_cols: set[str] = set(
            df.select_dtypes(include="number").columns.tolist()
        )
        text_cols: set[str] = set(self.detect_text_columns())

        # 결측치 제안
        for col in df.columns:
            ratio: float = float(df[col].isna().mean())
            if ratio > _MISSING_RATIO_WARN:
                pct: str = f"{ratio * 100:.1f}%"
                if col in numeric_cols:
                    suggestions.append(
                        f"{col}에 결측 {pct} → 중앙값 대체 추천"
                    )
                else:
                    suggestions.append(
                        f"{col}에 결측 {pct} → 최빈값 대체 추천"
                    )

        # 텍스트 컬럼 제안
        for col in text_cols:
            suggestions.append(
                f"{col}는 텍스트 컬럼 → NLP 전처리 추천"
            )

        # 고상관 쌍 제안
        correlations: dict[str, float] = self._compute_high_correlations()
        for pair_key, corr_val in correlations.items():
            col_a, col_b = pair_key.split("_", 1)
            suggestions.append(
                f"{col_a}과 {col_b} 상관계수 {corr_val:.2f} → 하나 제거 추천"
            )

        # 상수 컬럼 제안
        for col in df.columns:
            if df[col].nunique(dropna=False) <= 1:
                suggestions.append(
                    f"{col}은 상수 컬럼(고유값 1개) → 제거 추천"
                )

        # 높은 카디널리티 제안
        for col in df.columns:
            if df[col].nunique() > _HIGH_CARDINALITY_THRESHOLD:
                if col not in text_cols and col not in numeric_cols:
                    suggestions.append(
                        f"{col}은 카디널리티 높음(nunique={df[col].nunique()}) "
                        f"→ 타겟 인코딩 또는 빈도 인코딩 추천"
                    )

        log.info(
            "preprocessing_suggestions_generated",
            count=len(suggestions),
        )
        return suggestions

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_high_correlations(self) -> dict[str, float]:
        """절댓값 상관계수가 임계치를 초과하는 수치형 컬럼 쌍을 반환한다.

        Returns:
            "colA_colB" → 상관계수 딕셔너리 (|r| > 0.9 인 쌍만 포함).
        """
        df = self._df
        numeric_df: pd.DataFrame = df.select_dtypes(include="number")

        if numeric_df.shape[1] < 2:
            return {}

        corr_matrix: pd.DataFrame = numeric_df.corr()
        result: dict[str, float] = {}

        for col_a, col_b in combinations(numeric_df.columns, 2):
            val: float = corr_matrix.loc[col_a, col_b]
            if pd.isna(val):
                continue
            if abs(val) > _CORRELATION_THRESHOLD:
                key: str = f"{col_a}_{col_b}"
                result[key] = round(float(val), 4)

        return result
