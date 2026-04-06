"""
automl_reporter/report_builder.py — AutoML 결과 PDF 리포트 빌더.

사용법:
    from pathlib import Path
    from automl_reporter.report_builder import AutoMLReportBuilder

    builder = AutoMLReportBuilder(result)
    output = builder.build(Path("output/report.pdf"))
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from automl_reporter.runner import AutoMLResult, TaskType
from automl_reporter.visualizer import Visualizer
from shared.logger import get_logger
from shared.report_generator import ReportGenerator

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# 태스크 유형별 한국어 설명
# ---------------------------------------------------------------------------

_TASK_TYPE_LABELS: dict[TaskType, str] = {
    TaskType.BINARY_CLASSIFICATION: "이진 분류 (Binary Classification)",
    TaskType.MULTICLASS_CLASSIFICATION: "다중 분류 (Multiclass Classification)",
    TaskType.REGRESSION: "회귀 (Regression)",
    TaskType.CLUSTERING: "군집화 (Clustering)",
}

_TASK_TYPE_REASONS: dict[TaskType, str] = {
    TaskType.BINARY_CLASSIFICATION: (
        "타겟 변수의 고유값이 2개로 확인되어 이진 분류 문제로 설정했습니다. "
        "Accuracy, F1, AUC 등 분류 지표로 모델을 평가합니다."
    ),
    TaskType.MULTICLASS_CLASSIFICATION: (
        "타겟 변수의 고유값이 3개 이상 20개 이하이며 범주형으로 확인되어 "
        "다중 분류 문제로 설정했습니다. Accuracy, F1(weighted) 등을 기준으로 평가합니다."
    ),
    TaskType.REGRESSION: (
        "타겟 변수가 연속형 수치 데이터로 확인되어 회귀 문제로 설정했습니다. "
        "RMSE, MAE, R² 지표로 모델 성능을 평가합니다."
    ),
    TaskType.CLUSTERING: (
        "타겟 변수가 지정되지 않아 비지도 군집화 문제로 설정했습니다. "
        "실루엣 점수(Silhouette Score)와 Inertia로 군집 품질을 평가합니다."
    ),
}

# 태스크 유형별 주요 메트릭 (모델 비교 차트에 사용)
_PRIMARY_METRIC: dict[TaskType, str] = {
    TaskType.BINARY_CLASSIFICATION: "accuracy",
    TaskType.MULTICLASS_CLASSIFICATION: "accuracy",
    TaskType.REGRESSION: "rmse",
    TaskType.CLUSTERING: "silhouette_score",
}


class AutoMLReportBuilder:
    """모델 비교 PDF 리포트 빌더.

    2페이지 PDF 리포트:
    Page 1:
      - 데이터 요약 (행/열, 타겟 분포, 결측률)
      - 문제 유형 + 선택 이유
      - 모델 비교 차트 (bar chart)
      - 최적 모델 추천 + 이유

    Page 2:
      - Feature Importance Top 10 (bar chart)
      - 하이퍼파라미터/메트릭 요약 테이블
      - 다음 단계 제안 (인사이트)

    Args:
        result: AutoMLRunner.run()이 반환한 AutoMLResult 인스턴스.
    """

    def __init__(self, result: AutoMLResult) -> None:
        """초기화. Visualizer 인스턴스 생성."""
        self._result = result
        self._viz = Visualizer()
        log.info(
            "AutoMLReportBuilder_초기화",
            task_type=result.task_type.value,
            best_model=result.best_model_name,
            n_models=len(result.model_results),
        )

    def build(self, output_path: Path) -> Path:
        """PDF 리포트 빌드.

        1. ReportGenerator 생성 (title="AutoML 분석 리포트")
        2. Page 1 내용 추가
        3. Page 2 내용 추가
        4. save

        Args:
            output_path: 저장할 PDF 파일 경로.

        Returns:
            저장된 PDF 파일의 절대 Path.
        """
        log.info("리포트_빌드_시작", output_path=str(output_path))

        rg = ReportGenerator(title="AutoML 분석 리포트")
        self._build_page1(rg)
        self._build_page2(rg)
        saved = rg.save(Path(output_path))

        log.info("리포트_빌드_완료", path=str(saved))
        return saved

    # ------------------------------------------------------------------
    # Page 1
    # ------------------------------------------------------------------

    def _build_page1(self, rg: ReportGenerator) -> None:
        """데이터 요약, 문제 유형, 모델 비교 차트, 최적 모델 추천."""
        result = self._result
        ds = result.data_summary

        # ── 1. 데이터 요약 ──────────────────────────────────────────────
        rows = ds.get("rows", "N/A")
        columns = ds.get("columns", "N/A")

        # 결측률 요약 (상위 5개)
        missing_pct: dict[str, float] = ds.get("missing_pct", {})
        high_missing = sorted(
            [(col, pct) for col, pct in missing_pct.items() if pct > 0],
            key=lambda x: x[1],
            reverse=True,
        )[:5]
        if high_missing:
            missing_summary = ", ".join(
                f"{col}: {pct:.1f}%" for col, pct in high_missing
            )
        else:
            missing_summary = "결측값 없음"

        # 타겟 분포 요약
        target_dist: dict | None = ds.get("target_distribution")
        if target_dist is None:
            target_summary = "타겟 변수 없음 (군집화)"
        elif "mean" in target_dist:
            target_summary = (
                f"평균 {target_dist['mean']:.4f}, "
                f"표준편차 {target_dist['std']:.4f}, "
                f"범위 [{target_dist['min']:.4f}, {target_dist['max']:.4f}]"
            )
        else:
            top_classes = sorted(
                target_dist.items(), key=lambda x: x[1], reverse=True
            )[:5]
            target_summary = ", ".join(
                f"{cls}: {ratio * 100:.1f}%" for cls, ratio in top_classes
            )

        data_content = (
            f"전체 행 수: {rows:,}개\n"
            f"전체 열 수: {columns}개\n"
            f"결측률 (상위): {missing_summary}\n"
            f"타겟 분포: {target_summary}"
        )
        rg.add_section("1. 데이터 요약", data_content)

        # ── 2. 문제 유형 ────────────────────────────────────────────────
        task_label = _TASK_TYPE_LABELS.get(
            result.task_type, result.task_type.value
        )
        task_reason = _TASK_TYPE_REASONS.get(result.task_type, "")
        task_content = f"감지된 문제 유형: {task_label}\n\n{task_reason}"
        rg.add_section("2. 문제 유형", task_content)

        # ── 3. 모델 비교 차트 ────────────────────────────────────────────
        primary_metric = _PRIMARY_METRIC.get(result.task_type, "accuracy")
        model_names: list[str] = []
        scores: list[float] = []

        for mr in result.model_results:
            score = mr.metrics.get(primary_metric)
            if score is not None:
                model_names.append(mr.name)
                scores.append(score)

        if model_names and scores:
            with tempfile.TemporaryDirectory() as tmp_dir:
                chart_path = Path(tmp_dir) / "model_comparison.png"
                try:
                    saved_chart = self._viz.model_comparison_bar(
                        model_names=model_names,
                        scores=scores,
                        metric_name=primary_metric.upper(),
                        output_path=chart_path,
                        title=f"모델 비교 ({primary_metric.upper()})",
                    )
                    rg.add_chart(
                        saved_chart,
                        caption=f"모델별 {primary_metric.upper()} 성능 비교",
                    )
                    log.info("모델_비교_차트_추가_완료")
                except Exception as exc:
                    log.error("모델_비교_차트_생성_실패", error=str(exc))
        else:
            rg.add_section(
                "3. 모델 비교",
                f"'{primary_metric}' 메트릭 데이터가 없어 차트를 생성할 수 없습니다.",
            )

        # ── 4. 최적 모델 추천 ────────────────────────────────────────────
        best_metrics_str = ", ".join(
            f"{k}: {v:.4f}" for k, v in result.best_metrics.items()
        )
        tuned_flag = ""
        for mr in result.model_results:
            if mr.name == result.best_model_name and mr.is_tuned:
                tuned_flag = " (하이퍼파라미터 튜닝 완료)"
                break

        best_content = (
            f"추천 모델: {result.best_model_name}{tuned_flag}\n"
            f"핵심 지표: {best_metrics_str if best_metrics_str else 'N/A'}\n\n"
            f"선정 기준: {primary_metric.upper()} 기준 전체 모델 중 최고 성능을 기록했습니다."
        )
        rg.add_section("4. 최적 모델 추천", best_content)

        log.debug("Page1_완료")

    # ------------------------------------------------------------------
    # Page 2
    # ------------------------------------------------------------------

    def _build_page2(self, rg: ReportGenerator) -> None:
        """Feature Importance, 메트릭 테이블, 다음 단계 제안."""
        result = self._result

        # ── 5. Feature Importance ────────────────────────────────────────
        if result.feature_importance:
            with tempfile.TemporaryDirectory() as tmp_dir:
                fi_path = Path(tmp_dir) / "feature_importance.png"
                try:
                    saved_fi = self._viz.feature_importance(
                        importances=result.feature_importance,
                        top_k=10,
                        output_path=fi_path,
                        title="피처 중요도 Top 10",
                    )
                    rg.add_chart(saved_fi, caption="피처 중요도 상위 10개")
                    log.info("피처_중요도_차트_추가_완료")
                except Exception as exc:
                    log.error("피처_중요도_차트_생성_실패", error=str(exc))
        else:
            rg.add_section(
                "5. 피처 중요도",
                "현재 문제 유형 또는 모델에서 피처 중요도 정보를 제공하지 않습니다.",
            )

        # ── 6. 메트릭 요약 테이블 ─────────────────────────────────────────
        all_metric_keys: list[str] = []
        for mr in result.model_results:
            for k in mr.metrics:
                if k not in all_metric_keys:
                    all_metric_keys.append(k)

        if all_metric_keys:
            headers = (
                ["모델", "튜닝 여부", "학습 시간(s)"]
                + [k.upper() for k in all_metric_keys]
            )
            rows: list[list[str]] = []
            for mr in result.model_results:
                row: list[str] = [
                    mr.name,
                    "O" if mr.is_tuned else "X",
                    f"{mr.training_time_seconds:.2f}",
                ]
                for k in all_metric_keys:
                    val = mr.metrics.get(k)
                    row.append(f"{val:.4f}" if val is not None else "-")
                rows.append(row)

            rg.add_section("6. 모델 메트릭 요약", "")
            rg.add_table(headers=headers, rows=rows)
            log.info("메트릭_테이블_추가_완료", models=len(rows))
        else:
            rg.add_section(
                "6. 모델 메트릭 요약",
                "메트릭 데이터가 없습니다.",
            )

        # ── 7. 다음 단계 제안 ────────────────────────────────────────────
        recommendations = self._generate_recommendations()
        insight_text = "\n".join(
            f"{i + 1}. {rec}" for i, rec in enumerate(recommendations)
        )
        rg.add_insight(insight_text)

        log.debug("Page2_완료")

    # ------------------------------------------------------------------
    # 헬퍼
    # ------------------------------------------------------------------

    def _get_task_type_description(self) -> str:
        """문제 유형 설명 한국어 문자열 반환.

        Returns:
            태스크 유형에 해당하는 한국어 레이블 문자열.
        """
        return _TASK_TYPE_LABELS.get(
            self._result.task_type, self._result.task_type.value
        )

    def _generate_recommendations(self) -> list[str]:
        """분석 결과 기반 다음 단계 추천 3줄.

        Returns:
            추천 문자열 3개가 담긴 리스트.
        """
        result = self._result
        recs: list[str] = []

        # 추천 1: Feature Importance 기반
        if result.feature_importance:
            top3 = sorted(
                result.feature_importance.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:3]
            top3_names = ", ".join(f"'{name}'" for name, _ in top3)
            recs.append(
                f"피처 중요도 상위 3개({top3_names}) 집중 분석 및 도메인 해석을 추천합니다."
            )
        else:
            recs.append(
                "트리 기반 모델(Random Forest, GBM 등)로 재실험하여 피처 중요도를 확보하세요."
            )

        # 추천 2: 최적 모델 튜닝 여부 기반
        best_is_tuned = any(
            mr.name == result.best_model_name and mr.is_tuned
            for mr in result.model_results
        )
        if best_is_tuned:
            recs.append(
                f"'{result.best_model_name}'은 이미 튜닝된 모델입니다. "
                "더 많은 CV fold(예: 10-fold) 또는 앙상블 기법으로 추가 성능 향상을 시도해 보세요."
            )
        else:
            recs.append(
                f"'{result.best_model_name}'에 대해 하이퍼파라미터 튜닝(Optuna, GridSearch 등)을 "
                "적용하면 추가 성능 개선을 기대할 수 있습니다."
            )

        # 추천 3: 결측률 기반
        missing_pct: dict[str, float] = result.data_summary.get("missing_pct", {})
        high_missing_cols = [
            col for col, pct in missing_pct.items() if pct >= 20.0
        ]
        if high_missing_cols:
            cols_str = ", ".join(f"'{c}'" for c in high_missing_cols[:3])
            recs.append(
                f"결측률 20% 이상인 피처({cols_str})에 대한 결측 처리 전략(대체 또는 제거)을 "
                "재검토하면 모델 안정성을 높일 수 있습니다."
            )
        else:
            recs.append(
                "결측값이 없거나 낮아 데이터 품질이 양호합니다. "
                "클래스 불균형 여부를 확인하고 필요 시 오버샘플링(SMOTE 등)을 적용하세요."
            )

        return recs
